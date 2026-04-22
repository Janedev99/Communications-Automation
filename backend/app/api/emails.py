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
import threading
import uuid
from collections import defaultdict
from datetime import datetime, date, timezone
from typing import AsyncGenerator, DefaultDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_client_ip, get_current_user, require_csrf
from app.database import get_db
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
)
from app.models.escalation import Escalation, EscalationStatus
from app.models.user import User
from app.schemas.email import (
    AssignRequest,
    BulkActionRequest,
    BulkActionResponse,
    DraftResponseResponse,
    EmailThreadListItem,
    EmailThreadListResponse,
    EmailThreadResponse,
    ManualDraftRequest,
    StatusChangeRequest,
    UpdateDraftRequest,
)
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
                thread.category = result.category
                thread.category_confidence = result.confidence
                thread.ai_summary = result.summary
                thread.suggested_reply_tone = result.suggested_reply_tone
                thread.status = EmailStatus.categorized
                thread.updated_at = datetime.now(timezone.utc)
                log_action(
                    db,
                    action="email.bulk_recategorized",
                    entity_type="email_thread",
                    entity_id=str(thread.id),
                    user_id=current_user.id,
                    ip_address=get_client_ip(request),
                    details={"category": result.category.value, "confidence": result.confidence},
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
            from_dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            query = query.where(EmailThread.created_at >= from_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid 'from' date. Use ISO 8601 format.",
            )

    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
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
    client_email: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None, description="'me' or a user UUID"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadListResponse:
    """List email threads with optional filters. Supports pagination."""
    query = select(EmailThread)

    if thread_status is not None:
        query = query.where(EmailThread.status == thread_status)
    if category is not None:
        query = query.where(EmailThread.category == category)
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

    paged_query = (
        select(EmailThread, func.coalesce(msg_count_subq.c.message_count, 0).label("message_count"))
        .outerjoin(msg_count_subq, EmailThread.id == msg_count_subq.c.thread_id)
        .options(selectinload(EmailThread.assigned_to))
        .where(query.whereclause if query.whereclause is not None else True)
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

    # Update thread
    thread.category = result.category
    thread.category_confidence = result.confidence
    thread.ai_summary = result.summary
    thread.suggested_reply_tone = result.suggested_reply_tone
    thread.status = EmailStatus.categorized
    thread.updated_at = datetime.now(timezone.utc)

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
            "category": result.category.value,
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
    Return the latest active (non-resolved) escalation for a thread, or null.
    Used to show an escalation banner in the thread detail view.
    """
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    escalation = db.execute(
        select(Escalation)
        .where(
            Escalation.thread_id == thread_id,
            Escalation.status != EscalationStatus.resolved,
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
