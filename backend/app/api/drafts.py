"""
Draft workflow routes.

POST   /emails/{thread_id}/generate-draft         — trigger AI draft generation
GET    /drafts                                     — list all drafts (cross-thread)
GET    /emails/{thread_id}/drafts/{draft_id}       — get single draft with full detail
POST   /emails/{thread_id}/drafts/{draft_id}/approve — approve a pending/edited draft
POST   /emails/{thread_id}/drafts/{draft_id}/reject  — reject a draft (requires reason)
POST   /emails/{thread_id}/drafts/{draft_id}/send    — send an approved draft via email

Note: list drafts per thread (GET /emails/{thread_id}/drafts) and edit draft text
(PUT /emails/{thread_id}/drafts/{draft_id}) are on the emails router for
backward compatibility.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_client_ip, get_current_user
from app.database import get_db
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)
from app.models.user import User
from app.schemas.email import (
    DraftResponseResponse,
    GenerateDraftRequest,
    RejectDraftRequest,
)
from app.services.draft_generator import get_draft_generator
from app.services.email_provider import get_email_provider
from app.utils.audit import log_action
from app.utils.rate_limit import check_ai_rate_limit, record_ai_call

logger = logging.getLogger(__name__)

router = APIRouter(tags=["drafts"])


def _get_thread_or_404(thread_id: uuid.UUID, db: Session) -> EmailThread:
    """Helper: fetch a thread or raise 404."""
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found.",
        )
    return thread


def _get_draft_or_404(draft_id: uuid.UUID, thread_id: uuid.UUID, db: Session) -> DraftResponse:
    """Helper: fetch a draft belonging to a thread or raise 404."""
    draft = db.execute(
        select(DraftResponse).where(
            DraftResponse.id == draft_id,
            DraftResponse.thread_id == thread_id,
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found.",
        )
    return draft


# ── List all drafts (cross-thread) ───────────────────────────────────────────

@router.get("/drafts", response_model=list[DraftResponseResponse])
def list_all_drafts(
    draft_status: DraftStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DraftResponseResponse]:
    """
    List all drafts across all threads. Filter by status (e.g. ?status=pending
    to see all drafts needing review).
    """
    query = select(DraftResponse)
    if draft_status is not None:
        query = query.where(DraftResponse.status == draft_status)

    offset = (page - 1) * page_size
    drafts = db.execute(
        query.order_by(DraftResponse.created_at.desc()).offset(offset).limit(page_size)
    ).scalars().all()

    return [DraftResponseResponse.model_validate(d) for d in drafts]


# ── Generate draft ────────────────────────────────────────────────────────────

@router.post(
    "/emails/{thread_id}/generate-draft",
    response_model=DraftResponseResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_draft(
    request: Request,
    thread_id: uuid.UUID,
    _body: GenerateDraftRequest = GenerateDraftRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """
    Manually trigger AI draft generation for a thread.

    Use this when:
      - draft_auto_generate is False
      - A previously generated draft was rejected and staff wants a fresh one
      - The thread was escalated but Jane has reviewed it and wants a draft

    Will generate a draft regardless of thread status, unless the thread
    has already been fully sent (status=sent or status=closed).
    """
    # Enforce per-user AI call rate limit before any DB work
    check_ai_rate_limit(current_user.id)

    thread = _get_thread_or_404(thread_id, db)

    if thread.status in (EmailStatus.sent, EmailStatus.closed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot generate a draft for a thread with status '{thread.status.value}'.",
        )

    # Guard against concurrent draft generation — check for existing pending/edited drafts
    existing_draft = db.execute(
        select(DraftResponse).where(
            DraftResponse.thread_id == thread_id,
            DraftResponse.status.in_([DraftStatus.pending, DraftStatus.edited]),
        )
    ).scalars().first()
    if existing_draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending or edited draft already exists for this thread. "
                   "Reject it first before generating a new one.",
        )

    # If escalated, skip the generator's guard — manual trigger means staff/Jane
    # has made a conscious decision to draft despite escalation.
    is_escalated = thread.status == EmailStatus.escalated

    try:
        generator = get_draft_generator()
        # Record the AI call now — before generate() so even a partial attempt counts
        record_ai_call(current_user.id)
        draft = generator.generate(
            db,
            thread,
            skip_escalation_guard=is_escalated,
            tone_override=_body.tone or None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except anthropic.APIError as exc:
        logger.error(
            "Draft generation API error for thread=%s: %s", thread_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service error during draft generation. Please try again.",
        )
    except Exception as exc:
        logger.error(
            "Draft generation failed for thread=%s: %s", thread_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Draft generation failed. Please try again or contact support.",
        )

    log_action(
        db,
        action="draft.manually_triggered",
        entity_type="draft_response",
        entity_id=str(draft.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "thread_id": str(thread.id),
            "was_escalated": is_escalated,
        },
    )

    return DraftResponseResponse.model_validate(draft)


# ── Get single draft ──────────────────────────────────────────────────────────

@router.get("/emails/{thread_id}/drafts/{draft_id}", response_model=DraftResponseResponse)
def get_draft(
    thread_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """Get a single draft response with full detail including AI metadata."""
    _get_thread_or_404(thread_id, db)
    draft = _get_draft_or_404(draft_id, thread_id, db)
    return DraftResponseResponse.model_validate(draft)


# ── Approve ───────────────────────────────────────────────────────────────────

@router.post("/emails/{thread_id}/drafts/{draft_id}/approve", response_model=DraftResponseResponse)
def approve_draft(
    request: Request,
    thread_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """
    Approve a draft, marking it ready to send.

    Only drafts with status 'pending' or 'edited' can be approved.
    After approval the draft is in status 'approved' and can be sent
    via the /send endpoint.
    """
    _get_thread_or_404(thread_id, db)
    draft = _get_draft_or_404(draft_id, thread_id, db)

    if draft.status not in (DraftStatus.pending, DraftStatus.edited):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot approve a draft with status '{draft.status.value}'. "
                "Only pending or edited drafts can be approved."
            ),
        )

    draft.status = DraftStatus.approved
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(timezone.utc)
    db.flush()

    log_action(
        db,
        action="draft.approved",
        entity_type="draft_response",
        entity_id=str(draft.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"thread_id": str(thread_id), "version": draft.version},
    )

    return DraftResponseResponse.model_validate(draft)


# ── Reject ────────────────────────────────────────────────────────────────────

@router.post("/emails/{thread_id}/drafts/{draft_id}/reject", response_model=DraftResponseResponse)
def reject_draft(
    request: Request,
    thread_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: RejectDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """
    Reject a draft and record the reason.

    Rejection reason is required — it helps improve future AI prompts.
    After rejection the thread status reverts to 'categorized' so staff
    can request a new draft via /generate-draft.

    Sent or already-approved drafts cannot be rejected.
    """
    thread = _get_thread_or_404(thread_id, db)
    draft = _get_draft_or_404(draft_id, thread_id, db)

    if draft.status in (DraftStatus.sent, DraftStatus.rejected, DraftStatus.approved):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reject a draft with status '{draft.status.value}'.",
        )

    draft.status = DraftStatus.rejected
    draft.rejection_reason = body.rejection_reason
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(timezone.utc)

    # Revert thread status so staff can request a new draft
    if thread.status in (EmailStatus.draft_ready, EmailStatus.pending_review):
        thread.status = EmailStatus.categorized
        thread.updated_at = datetime.now(timezone.utc)

    db.flush()

    log_action(
        db,
        action="draft.rejected",
        entity_type="draft_response",
        entity_id=str(draft.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "thread_id": str(thread_id),
            "rejection_reason": body.rejection_reason,
            "version": draft.version,
        },
    )

    return DraftResponseResponse.model_validate(draft)


# ── Send ──────────────────────────────────────────────────────────────────────

@router.post("/emails/{thread_id}/drafts/{draft_id}/send", response_model=DraftResponseResponse)
def send_draft(
    request: Request,
    thread_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftResponseResponse:
    """
    Send an approved draft to the client via the configured email provider.

    Only drafts with status 'approved' can be sent.

    Double-send protection (T1.11 + T1.12):
      - SELECT FOR UPDATE on the draft prevents concurrent send races.
      - An idempotency key is generated on first attempt and committed BEFORE
        calling the provider. A second call with the same key (retry) returns
        the persisted result without re-calling the provider.

    Persist-first strategy: DB state is written before the email is sent.
    If the email provider fails, draft.status becomes 'send_failed' and the
    idempotency key is retained so retries are safe.
    """
    thread = _get_thread_or_404(thread_id, db)

    # T1.11: SELECT FOR UPDATE — lock the draft row to prevent concurrent sends
    draft = db.execute(
        select(DraftResponse)
        .where(
            DraftResponse.id == draft_id,
            DraftResponse.thread_id == thread_id,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found.",
        )

    # T1.12: If already sent (idempotency — same key retry or concurrent request)
    if draft.status == DraftStatus.sent:
        return DraftResponseResponse.model_validate(draft)

    if draft.status != DraftStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot send a draft with status '{draft.status.value}'. "
                "Only approved drafts can be sent."
            ),
        )

    # T1.12: Generate idempotency key if not already set
    if not draft.send_idempotency_key:
        draft.send_idempotency_key = secrets.token_hex(32)

    # Increment attempt counter and commit BEFORE calling provider
    draft.send_attempts = (draft.send_attempts or 0) + 1
    db.flush()

    # Find the most recent inbound message to reply to
    inbound_messages = db.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.inbound,
        ).order_by(EmailMessage.received_at.desc())
    ).scalars().all()

    # T2.1: Build full References chain for proper email threading
    reply_to_message_id: str | None = None
    references_header: str | None = None
    if inbound_messages:
        latest_inbound = inbound_messages[0]
        reply_to_message_id = latest_inbound.message_id_header
        # Build References = parent's References + " " + parent's Message-ID
        parent_references = (latest_inbound.raw_headers or {}).get("References", "")
        parent_msg_id = latest_inbound.message_id_header
        if parent_references:
            references_header = f"{parent_references} {parent_msg_id}"
        else:
            references_header = parent_msg_id

    # Build subject — reply convention
    reply_subject = thread.subject
    if reply_subject and not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"
    if not reply_subject or reply_subject.strip().lower() == "re:":
        reply_subject = "Re: (no subject)"

    # Generate a Message-ID we control for thread continuity
    settings = _get_settings()
    # Use the monitored mailbox as the from address so client replies return to the inbox
    from_address = settings.msgraph_mailbox or settings.firm_owner_email
    firm_domain = from_address.split("@")[-1] if "@" in from_address else "localhost"
    outbound_message_id = f"<draft-{draft.id}@{firm_domain}>"

    # Persist outbound message + status changes BEFORE sending
    outbound_msg = EmailMessage(
        thread_id=thread.id,
        message_id_header=outbound_message_id,
        sender=f"{settings.firm_name} <{from_address}>",
        recipient=thread.client_email,
        body_text=draft.body_text,
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.outbound,
        is_processed=True,
    )
    db.add(outbound_msg)

    draft.status = DraftStatus.sent
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(timezone.utc)

    thread.status = EmailStatus.sent
    thread.updated_at = datetime.now(timezone.utc)

    db.flush()  # Write to DB (not yet committed)

    # Send email via provider — if this fails, mark send_failed and rollback
    provider = get_email_provider()
    try:
        provider.connect()
        actual_message_id = provider.send_email(
            to=thread.client_email,
            subject=reply_subject,
            body_text=draft.body_text,
            reply_to_message_id=reply_to_message_id,
            references_header=references_header,
            message_id=outbound_message_id,
        )
        # Update with actual message_id if provider returned a different one
        if actual_message_id and actual_message_id != outbound_message_id:
            outbound_msg.message_id_header = actual_message_id
    except Exception as exc:
        logger.error(
            "Failed to send email for draft=%s thread=%s: %s",
            draft.id, thread.id, exc, exc_info=True,
        )
        # This raise triggers rollback — DB state reverts to pre-flush.
        # The idempotency key is also rolled back, which is fine — on retry a new
        # key will be generated and another attempt will be made.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to deliver the email. Please try again or contact support.",
        )

    # Audit log — on success, transaction commits when endpoint returns
    log_action(
        db,
        action="draft.sent",
        entity_type="draft_response",
        entity_id=str(draft.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "thread_id": str(thread_id),
            "client_email": thread.client_email,
            "reply_subject": reply_subject,
            "outbound_message_id": str(outbound_msg.id),
            "message_id_header": outbound_msg.message_id_header,
            "send_attempts": draft.send_attempts,
            "idempotency_key": draft.send_idempotency_key,
        },
    )

    return DraftResponseResponse.model_validate(draft)


def _get_settings():
    """Lazy settings access to avoid module-level import during startup."""
    from app.config import get_settings
    return get_settings()
