"""Pydantic schemas for Escalation."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.escalation import EscalationSeverity, EscalationStatus


class EscalationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    reason: str
    severity: EscalationSeverity
    status: EscalationStatus
    assigned_to_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None
    resolution_notes: str | None


class EscalationListResponse(BaseModel):
    items: list[EscalationResponse]
    total: int
    page: int
    page_size: int


class AcknowledgeEscalationRequest(BaseModel):
    notes: str | None = None


class ResolveEscalationRequest(BaseModel):
    resolution_notes: str = Field(min_length=1)
