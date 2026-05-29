"""
Email routes.

GET  /emails                            — list threads with filters and pagination
GET  /emails/search                     — full-text search across threads
GET  /emails/{thread_id}                — get a single thread with its messages
POST /emails/{thread_id}/categorize     — manually re-trigger categorization
PUT  /emails/{thread_id}/assign         — assign / unassign a thread to a user
PUT  /emails/{thread_id}/status         — manually change thread status
POST /emails/bulk                       — bulk close / assign / recategorize
GET  /emails/{thread_id}/drafts         — list draft responses for a thread
PUT  /emails/{thread_id}/drafts/{draft_id} — update a draft (review/edit)
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime, date, timezone
from typing import AsyncGenerator, DefaultDict, Literal

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_client_ip, get_current_user, require_csrf

logger = logging.getLogger(__name__)


def _parse_iso_utc(s: str) -> datetime:
    """Parse an ISO 8601 datetime string and ensure it is UTC-aware.

    Python's ``datetime.fromisoformat`` leaves naive datetimes (those without a
    timezone offset) as-is.  A naive datetime compared against timezone-aware
    column values in SQLAlchemy produces wrong query results on some backends.
    This helper always returns an aware datetime in UTC so filter comparisons
    are unambiguous.
    """
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
from app.database import get_db
from app.models.email import (
    CategorizationSource,
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.services.tier_engine import decide_tier
from app.models.escalation import Escalation, EscalationStatus
from app.models.user import User
from app.schemas.email import (
    AddThreadToKnowledgeBaseRequest,
    AssignRequest,
    BulkActionRequest,
    BulkActionResponse,
    ComposeDraftRequest,
    ComposeDraftResponse,
    DraftResponseResponse,
    EmailThreadListItem,
    EmailThreadListResponse,
    EmailThreadResponse,
    ManualDraftRequest,
    SaveThreadRequest,
    SavedFolder,
    SavedMessageItem,
    StatusChangeRequest,
    UpdateDraftRequest,
)
from app.models.email import KnowledgeEntry
from app.schemas.knowledge import KnowledgeEntryResponse
from app.schemas.escalation import EscalationResponse
from app.services.categorizer import get_categorizer
from app.services.escalation import get_escalation_engine
from app.utils.audit import log_action
from app.utils.rate_limit import check_ai_rate_limit, record_ai_call

router = APIRouter(prefix="/emails", tags=["emails"])


# ── Allowed status transitions for manual status changes ──────────────────────
# Maps current status -> set of allowed target statuses
_ALLOWED_TRANSITIONS: dict[EmailStatus, set[EmailStatus]] = {
    EmailStatus.new:            {EmailStatus.closed, EmailStatus.pending_review},
    EmailStatus.categorized:    {EmailStatus.closed, EmailStatus.pending_review},
    EmailStatus.draft_ready:    {EmailStatus.closed, EmailStatus.pending_review},
    EmailStatus.pending_review: {EmailStatus.closed},
    EmailStatus.sent:           {EmailStatus.closed},
    EmailStatus.escalated:      {EmailStatus.closed, EmailStatus.pending_review},
    EmailStatus.closed:         {EmailStatus.categorized},  # "reopen"
}


# ── Search endpoint (declared before /{thread_id} to avoid routing conflict) ──

@router.get("/search", response_model=EmailThreadListResponse)
def search_threads(
    q: str = Query(min_length=1, max_length=500),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadListResponse:
    """
    Full-text search across thread subject, AI summary, client email, client name,
    and message body text. Returns deduplicated, paginated threads.
    """
    term = f"%{q}%"

    # Subquery: thread IDs matched by message body search
    matched_by_body = (
        select(EmailMessage.thread_id)
        .where(EmailMessage.body_text.ilike(term))
        .distinct()
        .subquery()
    )

    base_filter = or_(
        EmailThread.subject.ilike(term),
        EmailThread.ai_summary.ilike(term),
        EmailThread.client_email.ilike(term),
        EmailThread.client_name.ilike(term),
        EmailThread.id.in_(select(matched_by_body.c.thread_id)),
    )

    count_query = select(func.count(EmailThread.id)).where(base_filter)
    total = db.execute(count_query).scalar_one()

    offset = (page - 1) * page_size

    msg_count_subq = (
        select(
            EmailMessage.thread_id,
            func.count(EmailMessage.id).label("message_count"),
        )
        .group_by(EmailMessage.thread_id)
        .subquery()
    )

    paged_query = (
        select(EmailThread, func.coalesce(msg_count_subq.c.message_count, 0).label("message_count"))
        .outerjoin(msg_count_subq, EmailThread.id == msg_count_subq.c.thread_id)
        .options(selectinload(EmailThread.assigned_to))
        .where(base_filter)
        .order_by(EmailThread.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    rows = db.execute(paged_query).all()

    items: list[EmailThreadListItem] = []
    for thread, msg_count in rows:
        item = EmailThreadListItem.model_validate(thread)
        item.message_count = msg_count
        item.assigned_to_name = thread.assigned_to.name if thread.assigned_to else None
        items.append(item)

    return EmailThreadListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


# ── Bulk action endpoint (also before /{thread_id}) ───────────────────────────

@router.post("/bulk", response_model=BulkActionResponse, dependencies=[Depends(require_csrf)])
def bulk_action(
    request: Request,
    body: BulkActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkActionResponse:
    """
    Perform a bulk action (close / assign / recategorize) on multiple threads.
    Returns counts of succeeded and failed operations.
    """
    succeeded = 0
    failed = 0
    errors: list[str] = []
    # Connected lazily on the first delete/spam thread and reused across the
    # batch so we don't reconnect to Graph per thread.
    _bulk_provider = None

    for thread_id in body.thread_ids:
        try:
            thread = db.execute(
                select(EmailThread).where(EmailThread.id == thread_id)
            ).scalar_one_or_none()

            if thread is None:
                failed += 1
                errors.append(f"{thread_id}: not found")
                continue

            if body.action == "close":
                allowed = _ALLOWED_TRANSITIONS.get(thread.status, set())
                if EmailStatus.closed not in allowed:
                    failed += 1
                    errors.append(
                        f"{thread_id}: cannot close a thread with status '{thread.status.value}'"
                    )
                    continue
                prev_status = thread.status.value
                thread.status = EmailStatus.closed
                thread.updated_at = datetime.now(timezone.utc)
                log_action(
                    db,
                    action="email.bulk_closed",
                    entity_type="email_thread",
                    entity_id=str(thread.id),
                    user_id=current_user.id,
                    ip_address=get_client_ip(request),
                    details={"previous_status": prev_status},
                )

            elif body.action == "assign":
                previous_assignee = str(thread.assigned_to_id) if thread.assigned_to_id else None
                thread.assigned_to_id = body.params.user_id
                thread.updated_at = datetime.now(timezone.utc)
                log_action(
                    db,
                    action="email.bulk_assigned",
                    entity_type="email_thread",
                    entity_id=str(thread.id),
                    user_id=current_user.id,
                    ip_address=get_client_ip(request),
                    details={
                        "previous_assignee_id": previous_assignee,
                        "new_assignee_id": str(body.params.user_id) if body.params.user_id else None,
                    },
                )

            elif body.action == "recategorize":
                thread_with_msgs = db.execute(
                    select(EmailThread)
                    .options(selectinload(EmailThread.messages))
                    .where(EmailThread.id == thread_id)
                ).scalar_one()
                inbound = [m for m in thread_with_msgs.messages if m.direction.value == "inbound"]
                if not inbound:
                    failed += 1
                    errors.append(f"{thread_id}: no inbound messages to recategorize")
                    continue
                latest = max(inbound, key=lambda m: m.received_at)
                body_text = latest.body_text or latest.body_html or ""
                categorizer = get_categorizer()
                result = categorizer.categorize(
                    sender=latest.sender,
                    subject=thread.subject,
                    body=body_text,
                )

                before_tier = thread.tier
                before_category = thread.category

                thread.category = result.category
                thread.category_confidence = result.confidence
                thread.ai_summary = result.summary
                thread.suggested_reply_tone = result.suggested_reply_tone
                thread.categorization_source = result.source
                thread.status = EmailStatus.categorized
                thread.updated_at = datetime.now(timezone.utc)

                # Phase 3: re-decide tier (same reason as manual_categorize).
                tier_decision = decide_tier(db, result=result, source=result.source)
                thread.tier = tier_decision.tier
                thread.tier_set_at = datetime.now(timezone.utc)
                thread.tier_set_by = current_user.email or "bulk-recategorize"

                log_action(
                    db,
                    action="email.bulk_recategorized",
                    entity_type="email_thread",
                    entity_id=str(thread.id),
                    user_id=current_user.id,
                    ip_address=get_client_ip(request),
                    details={
                        "before": {
                            "category": before_category.value,
                            "tier": before_tier.value,
                        },
                        "after": {
                            "category": result.category.value,
                            "tier": tier_decision.tier.value,
                        },
                        "confidence": result.confidence,
                    },
                )

            elif body.action in ("delete", "spam"):
                # Mirror the single-thread trash/spam endpoints: move every
                # inbound message to Outlook's Deleted Items / Junk Email and
                # park the thread in the matching terminal status.
                if body.action == "delete":
                    target_status = EmailStatus.deleted
                    destination = "deleted_items"
                    audit_action = "thread.deleted"
                    other_terminal = EmailStatus.spam
                else:
                    target_status = EmailStatus.spam
                    destination = "junk_email"
                    audit_action = "thread.marked_spam"
                    other_terminal = EmailStatus.deleted

                if thread.status == target_status:
                    # Already there — idempotent no-op success, no Graph call.
                    succeeded += 1
                    continue
                if thread.status == other_terminal:
                    # Cross-terminal (deleted<->spam) — refuse per-thread, same
                    # rule as the single endpoint's 409. Restore first.
                    failed += 1
                    errors.append(
                        f"{thread_id}: in '{thread.status.value}' — restore before re-classifying"
                    )
                    continue

                if _bulk_provider is None:
                    from app.services.email_provider import get_email_provider
                    _bulk_provider = get_email_provider()
                    _bulk_provider.connect()
                _perform_terminal_move(
                    db=db,
                    request=request,
                    thread=thread,
                    target_status=target_status,
                    destination=destination,
                    audit_action=audit_action,
                    provider=_bulk_provider,
                    current_user=current_user,
                )

            elif body.action == "save":
                was_saved = thread.is_saved
                thread.is_saved = True
                thread.saved_folder = body.params.folder or None
                thread.saved_at = datetime.now(timezone.utc)
                thread.saved_by_id = current_user.id
                thread.updated_at = datetime.now(timezone.utc)
                log_action(
                    db,
                    action="email.bulk_saved" if not was_saved else "email.bulk_save_updated",
                    entity_type="email_thread",
                    entity_id=str(thread.id),
                    user_id=current_user.id,
                    ip_address=get_client_ip(request),
                    details={"folder": body.params.folder or None},
                )

            db.flush()
            succeeded += 1

        except Exception as exc:
            failed += 1
            errors.append(f"{thread_id}: {exc}")

    return BulkActionResponse(succeeded=succeeded, failed=failed, errors=errors)


# ── Export daily rate-limit tracker (T1.18) ───────────────────────────────────
# Tracks per-user export counts per calendar day: {(user_id, date): count}
# Module-level dict is safe here: only admin users can reach this endpoint,
# and the process-level singleton is acceptable for V1 (single-replica deploy).
_export_rate_lock = threading.Lock()
_export_counts: DefaultDict[tuple[uuid.UUID, date], int] = defaultdict(int)
_EXPORT_DAILY_LIMIT = 10


def _check_export_rate_limit(user_id: uuid.UUID) -> None:
    today = datetime.now(timezone.utc).date()
    with _export_rate_lock:
        key = (user_id, today)
        if _export_counts[key] >= _EXPORT_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Export rate limit reached. Maximum {_EXPORT_DAILY_LIMIT} "
                    "full exports per day per user."
                ),
            )
        _export_counts[key] += 1


# ── Export / compliance report ─────────────────────────────────────────────────
# NOTE: Declared before /{thread_id} to avoid routing conflict (FastAPI matches
# in declaration order and "export" would otherwise be captured as a thread UUID).

@router.get("/export")
def export_threads(
    client_email: str | None = Query(default=None),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    offset: int = Query(default=0, ge=0, description="Number of threads to skip"),
    limit: int = Query(default=100, ge=1, le=500, description="Max threads per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Export threads with all messages, drafts, and escalations.
    Admin only. Used for compliance reporting.

    T1.18:
      - Paginated via offset/limit (max 500 per page).
      - Rate-limited to 10 full exports per user per day.
      - Streaming JSON-lines response (one JSON object per line).
    """
    if current_user.role.value != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    # Rate limit check
    _check_export_rate_limit(current_user.id)

    query = select(EmailThread).options(
        selectinload(EmailThread.messages),
        selectinload(EmailThread.drafts),
        selectinload(EmailThread.escalations),
    )

    if client_email:
        safe_email = client_email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(EmailThread.client_email.ilike(f"%{safe_email}%", escape="\\"))

    if from_date:
        try:
            from_dt = _parse_iso_utc(from_date)
            query = query.where(EmailThread.created_at >= from_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid 'from' date. Use ISO 8601 format.",
            )

    if to_date:
        try:
            to_dt = _parse_iso_utc(to_date)
            query = query.where(EmailThread.created_at <= to_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid 'to' date. Use ISO 8601 format.",
            )

    threads = db.execute(
        query.order_by(EmailThread.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    def _iter_jsonlines() -> AsyncGenerator[str, None]:  # type: ignore[return]
        """Yield one JSON line per thread for memory-efficient streaming."""
        for t in threads:
            record = {
                "id": str(t.id),
                "subject": t.subject,
                "client_email": t.client_email,
                "client_name": t.client_name,
                "status": t.status.value,
                "category": t.category.value,
                "ai_summary": t.ai_summary,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
                "messages": [
                    {
                        "id": str(m.id),
                        "sender": m.sender,
                        "recipient": m.recipient,
                        "body_text": m.body_text,
                        "received_at": m.received_at.isoformat(),
                        "direction": m.direction.value,
                    }
                    for m in sorted(t.messages, key=lambda m: m.received_at)
                ],
                "drafts": [
                    {
                        "id": str(d.id),
                        "body_text": d.body_text,
                        "status": d.status.value,
                        "version": d.version,
                        "created_at": d.created_at.isoformat(),
                        "reviewed_at": d.reviewed_at.isoformat() if d.reviewed_at else None,
                    }
                    for d in sorted(t.drafts, key=lambda d: d.created_at)
                ],
                "escalations": [
                    {
                        "id": str(e.id),
                        "reason": e.reason,
                        "severity": e.severity.value,
                        "status": e.status.value,
                        "created_at": e.created_at.isoformat(),
                        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
                    }
                    for e in sorted(t.escalations, key=lambda e: e.created_at)
                ],
            }
            yield json.dumps(record, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _iter_jsonlines(),
        media_type="application/x-ndjson",
        headers={
            "X-Export-Count": str(len(threads)),
            "X-Export-Offset": str(offset),
        },
    )


# ── Thread list ───────────────────────────────────────────────────────────────

@router.get("", response_model=EmailThreadListResponse)
def list_threads(
    thread_status: EmailStatus | None = Query(default=None, alias="status"),
    category: EmailCategory | None = Query(default=None),
    tier: ThreadTier | None = Query(default=None, description="Filter by triage tier"),
    client_email: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None, description="'me' or a user UUID"),
    saved: bool | None = Query(default=None, description="Filter to saved threads only"),
    folder: str | None = Query(default=None, description="Filter to a specific saved folder"),
    sent_only: bool = Query(
        default=False,
        description="Show only threads containing at least one outbound (sent) message",
    ),
    sort: Literal[
        "updated_desc", "updated_asc",
        "subject_asc", "subject_desc",
        "client_asc", "client_desc",
    ] = Query(
        default="updated_desc",
        description="Sort order. Defaults to most-recently-updated first.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadListResponse:
    """List email threads with optional filters. Supports pagination."""
    query = select(EmailThread)

    if thread_status is not None:
        query = query.where(EmailThread.status == thread_status)
    else:
        # Default view hides the trash-management terminal states. A user
        # who wants to browse Deleted / Spam can do so by passing
        # `?status=deleted` or `?status=spam` explicitly, but the inbox
        # tab should never surface them by default — that's the whole
        # point of "trash" as a UX category.
        query = query.where(
            EmailThread.status.notin_([EmailStatus.deleted, EmailStatus.spam])
        )
    if category is not None:
        query = query.where(EmailThread.category == category)
    if saved is True:
        query = query.where(EmailThread.is_saved == True)  # noqa: E712
    elif saved is False:
        query = query.where(EmailThread.is_saved == False)  # noqa: E712
    if folder is not None:
        # Empty string folder means "saved but unsorted" — match NULL saved_folder.
        if folder == "":
            query = query.where(
                EmailThread.is_saved == True,  # noqa: E712
                EmailThread.saved_folder.is_(None),
            )
        else:
            query = query.where(EmailThread.saved_folder == folder)
    if sent_only:
        # "Sent" = any thread we've actually sent mail in — composed emails AND
        # approved reply-sends. Keyed off the presence of an outbound message
        # rather than a terminal status, so a resolved/closed thread still
        # appears if Jane replied in it (matches Outlook's Sent Items, which is
        # independent of Inbox read/closed state). Trash + spam threads are
        # still excluded by the default status filter above.
        outbound_exists = (
            select(EmailMessage.id)
            .where(
                EmailMessage.thread_id == EmailThread.id,
                EmailMessage.direction == MessageDirection.outbound,
            )
            .exists()
        )
        query = query.where(outbound_exists)
    if tier is not None:
        # The Escalated tab is what users mental-model as "everything that
        # needs Jane's attention." Tier and status are stored independently and
        # can drift (bulk re-categorize touches one but not the other; resolved
        # escalations clear status but leave tier; pre-tier-migration rows may
        # also be inconsistent). Match either column for t3 so a status-only
        # escalation never disappears from the tab.
        if tier == ThreadTier.t3_escalate:
            query = query.where(
                or_(
                    EmailThread.tier == ThreadTier.t3_escalate,
                    EmailThread.status == EmailStatus.escalated,
                )
            )
        else:
            query = query.where(EmailThread.tier == tier)
    if client_email:
        # Escape LIKE wildcards to prevent unintended pattern matching
        safe_email = client_email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            EmailThread.client_email.ilike(f"%{safe_email}%", escape="\\")
        )
    if assigned_to:
        if assigned_to == "me":
            query = query.where(EmailThread.assigned_to_id == current_user.id)
        else:
            try:
                filter_uid = uuid.UUID(assigned_to)
                query = query.where(EmailThread.assigned_to_id == filter_uid)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="assigned_to must be 'me' or a valid user UUID.",
                )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar_one()

    # Paginate — fetch threads with per-thread message counts in a single query
    offset = (page - 1) * page_size

    # Subquery: count of messages per thread
    msg_count_subq = (
        select(
            EmailMessage.thread_id,
            func.count(EmailMessage.id).label("message_count"),
        )
        .group_by(EmailMessage.thread_id)
        .subquery()
    )

    # Sort options. lower() on text sorts so client_email/subject sorts are
    # case-insensitive, which matches user mental-model ("Apex" and "apex"
    # belong next to each other, not in different halves of the list").
    sort_clause = {
        "updated_desc": EmailThread.updated_at.desc(),
        "updated_asc": EmailThread.updated_at.asc(),
        "subject_asc": func.lower(EmailThread.subject).asc(),
        "subject_desc": func.lower(EmailThread.subject).desc(),
        "client_asc": func.lower(EmailThread.client_email).asc(),
        "client_desc": func.lower(EmailThread.client_email).desc(),
    }[sort]

    paged_query = (
        select(EmailThread, func.coalesce(msg_count_subq.c.message_count, 0).label("message_count"))
        .outerjoin(msg_count_subq, EmailThread.id == msg_count_subq.c.thread_id)
        .options(selectinload(EmailThread.assigned_to))
        .where(query.whereclause if query.whereclause is not None else True)
        .order_by(sort_clause)
        .offset(offset)
        .limit(page_size)
    )

    rows = db.execute(paged_query).all()

    items: list[EmailThreadListItem] = []
    for thread, msg_count in rows:
        item = EmailThreadListItem.model_validate(thread)
        item.message_count = msg_count
        item.assigned_to_name = thread.assigned_to.name if thread.assigned_to else None
        items.append(item)

    return EmailThreadListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.get("/{thread_id}", response_model=EmailThreadResponse)
def get_thread(
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """Get a single email thread with all its messages."""
    thread = db.execute(
        select(EmailThread)
        .options(selectinload(EmailThread.messages), selectinload(EmailThread.assigned_to))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    return EmailThreadResponse.from_thread(thread)


@router.get("/{thread_id}/messages/{message_id}/attachments/{attachment_index}/download")
def download_attachment(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    attachment_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Stream an attachment's binary content from the email provider.

    Fetches on-demand rather than storing binaries server-side — keeps the
    DB lean and avoids retention / PII concerns around tax documents. Cost is
    one extra round-trip to MS Graph per click.

    Path: thread_id/message_id/attachment_index. Index matches the order
    stored on EmailMessage.attachments (non-inline only — inline images
    were filtered at poll time).
    """
    # Verify the thread-message relationship up front (security + clean 404)
    msg = db.execute(
        select(EmailMessage).where(
            EmailMessage.id == message_id,
            EmailMessage.thread_id == thread_id,
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found in this thread.",
        )

    attachments_meta = msg.attachments or []
    if not 0 <= attachment_index < len(attachments_meta):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Attachment index {attachment_index} out of range "
                f"(message has {len(attachments_meta)} attachments)."
            ),
        )

    # Persisted attachment_id when available (new polls); fall back to index
    # lookup for legacy rows.
    stored = attachments_meta[attachment_index]
    persisted_id = stored.get("attachment_id") if isinstance(stored, dict) else None

    from app.services.email_provider import get_email_provider
    provider = get_email_provider()
    try:
        provider.connect()
        content_iter, filename, content_type = provider.fetch_attachment(
            internet_message_id=msg.message_id_header,
            attachment_id=persisted_id,
            attachment_index=None if persisted_id else attachment_index,
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Current email provider does not support attachment download.",
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except IndexError as exc:
        # Provider's attachment list disagreed with our stored count (rare —
        # would mean the message was modified server-side).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except httpx.HTTPStatusError as exc:
        # Graph (or any other upstream provider) returned a non-2xx that the
        # provider's raise_for_status() bubbled up. Without this handler the
        # error fell through as a generic FastAPI 500 — but the failure isn't
        # in our service, it's upstream. 502 Bad Gateway is the honest
        # status: "I'm a gateway and the inbound server gave me garbage."
        # Log the upstream details for diagnostics; surface a generic message
        # to the client so we don't leak Graph internals.
        upstream_status = exc.response.status_code
        logger.warning(
            "Attachment download upstream failure: HTTP %d for message_id=%s "
            "attachment=%s response_body=%s",
            upstream_status,
            msg.message_id_header,
            persisted_id or f"index:{attachment_index}",
            exc.response.text[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Failed to fetch attachment from the email provider "
                f"(upstream returned HTTP {upstream_status}). Try again shortly."
            ),
        )

    # Stored size comes from the poll-time metadata so we don't need to
    # buffer the whole binary to know it. Falls back to None on legacy rows
    # that didn't persist size at poll time — in that case Content-Length is
    # omitted and the response uses chunked transfer encoding.
    stored_size = stored.get("size") if isinstance(stored, dict) else None

    # Audit-log the download — sensitive tax docs flow through this path.
    log_action(
        db,
        action="email.attachment_downloaded",
        entity_type="email_message",
        entity_id=str(message_id),
        details={
            "thread_id": str(thread_id),
            "filename": filename,
            "size": stored_size,
            "content_type": content_type,
            "attachment_index": attachment_index,
        },
        user_id=current_user.id,
    )
    db.commit()

    # `Content-Disposition: attachment` forces the browser to download rather
    # than render inline. We don't quote-escape the filename for legacy clients
    # — RFC 5987 encoding (filename*=UTF-8''...) handles non-ASCII filenames
    # in modern browsers without breaking older ones.
    import urllib.parse
    safe_ascii = filename.encode("ascii", errors="replace").decode("ascii")
    quoted_utf8 = urllib.parse.quote(filename)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{safe_ascii}"; '
            f"filename*=UTF-8''{quoted_utf8}"
        ),
    }
    if stored_size is not None:
        headers["Content-Length"] = str(stored_size)

    # content_iter streams chunks directly from the upstream provider — no
    # BytesIO wrap, no full-file buffer in memory. A 50MB attachment now
    # peaks at ~64KB resident (chunk size) instead of 50MB.
    return StreamingResponse(
        content_iter,
        media_type=content_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/{thread_id}/messages/{message_id}/inline/{content_id:path}")
def get_inline_image(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    content_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Stream an inline image (referenced by <img src="cid:..."> in the HTML body)
    on demand from the email provider, matched by Content-ID.

    Used by the message renderer to display embedded images like Outlook.
    Fetched live — never stored — mirroring the attachment-download model, so it
    works for already-polled messages with no migration. Not audited: a single
    email can reference many inline images and each render would flood the audit
    log; these are decorative body content, not deliberate document downloads.
    """
    msg = db.execute(
        select(EmailMessage).where(
            EmailMessage.id == message_id,
            EmailMessage.thread_id == thread_id,
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found in this thread.",
        )

    from app.services.email_provider import get_email_provider
    provider = get_email_provider()
    try:
        provider.connect()
        content_iter, content_type = provider.fetch_inline_attachment(
            internet_message_id=msg.message_id_header,
            content_id=content_id,
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Current email provider does not support inline images.",
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        logger.warning(
            "Inline image upstream failure: HTTP %d for message_id=%s cid=%s",
            upstream_status,
            msg.message_id_header,
            content_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Failed to fetch inline image from the email provider "
                f"(upstream returned HTTP {upstream_status})."
            ),
        )

    # Inline images are immutable for a given message+cid, so a short private
    # cache cuts repeat fetches when a thread re-renders. `private` keeps it out
    # of any shared cache since the bytes sit behind per-user auth.
    return StreamingResponse(
        content_iter,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{thread_id}/categorize", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def manual_categorize(
    request: Request,
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Manually re-trigger AI categorization on a thread.
    Uses the most recent inbound message as the input.
    """
    # Enforce per-user AI call rate limit before any DB work
    check_ai_rate_limit(current_user.id)

    thread = db.execute(
        select(EmailThread)
        .options(selectinload(EmailThread.messages))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    inbound_messages = [
        m for m in thread.messages if m.direction.value == "inbound"
    ]
    if not inbound_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No inbound messages found in this thread to categorize.",
        )

    latest = max(inbound_messages, key=lambda m: m.received_at)
    body = latest.body_text or latest.body_html or ""

    categorizer = get_categorizer()
    record_ai_call(current_user.id)
    result = categorizer.categorize(
        sender=latest.sender,
        subject=thread.subject,
        body=body,
    )

    # Capture before-state so the audit row can show tier transitions
    before_tier = thread.tier
    before_category = thread.category

    # Update thread
    thread.category = result.category
    thread.category_confidence = result.confidence
    thread.ai_summary = result.summary
    thread.suggested_reply_tone = result.suggested_reply_tone
    thread.categorization_source = result.source
    thread.status = EmailStatus.categorized
    thread.updated_at = datetime.now(timezone.utc)

    # Phase 3: re-decide tier on every recategorize so a manual fix doesn't
    # leave the thread stuck in a stale tier (a complaint demoted to general
    # inquiry must lose its T3 label).
    tier_decision = decide_tier(db, result=result, source=result.source)
    thread.tier = tier_decision.tier
    thread.tier_set_at = datetime.now(timezone.utc)
    thread.tier_set_by = current_user.email or "manual"

    # Check escalation
    engine = get_escalation_engine()
    escalation = engine.process(db, thread, result)

    log_action(
        db,
        action="email.manually_categorized",
        entity_type="email_thread",
        entity_id=str(thread.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "before": {
                "category": before_category.value,
                "tier": before_tier.value,
            },
            "after": {
                "category": result.category.value,
                "tier": tier_decision.tier.value,
            },
            "confidence": result.confidence,
            "escalation_created": escalation is not None,
        },
    )

    db.flush()
    db.refresh(thread)
    return EmailThreadResponse.from_thread(thread)


# ── Assignment ────────────────────────────────────────────────────────────────

@router.put("/{thread_id}/assign", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def assign_thread(
    request: Request,
    thread_id: uuid.UUID,
    body: AssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Assign a thread to a user. Pass user_id=null to unassign.
    Any authenticated staff member can claim or reassign a thread.
    """
    thread = db.execute(
        select(EmailThread)
        .options(selectinload(EmailThread.messages), selectinload(EmailThread.assigned_to))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    # If assigning to a specific user, verify that user exists and is active
    if body.user_id is not None:
        target_user = db.execute(
            select(User).where(User.id == body.user_id, User.is_active == True)  # noqa: E712
        ).scalar_one_or_none()
        if target_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found or inactive.",
            )

    previous_assignee_id = thread.assigned_to_id
    thread.assigned_to_id = body.user_id
    thread.updated_at = datetime.now(timezone.utc)

    db.flush()

    log_action(
        db,
        action="email.assigned",
        entity_type="email_thread",
        entity_id=str(thread.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "previous_assignee_id": str(previous_assignee_id) if previous_assignee_id else None,
            "new_assignee_id": str(body.user_id) if body.user_id else None,
        },
    )

    db.refresh(thread)
    return EmailThreadResponse.from_thread(thread)


# ── Save / unsave thread + folders ────────────────────────────────────────────


@router.post("/{thread_id}/save", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def save_thread(
    request: Request,
    thread_id: uuid.UUID,
    body: SaveThreadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Save a thread for later — Jane's Outlook-folder workflow, in-app.

    Pass ``folder`` to file it under a named folder (e.g. a client name);
    omit it to save without a folder. Re-saving an already-saved thread
    overwrites the folder/note (same idempotent behaviour as Outlook flag).
    """
    thread = db.execute(
        select(EmailThread)
        .options(
            selectinload(EmailThread.messages),
            selectinload(EmailThread.assigned_to),
            selectinload(EmailThread.saved_by),
        )
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    folder = body.folder.strip() if body.folder else None
    note = body.note.strip() if body.note else None

    was_saved = thread.is_saved
    thread.is_saved = True
    thread.saved_folder = folder or None
    thread.saved_note = note or None
    thread.saved_at = datetime.now(timezone.utc)
    thread.saved_by_id = current_user.id
    thread.updated_at = datetime.now(timezone.utc)

    db.flush()

    log_action(
        db,
        action="email.saved" if not was_saved else "email.save_updated",
        entity_type="email_thread",
        entity_id=str(thread.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "folder": folder,
            "has_note": note is not None,
        },
    )

    db.refresh(thread)
    return EmailThreadResponse.from_thread(thread)


@router.post("/{thread_id}/unsave", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def unsave_thread(
    request: Request,
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """Remove a thread from saved. Idempotent — succeeds even if not saved."""
    thread = db.execute(
        select(EmailThread)
        .options(
            selectinload(EmailThread.messages),
            selectinload(EmailThread.assigned_to),
            selectinload(EmailThread.saved_by),
        )
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    if thread.is_saved:
        prior_folder = thread.saved_folder
        thread.is_saved = False
        thread.saved_folder = None
        thread.saved_note = None
        thread.saved_at = None
        thread.saved_by_id = None
        thread.updated_at = datetime.now(timezone.utc)
        db.flush()

        log_action(
            db,
            action="email.unsaved",
            entity_type="email_thread",
            entity_id=str(thread.id),
            user_id=current_user.id,
            ip_address=get_client_ip(request),
            details={"prior_folder": prior_folder},
        )

    db.refresh(thread)
    return EmailThreadResponse.from_thread(thread)


@router.get("/saved/folders", response_model=list[SavedFolder])
def list_saved_folders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SavedFolder]:
    """
    List distinct saved folders + per-folder counts.

    Counts cover BOTH saved threads and saved individual messages, so the
    /saved view's folder rail accurately reflects how many items live in
    each folder regardless of granularity. Each row also breaks down
    thread_count vs message_count for UIs that need to distinguish.

    The unsorted bucket (no folder) appears as an entry with ``name=None``.
    """
    thread_rows = db.execute(
        select(
            EmailThread.saved_folder.label("folder"),
            func.count(EmailThread.id).label("count"),
        )
        .where(EmailThread.is_saved == True)  # noqa: E712
        .group_by(EmailThread.saved_folder)
    ).all()

    message_rows = db.execute(
        select(
            EmailMessage.saved_folder.label("folder"),
            func.count(EmailMessage.id).label("count"),
        )
        .where(EmailMessage.is_saved == True)  # noqa: E712
        .group_by(EmailMessage.saved_folder)
    ).all()

    # Merge by folder name, preserving the threads/messages split.
    aggregated: dict[str | None, dict[str, int]] = {}
    for row in thread_rows:
        bucket = aggregated.setdefault(row.folder, {"threads": 0, "messages": 0})
        bucket["threads"] += row.count
    for row in message_rows:
        bucket = aggregated.setdefault(row.folder, {"threads": 0, "messages": 0})
        bucket["messages"] += row.count

    # Stable sort: unfiled (None) first, then folders alphabetically.
    def _sort_key(name: str | None) -> tuple[int, str]:
        return (0, "") if name is None else (1, name.lower())

    folders = [
        SavedFolder(
            name=name,
            count=counts["threads"] + counts["messages"],
            thread_count=counts["threads"],
            message_count=counts["messages"],
        )
        for name, counts in sorted(aggregated.items(), key=lambda kv: _sort_key(kv[0]))
    ]
    return folders


@router.delete(
    "/saved/folders/{folder_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def delete_saved_folder(
    request: Request,
    folder_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """
    Delete a named saved folder.

    Folders aren't first-class entities — they're just distinct values of
    the ``saved_folder`` column on email_threads and email_messages. So
    "deleting a folder" follows the Outlook / Gmail-label model: the
    folder *label* goes away, but every item that was filed under it
    stays saved (it just becomes unfiled).

    Atomically:
      - Sets saved_folder = NULL on every saved thread that referenced
        this folder.
      - Sets saved_folder = NULL on every saved message that referenced
        this folder.
      - is_saved stays true on every affected row, so users keep their
        items in the Saved view — they just move into the "No folder"
        bucket on the rail.
      - The folder name disappears from /saved/folders the next time
        it's read, since folders are derived from distinct column values.

    Always returns 204 (idempotent — deleting a never-existed folder
    name is a no-op). Audit log captures the count of items that were
    moved out so admins can reconstruct the action later.
    """
    if not folder_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Folder name cannot be empty.",
        )

    now = datetime.now(timezone.utc)

    threads_unfiled = db.execute(
        update(EmailThread)
        .where(
            EmailThread.is_saved == True,  # noqa: E712
            EmailThread.saved_folder == folder_name,
        )
        .values(saved_folder=None, updated_at=now)
    ).rowcount or 0
    messages_unfiled = db.execute(
        update(EmailMessage)
        .where(
            EmailMessage.is_saved == True,  # noqa: E712
            EmailMessage.saved_folder == folder_name,
        )
        .values(saved_folder=None)
    ).rowcount or 0

    db.flush()

    log_action(
        db,
        action="email.folder_deleted",
        entity_type="saved_folder",
        entity_id=folder_name[:64],  # entity_id is a string column
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "folder": folder_name,
            "threads_unfiled": threads_unfiled,
            "messages_unfiled": messages_unfiled,
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Save / unsave individual message ──────────────────────────────────────────


def _get_message_or_404(
    db: Session, *, thread_id: uuid.UUID, message_id: uuid.UUID
) -> EmailMessage:
    """Fetch a message scoped to a thread or raise 404."""
    msg = db.execute(
        select(EmailMessage)
        .options(selectinload(EmailMessage.saved_by))
        .where(
            EmailMessage.id == message_id,
            EmailMessage.thread_id == thread_id,
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found in this thread.",
        )
    return msg


@router.post(
    "/{thread_id}/messages/{message_id}/save",
    response_model=EmailThreadResponse,
    dependencies=[Depends(require_csrf)],
)
def save_message(
    request: Request,
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    body: SaveThreadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Save a single message inside a thread.

    Per Jane: she usually wants to keep a single email rather than the
    whole thread. Per-message and per-thread saves are independent — a
    saved message does not save its parent thread, and unsaving a thread
    leaves any saved messages intact.

    Returns the parent thread so the client gets fresh state for the
    detail view in one round trip.
    """
    msg = _get_message_or_404(db, thread_id=thread_id, message_id=message_id)

    folder = body.folder.strip() if body.folder else None
    note = body.note.strip() if body.note else None

    was_saved = msg.is_saved
    msg.is_saved = True
    msg.saved_folder = folder or None
    msg.saved_note = note or None
    msg.saved_at = datetime.now(timezone.utc)
    msg.saved_by_id = current_user.id

    db.flush()

    log_action(
        db,
        action="email.message_saved" if not was_saved else "email.message_save_updated",
        entity_type="email_message",
        entity_id=str(msg.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "thread_id": str(thread_id),
            "folder": folder,
            "has_note": note is not None,
        },
    )

    # Return refreshed thread so the UI can re-render the bubble + dialog state.
    thread = db.execute(
        select(EmailThread)
        .options(
            selectinload(EmailThread.messages),
            selectinload(EmailThread.assigned_to),
            selectinload(EmailThread.saved_by),
        )
        .where(EmailThread.id == thread_id)
    ).scalar_one()
    return EmailThreadResponse.from_thread(thread)


@router.post(
    "/{thread_id}/messages/{message_id}/unsave",
    response_model=EmailThreadResponse,
    dependencies=[Depends(require_csrf)],
)
def unsave_message(
    request: Request,
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """Idempotent un-save for a single message."""
    msg = _get_message_or_404(db, thread_id=thread_id, message_id=message_id)

    if msg.is_saved:
        prior_folder = msg.saved_folder
        msg.is_saved = False
        msg.saved_folder = None
        msg.saved_note = None
        msg.saved_at = None
        msg.saved_by_id = None
        db.flush()

        log_action(
            db,
            action="email.message_unsaved",
            entity_type="email_message",
            entity_id=str(msg.id),
            user_id=current_user.id,
            ip_address=get_client_ip(request),
            details={
                "thread_id": str(thread_id),
                "prior_folder": prior_folder,
            },
        )

    thread = db.execute(
        select(EmailThread)
        .options(
            selectinload(EmailThread.messages),
            selectinload(EmailThread.assigned_to),
            selectinload(EmailThread.saved_by),
        )
        .where(EmailThread.id == thread_id)
    ).scalar_one()
    return EmailThreadResponse.from_thread(thread)


@router.get("/saved/messages", response_model=list[SavedMessageItem])
def list_saved_messages(
    folder: str | None = Query(default=None, description="Filter to a specific folder; empty string for unfiled"),
    sort: Literal[
        "saved_desc", "saved_asc",
        "subject_asc", "subject_desc",
        "client_asc", "client_desc",
    ] = Query(
        default="saved_desc",
        description="Sort order. Defaults to most-recently-saved first.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SavedMessageItem]:
    """
    Cross-thread list of saved individual messages with denormalised
    parent-thread context. Sort axis defaults to saved-at desc; subject
    and client sorts are case-insensitive (lower()) so human eyes don't
    see "Apex" and "apex" split across the list.
    """
    # Note: subject + client sort against the parent THREAD, not the
    # message itself — the message has no subject and the from-address
    # may differ across replies in the same thread (e.g. CC chains).
    sort_clause = {
        "saved_desc": EmailMessage.saved_at.desc().nullslast(),
        "saved_asc": EmailMessage.saved_at.asc().nullsfirst(),
        "subject_asc": func.lower(EmailThread.subject).asc(),
        "subject_desc": func.lower(EmailThread.subject).desc(),
        "client_asc": func.lower(EmailThread.client_email).asc(),
        "client_desc": func.lower(EmailThread.client_email).desc(),
    }[sort]
    query = (
        select(EmailMessage, EmailThread)
        .join(EmailThread, EmailThread.id == EmailMessage.thread_id)
        .where(EmailMessage.is_saved == True)  # noqa: E712
        .order_by(sort_clause)
    )
    if folder is not None:
        if folder == "":
            query = query.where(EmailMessage.saved_folder.is_(None))
        else:
            query = query.where(EmailMessage.saved_folder == folder)

    rows = db.execute(query).all()
    return [
        SavedMessageItem(
            id=msg.id,
            thread_id=msg.thread_id,
            sender=msg.sender,
            recipient=msg.recipient,
            body_text=msg.body_text,
            received_at=msg.received_at,
            direction=msg.direction,
            saved_folder=msg.saved_folder,
            saved_note=msg.saved_note,
            saved_at=msg.saved_at,
            thread_subject=thread.subject,
            thread_client_email=thread.client_email,
            thread_client_name=thread.client_name,
        )
        for msg, thread in rows
    ]


# ── Manual status change ──────────────────────────────────────────────────────

@router.put("/{thread_id}/status", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def change_thread_status(
    request: Request,
    thread_id: uuid.UUID,
    body: StatusChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Manually change the status of a thread.

    Allowed transitions:
    - Any active status -> closed (close thread)
    - closed -> categorized (reopen)
    - Any active status -> pending_review
    """
    thread = db.execute(
        select(EmailThread)
        .options(selectinload(EmailThread.messages), selectinload(EmailThread.assigned_to))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    allowed = _ALLOWED_TRANSITIONS.get(thread.status, set())
    if body.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot transition from '{thread.status.value}' to '{body.status.value}'. "
                f"Allowed targets: {[s.value for s in sorted(allowed, key=lambda x: x.value)]}."
            ),
        )

    previous_status = thread.status
    thread.status = body.status
    thread.updated_at = datetime.now(timezone.utc)

    db.flush()

    log_action(
        db,
        action="email.status_changed",
        entity_type="email_thread",
        entity_id=str(thread.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "previous_status": previous_status.value,
            "new_status": body.status.value,
        },
    )

    db.refresh(thread)
    return EmailThreadResponse.from_thread(thread)


# ── Trash management (delete / spam) ──────────────────────────────────────────
#
# Two terminal-status endpoints that BOTH (a) move every inbound message in
# the thread to a designated folder in Outlook via Graph and (b) park the
# local thread row in a terminal EmailStatus so the inbox view filters it
# out. Outbound (sent) messages stay in Sent Items — we never touch those.
#
# Idempotent by design: clicking trash/spam on an already-terminal thread
# returns the current state without re-issuing Graph moves. Failure mid-move
# leaves the DB untouched (transaction never commits) so retries pick up
# where the failure happened — Graph's /move is itself idempotent for
# already-moved messages, so retry is safe.
#
# Authority: Jane explicitly granted Outlook-side deletion authority in
# the 2026-05-21 meeting ("I give authority to be able to delete… we're
# good"). The UI must still show a confirm dialog per Gus's request, but
# the API does not require an extra "confirmed=true" flag — the dialog
# lives entirely client-side.


def _perform_terminal_move(
    *,
    db: Session,
    request: Request,
    thread: EmailThread,
    target_status: EmailStatus,
    destination: str,
    audit_action: str,
    provider,
    current_user: User,
) -> int:
    """
    Move a thread's inbound messages to `destination` via an already-connected
    `provider`, set thread.status = target_status, and write the audit row.
    Returns the count of messages moved.

    Shared by the single-thread trash/spam endpoints and the bulk endpoint.
    The caller owns the lookup + idempotent/cross-terminal guards and the
    provider connection; this function is purely the move + state change +
    audit. Provider errors propagate to the caller (the single endpoint lets
    them 500/bubble; the bulk loop catches them per-thread).
    """
    inbound_messages = [
        m for m in thread.messages if m.direction == MessageDirection.inbound
    ]
    moved_count = 0
    for msg in inbound_messages:
        # message_id_header is the stored internetMessageId. A message without
        # one has no resolvable Graph identifier — skip without counting.
        if not msg.message_id_header:
            continue
        provider.move_message(
            internet_message_id=msg.message_id_header,
            destination=destination,
        )
        moved_count += 1

    previous_status = thread.status
    thread.status = target_status
    thread.updated_at = datetime.now(timezone.utc)
    db.flush()

    log_action(
        db,
        action=audit_action,
        entity_type="email_thread",
        entity_id=str(thread.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "previous_status": previous_status.value,
            "destination": destination,
            "messages_moved": moved_count,
            "inbound_total": len(inbound_messages),
        },
    )
    return moved_count


def _trash_or_spam_thread(
    *,
    request: Request,
    thread_id: uuid.UUID,
    target_status: EmailStatus,
    destination: str,
    audit_action: str,
    current_user: User,
    db: Session,
) -> EmailThreadResponse:
    """
    Shared implementation for the trash + spam endpoints.

    Steps:
      1. Lookup thread; 404 if missing.
      2. Idempotent fast-path: if already in target_status, return as-is.
      3. Refuse if already in the OTHER terminal trash state (deleted vs
         spam) — they're not interchangeable and the user should have to
         un-trash before re-classifying. This is a 409 Conflict.
      4. Move every inbound message via the provider. Outbound messages
         stay put. Exceptions propagate uncaught — DB is not yet touched.
      5. Update thread.status, audit log, commit.
    """
    thread = db.execute(
        select(EmailThread)
        .options(selectinload(EmailThread.messages), selectinload(EmailThread.assigned_to))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    # Idempotent — already in target. Return current state without doing
    # anything. Lets the UI tolerate double-clicks and stale tab refreshes.
    if thread.status == target_status:
        return EmailThreadResponse.from_thread(thread)

    # Cross-terminal — refuse. Trashing a spam thread (or vice versa) is
    # almost certainly user confusion and silently doing it would lose the
    # distinction between "this was junk mail" and "I'm done with this".
    other_terminal = EmailStatus.spam if target_status == EmailStatus.deleted else EmailStatus.deleted
    if thread.status == other_terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Thread is currently in '{thread.status.value}'. Restore it "
                f"to an active status before marking it as '{target_status.value}'."
            ),
        )

    from app.services.email_provider import get_email_provider
    provider = get_email_provider()
    provider.connect()

    _perform_terminal_move(
        db=db,
        request=request,
        thread=thread,
        target_status=target_status,
        destination=destination,
        audit_action=audit_action,
        provider=provider,
        current_user=current_user,
    )

    db.refresh(thread)
    return EmailThreadResponse.from_thread(thread)


@router.post("/{thread_id}/trash", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def trash_thread(
    request: Request,
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Move all inbound messages in the thread to Outlook's Deleted Items
    folder and park the thread in EmailStatus.deleted.

    Recoverable: messages remain in Outlook's Deleted Items until Outlook
    itself purges them per its retention policy. Restore from Outlook if
    needed. The local thread row stays in our DB for audit.
    """
    return _trash_or_spam_thread(
        request=request,
        thread_id=thread_id,
        target_status=EmailStatus.deleted,
        destination="deleted_items",
        audit_action="thread.deleted",
        current_user=current_user,
        db=db,
    )


@router.post("/{thread_id}/spam", response_model=EmailThreadResponse, dependencies=[Depends(require_csrf)])
def mark_thread_spam(
    request: Request,
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """
    Move all inbound messages in the thread to Outlook's Junk Email folder
    and park the thread in EmailStatus.spam.

    Marking as junk also trains Outlook's junk filter on the sender — so
    future emails from the same source are auto-routed to junk and never
    reach this app's poller. That's the long-term value of the spam button
    beyond just trash management.
    """
    return _trash_or_spam_thread(
        request=request,
        thread_id=thread_id,
        target_status=EmailStatus.spam,
        destination="junk_email",
        audit_action="thread.marked_spam",
        current_user=current_user,
        db=db,
    )


# ── Add thread to knowledge base ──────────────────────────────────────────────
#
# From the 2026-05-21 client meeting — Jane asked to be able to put a
# substantial reply she wrote into the knowledge base so future AI drafts
# could pull from it as context. The feedback loop already learns from
# every approved/sent draft implicitly (see services/draft_feedback.py),
# but explicit KB entries are higher-signal: they're authored content
# Jane has consciously labelled "this is the kind of answer we want."


# Subject prefixes that accumulate on reply / forward chains. Stripping
# them at KB-creation time makes the resulting entries easier to skim and
# search ("Q3 audit findings" rather than "Re: Re: FW: Q3 audit findings").
_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fwd?|fw):\s*", re.IGNORECASE)


def _clean_subject_for_kb(subject: str) -> str:
    """Strip iterating Re:/Fwd:/FW: prefixes off a subject. Returns the
    original subject if cleaning would yield an empty string (e.g. a
    subject that was literally just 'Re:')."""
    cleaned = subject
    while True:
        match = _SUBJECT_PREFIX_RE.match(cleaned)
        if not match:
            break
        cleaned = cleaned[match.end():]
    cleaned = cleaned.strip()
    return cleaned or subject


def _build_kb_content_from_thread(thread: EmailThread) -> str:
    """
    Build a KB-entry body from the thread's latest Q&A exchange.

    Format:

        Question (from <sender>):
        <latest inbound body>

        Our response:
        <latest outbound body>

    This shape teaches the AI drafter what a known-good answer to this
    type of question looks like — paired with the original question for
    grounded retrieval. If the thread has no outbound message yet, we
    surface just the question so the entry is still a useful "this is
    the kind of question we see" reference.
    """
    inbound = sorted(
        [m for m in thread.messages if m.direction == MessageDirection.inbound],
        key=lambda m: m.received_at,
    )
    outbound = sorted(
        [m for m in thread.messages if m.direction == MessageDirection.outbound],
        key=lambda m: m.received_at,
    )

    parts: list[str] = []
    if inbound:
        latest_in = inbound[-1]
        sender = latest_in.sender or "client"
        body = (latest_in.body_text or latest_in.body_html or "").strip()
        if body:
            parts.append(f"Question (from {sender}):\n{body}")
    if outbound:
        latest_out = outbound[-1]
        body = (latest_out.body_text or latest_out.body_html or "").strip()
        if body:
            parts.append(f"Our response:\n{body}")

    if not parts:
        # Pathological — a thread with messages whose bodies are all
        # blank. Surface the subject as a minimal placeholder so the
        # KB row isn't an empty string (NOT NULL on content).
        return f"(Thread: {thread.subject})"
    return "\n\n".join(parts)


@router.post(
    "/{thread_id}/add-to-knowledge-base",
    response_model=KnowledgeEntryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def add_thread_to_knowledge_base(
    request: Request,
    thread_id: uuid.UUID,
    body: AddThreadToKnowledgeBaseRequest = AddThreadToKnowledgeBaseRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeEntryResponse:
    """
    Create a KnowledgeEntry from this thread's latest Q&A.

    Default title: thread subject (Re:/Fwd: stripped).
    Default category: thread.category value.
    Default tags: ['from_email', '<category>'].
    Default content: latest inbound question + latest outbound response,
    formatted as a Q&A block.

    Each field can be overridden via the request body. The endpoint
    audits as `knowledge.created_from_thread` (separate from the regular
    `knowledge.created` so admin reports can distinguish hand-authored
    KB entries from thread-derived ones).
    """
    thread = db.execute(
        select(EmailThread)
        .options(selectinload(EmailThread.messages))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    # Resolve defaults with overrides.
    title = (body.title or "").strip() or _clean_subject_for_kb(thread.subject)
    category = body.category if body.category is not None else thread.category.value
    if body.tags is not None:
        tags = body.tags
    else:
        tags = ["from_email", thread.category.value]

    content = _build_kb_content_from_thread(thread)

    entry = KnowledgeEntry(
        title=title,
        content=content,
        category=category,
        tags=tags or None,  # ARRAY(String) — empty list as NULL keeps the index lean
        entry_type="snippet",
        is_active=True,
        created_by_id=current_user.id,
    )
    db.add(entry)
    db.flush()

    log_action(
        db,
        action="knowledge.created_from_thread",
        entity_type="knowledge_entry",
        entity_id=str(entry.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "thread_id": str(thread.id),
            "thread_subject": thread.subject,
            "category": category,
            "title": title,
            "title_was_overridden": body.title is not None,
            "category_was_overridden": body.category is not None,
        },
    )

    return KnowledgeEntryResponse.model_validate(entry)


@router.get("/{thread_id}/drafts", response_model=list[DraftResponseResponse])
def list_drafts(
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DraftResponseResponse]:
    """List all draft responses for a thread."""
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    drafts = db.execute(
        select(DraftResponse)
        .where(DraftResponse.thread_id == thread_id)
        .order_by(DraftResponse.created_at.desc())
    ).scalars().all()

    return [DraftResponseResponse.model_validate(d) for d in drafts]


@router.put("/{thread_id}/drafts/{draft_id}", response_model=DraftResponseResponse, dependencies=[Depends(require_csrf)])
def update_draft(
    request: Request,
    thread_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: UpdateDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """Update a draft response (edit text and/or change status)."""
    draft = db.execute(
        select(DraftResponse).where(
            DraftResponse.id == draft_id,
            DraftResponse.thread_id == thread_id,
        )
    ).scalar_one_or_none()

    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    if draft.status in (DraftStatus.sent, DraftStatus.rejected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot modify a draft with status '{draft.status.value}'.",
        )

    if body.body_text is not None:
        draft.body_text = body.body_text
        # Auto-transition to 'edited' when body text changes and increment version
        if draft.status in (DraftStatus.pending, DraftStatus.approved):
            draft.status = DraftStatus.edited
        draft.version += 1

    db.flush()

    log_action(
        db,
        action="draft.updated",
        entity_type="draft_response",
        entity_id=str(draft.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"status": draft.status.value},
    )

    return DraftResponseResponse.model_validate(draft)


# ── Thread escalation detail ───────────────────────────────────────────────────

@router.get("/{thread_id}/escalation", response_model=EscalationResponse | None)
def get_thread_escalation(
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EscalationResponse | None:
    """
    Return an escalation worth surfacing in the thread detail banner.

    Two-tier rule:
      - Live (non-resolved) escalations always surface — that's the active
        work signal that drives the red banner.
      - **Resolved** escalations also surface IF and only if the reason
        contains the canonical PII phrase ("sensitive client data") — PII
        is a property of the email *content*, not of staff workflow, so
        the designation persists in the banner forever even after the
        escalation is closed. Resolving an IRS-audit escalation hides
        its banner; resolving a "client emailed an SSN" escalation does
        NOT, because the SSN is still in that thread.
    """
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    # Prefer live escalations. Fall back to resolved-but-PII so the banner
    # keeps the PII tag even after the work item is closed.
    live = db.execute(
        select(Escalation)
        .where(
            Escalation.thread_id == thread_id,
            Escalation.status != EscalationStatus.resolved,
        )
        .order_by(Escalation.created_at.desc())
    ).scalars().first()

    escalation = live
    if escalation is None:
        # No live escalation — see if there's a resolved PII one to surface.
        # The canonical phrase comes from app.services.pii_detector.summarize_pii;
        # case-insensitive ILIKE keeps the comparison in sync with the frontend's
        # isSensitiveData() helper.
        escalation = db.execute(
            select(Escalation)
            .where(
                Escalation.thread_id == thread_id,
                Escalation.reason.ilike("%sensitive client data%"),
            )
            .order_by(Escalation.created_at.desc())
        ).scalars().first()

    if escalation is None:
        return None

    resp = EscalationResponse.model_validate(escalation)
    resp.thread_subject = thread.subject
    resp.thread_client_email = thread.client_email
    return resp


# ── Manual draft creation (template-based) ────────────────────────────────────

@router.post("/{thread_id}/drafts", response_model=DraftResponseResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_manual_draft(
    request: Request,
    thread_id: uuid.UUID,
    body: ManualDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """
    Create a manual draft (no AI) for a thread — typically from a response template.
    The draft starts in 'edited' status so it goes through the normal approval flow.
    """
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    if thread.status in (EmailStatus.sent, EmailStatus.closed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot create a draft for a thread with status '{thread.status.value}'.",
        )

    existing = db.execute(
        select(DraftResponse).where(
            DraftResponse.thread_id == thread_id,
            DraftResponse.status.in_([DraftStatus.pending, DraftStatus.edited]),
        )
    ).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending or edited draft already exists for this thread. Reject it first.",
        )

    draft = DraftResponse(
        thread_id=thread.id,
        body_text=body.body_text,
        original_body_text=body.body_text,
        status=DraftStatus.edited,
        version=1,
    )
    db.add(draft)

    thread.status = EmailStatus.draft_ready
    thread.updated_at = datetime.now(timezone.utc)

    db.flush()

    log_action(
        db,
        action="draft.manual_created",
        entity_type="draft_response",
        entity_id=str(draft.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"thread_id": str(thread.id), "body_length": len(body.body_text)},
    )

    return DraftResponseResponse.model_validate(draft)


# ── Compose a brand-new outbound email ───────────────────────────────────────

_COMPOSE_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _parse_recipient_list(raw: str | None) -> list[str]:
    """Split a comma/semicolon-separated recipient string into validated, de-duped
    addresses (order preserved). Raises 422 on any malformed address."""
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[;,]", raw):
        addr = part.strip()
        if not addr:
            continue
        if not _COMPOSE_EMAIL_RE.match(addr):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid email address: {addr!r}",
            )
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            out.append(addr)
    return out


@router.post(
    "/compose",
    response_model=EmailThreadResponse,
    dependencies=[Depends(require_csrf)],
)
def compose_email(
    request: Request,
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    cc: str | None = Form(None),
    attachments: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadResponse:
    """Compose and SEND a brand-new outbound email (not a reply).

    multipart/form-data: ``to`` / ``subject`` / ``body`` (required), optional
    ``cc`` (comma/semicolon separated), and zero or more ``attachments`` files.

    Records the sent mail as a new thread + outbound EmailMessage so it shows in
    the app, and appends Jane's configured signature (same source the AI drafter
    uses). The real send goes through the configured provider; on failure nothing
    is persisted. Auth + CSRF required.
    """
    from app.config import get_settings as _get_settings
    from app.services import system_settings as _ss
    from app.services.email_provider import (
        MAX_TOTAL_ATTACHMENT_SIZE,
        EmailAttachment,
        get_email_provider,
    )

    to_list = _parse_recipient_list(to)
    if not to_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one valid 'to' recipient is required.",
        )
    cc_list = _parse_recipient_list(cc)

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject is required.",
        )
    body_text = (body or "").strip()
    if not body_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message body is required.",
        )

    # Read uploads into memory, enforcing the total-size cap as we go.
    email_attachments: list[EmailAttachment] = []
    total = 0
    for up in attachments or []:
        content = up.file.read()
        if not content:
            continue
        total += len(content)
        if total > MAX_TOTAL_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Attachments exceed the "
                    f"{MAX_TOTAL_ATTACHMENT_SIZE // (1024 * 1024)} MB limit."
                ),
            )
        email_attachments.append(
            EmailAttachment(
                filename=up.filename or "attachment",
                content=content,
                content_type=up.content_type or "application/octet-stream",
            )
        )

    # Append Jane's signature (same setting the AI drafter uses).
    signature = (_ss.get_setting(db, _ss.DRAFT_SIGNATURE) or "").strip()
    final_body = f"{body_text}\n\n{signature}" if signature else body_text

    app_settings = _get_settings()
    from_address = app_settings.msgraph_mailbox or app_settings.firm_owner_email
    primary_to = to_list[0]
    # send_email takes a single `to`; fold any extra To addresses into Cc so all
    # recipients still receive the message (v1 — a multi-To provider API is a
    # later enhancement).
    effective_cc = to_list[1:] + cc_list

    # Persist the thread + outbound message BEFORE sending; roll back on failure.
    thread = EmailThread(
        subject=subject,
        client_email=primary_to,
        status=EmailStatus.sent,
        category=EmailCategory.uncategorized,
    )
    db.add(thread)
    db.flush()

    domain = from_address.split("@")[-1] if "@" in from_address else "localhost"
    outbound_message_id = f"<compose-{thread.id}@{domain}>"
    outbound_msg = EmailMessage(
        thread_id=thread.id,
        message_id_header=outbound_message_id,
        sender=f"{app_settings.firm_name} <{from_address}>",
        recipient=", ".join(to_list),
        body_text=final_body,
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.outbound,
        is_processed=True,
    )
    db.add(outbound_msg)
    db.flush()

    provider = get_email_provider()
    try:
        provider.connect()
        actual_message_id = provider.send_email(
            to=primary_to,
            subject=subject,
            body_text=final_body,
            cc=effective_cc,
            attachments=email_attachments,
            message_id=outbound_message_id,
        )
        if actual_message_id and actual_message_id != outbound_message_id:
            outbound_msg.message_id_header = actual_message_id
    except ValueError as exc:
        # Provider-side size/validation failure → 413 with the reason.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        )
    except Exception as exc:
        logger.error("compose_email send failed to=%s: %s", to_list, exc, exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send the email. Please try again.",
        )

    log_action(
        db,
        action="email.composed",
        entity_type="email_thread",
        entity_id=str(thread.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "to": to_list,
            "cc": cc_list,
            "subject": subject,
            "attachment_count": len(email_attachments),
            "attachment_bytes": total,
            "message_id_header": outbound_msg.message_id_header,
        },
    )
    db.commit()
    db.refresh(thread)
    return EmailThreadResponse.model_validate(thread)


@router.post(
    "/compose/draft",
    response_model=ComposeDraftResponse,
    dependencies=[Depends(require_csrf)],
)
def compose_draft(
    request: Request,
    body: ComposeDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ComposeDraftResponse:
    """Ask the AI to draft a brand-new outbound email from a free-text
    instruction. Returns an editable subject + body — nothing is sent or
    persisted here; the user reviews, edits, then sends via /compose.

    Mirrors the reply-draft endpoint's error contract: provider/budget/parse
    problems surface as 409 with the reason; transient AI failures as 502.
    Auth + CSRF required.
    """
    from app.services.draft_generator import get_draft_generator

    generator = get_draft_generator()
    try:
        result = generator.generate_composed_email(
            db,
            instruction=body.instruction,
            recipient=body.recipient,
            subject_hint=body.subject_hint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface a clean 502, log the detail
        logger.error("compose_draft failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI service failed to draft the email. Please try again.",
        )

    return ComposeDraftResponse(subject=result.subject, body=result.body)
