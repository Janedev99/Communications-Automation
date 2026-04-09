"""
Escalation routes.

GET /escalations                          — list escalations with filters
GET /escalations/{id}                     — get a single escalation
PUT /escalations/{id}/acknowledge         — Jane/admin marks as seen
PUT /escalations/{id}/resolve             — Jane/admin marks as resolved
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user
from app.database import get_db
from app.models.email import EmailThread
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.models.user import User
from app.schemas.escalation import (
    AcknowledgeEscalationRequest,
    EscalationListResponse,
    EscalationResponse,
    ResolveEscalationRequest,
)
from app.utils.audit import log_action

router = APIRouter(prefix="/escalations", tags=["escalations"])


def _build_response(escalation: Escalation, db: Session) -> EscalationResponse:
    """Build an EscalationResponse, enriching it with thread subject and client email."""
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == escalation.thread_id)
    ).scalar_one_or_none()
    resp = EscalationResponse.model_validate(escalation)
    if thread is not None:
        resp.thread_subject = thread.subject
        resp.thread_client_email = thread.client_email
    return resp


@router.get("", response_model=EscalationListResponse)
def list_escalations(
    status_filter: EscalationStatus | None = Query(default=None, alias="status"),
    severity: EscalationSeverity | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EscalationListResponse:
    """List escalations with optional filtering."""
    query = select(Escalation)

    if status_filter is not None:
        query = query.where(Escalation.status == status_filter)
    if severity is not None:
        query = query.where(Escalation.severity == severity)
    if assigned_to_me:
        query = query.where(Escalation.assigned_to_id == current_user.id)

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    offset = (page - 1) * page_size
    rows = db.execute(
        query.order_by(Escalation.created_at.desc()).offset(offset).limit(page_size)
    ).scalars().all()

    return EscalationListResponse(
        items=[_build_response(e, db) for e in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{escalation_id}", response_model=EscalationResponse)
def get_escalation(
    escalation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EscalationResponse:
    escalation = db.execute(
        select(Escalation).where(Escalation.id == escalation_id)
    ).scalar_one_or_none()

    if escalation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found.")

    return _build_response(escalation, db)


@router.put("/{escalation_id}/acknowledge", response_model=EscalationResponse)
def acknowledge_escalation(
    request: Request,
    escalation_id: uuid.UUID,
    body: AcknowledgeEscalationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EscalationResponse:
    """Mark an escalation as acknowledged (seen by Jane or a staff member)."""
    escalation = db.execute(
        select(Escalation).where(Escalation.id == escalation_id)
    ).scalar_one_or_none()

    if escalation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found.")

    if escalation.status == EscalationStatus.resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escalation is already resolved.",
        )

    escalation.status = EscalationStatus.acknowledged
    escalation.assigned_to_id = current_user.id
    if body.notes:
        # Append acknowledgement note to reason
        escalation.reason = escalation.reason + f"\n\nAcknowledgement note: {body.notes}"

    db.flush()

    log_action(
        db,
        action="escalation.acknowledged",
        entity_type="escalation",
        entity_id=str(escalation.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
    )

    return _build_response(escalation, db)


@router.put("/{escalation_id}/resolve", response_model=EscalationResponse)
def resolve_escalation(
    request: Request,
    escalation_id: uuid.UUID,
    body: ResolveEscalationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EscalationResponse:
    """Mark an escalation as resolved with resolution notes."""
    escalation = db.execute(
        select(Escalation).where(Escalation.id == escalation_id)
    ).scalar_one_or_none()

    if escalation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found.")

    if escalation.status == EscalationStatus.resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escalation is already resolved.",
        )

    now = datetime.now(timezone.utc)
    escalation.status = EscalationStatus.resolved
    escalation.resolved_at = now
    escalation.resolved_by_id = current_user.id
    escalation.resolution_notes = body.resolution_notes

    # Update the linked thread's status back to categorized (no longer escalated)
    from app.models.email import EmailStatus
    thread = db.execute(
        select(EmailThread).where(EmailThread.id == escalation.thread_id)
    ).scalar_one_or_none()
    if thread and thread.status == EmailStatus.escalated:
        thread.status = EmailStatus.categorized
        thread.updated_at = now

    db.flush()

    log_action(
        db,
        action="escalation.resolved",
        entity_type="escalation",
        entity_id=str(escalation.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"resolution_notes": body.resolution_notes},
    )

    return _build_response(escalation, db)
