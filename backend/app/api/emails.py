"""
Email routes.

GET  /emails                       — list threads with filters and pagination
GET  /emails/{thread_id}           — get a single thread with its messages
POST /emails/{thread_id}/categorize — manually re-trigger categorization
GET  /emails/{thread_id}/drafts    — list draft responses for a thread
PUT  /emails/{thread_id}/drafts/{draft_id} — update a draft (review/edit)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_client_ip, get_current_user
from app.database import get_db
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
)
from app.models.user import User
from app.schemas.email import (
    DraftResponseResponse,
    EmailThreadListItem,
    EmailThreadListResponse,
    EmailThreadResponse,
    UpdateDraftRequest,
)
from app.services.categorizer import get_categorizer
from app.services.escalation import get_escalation_engine
from app.utils.audit import log_action

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=EmailThreadListResponse)
def list_threads(
    status: EmailStatus | None = Query(default=None),
    category: EmailCategory | None = Query(default=None),
    client_email: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailThreadListResponse:
    """List email threads with optional filters. Supports pagination."""
    query = select(EmailThread)

    if status is not None:
        query = query.where(EmailThread.status == status)
    if category is not None:
        query = query.where(EmailThread.category == category)
    if client_email:
        # Escape LIKE wildcards to prevent unintended pattern matching
        safe_email = client_email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            EmailThread.client_email.ilike(f"%{safe_email}%", escape="\\")
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
        .options(selectinload(EmailThread.messages))
        .where(EmailThread.id == thread_id)
    ).scalar_one_or_none()

    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")

    return EmailThreadResponse.model_validate(thread)


@router.post("/{thread_id}/categorize", response_model=EmailThreadResponse)
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
    result = categorizer.categorize(
        sender=latest.sender,
        subject=thread.subject,
        body=body,
    )

    # Update thread
    from datetime import timezone
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
    return EmailThreadResponse.model_validate(thread)


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


@router.put("/{thread_id}/drafts/{draft_id}", response_model=DraftResponseResponse)
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

    from datetime import timezone
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
