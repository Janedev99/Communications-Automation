"""Pydantic schemas for EmailThread, EmailMessage, DraftResponse, KnowledgeEntry."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.email import (
    DraftStatus,
    EmailCategory,
    EmailStatus,
    MessageDirection,
)


# ── Categorization result (from AI) ───────────────────────────────────────────

class CategorizationResult(BaseModel):
    """Structured output returned by the categorizer service."""
    category: EmailCategory
    confidence: float = Field(ge=0.0, le=1.0)
    escalation_needed: bool
    escalation_reasons: list[str] = Field(default_factory=list)
    summary: str
    suggested_reply_tone: str = "professional"  # e.g. "professional", "empathetic", "urgent"


# ── EmailMessage schemas ───────────────────────────────────────────────────────

class EmailMessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    message_id_header: str
    sender: str
    recipient: str | None
    body_text: str | None
    received_at: datetime
    direction: MessageDirection
    is_processed: bool


# ── EmailThread schemas ────────────────────────────────────────────────────────

class EmailThreadResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    subject: str
    client_email: str
    client_name: str | None
    status: EmailStatus
    category: EmailCategory
    category_confidence: float | None
    ai_summary: str | None
    suggested_reply_tone: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[EmailMessageResponse] = Field(default_factory=list)


class EmailThreadListItem(BaseModel):
    """Lightweight thread representation for list endpoints."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    subject: str
    client_email: str
    client_name: str | None
    status: EmailStatus
    category: EmailCategory
    category_confidence: float | None
    ai_summary: str | None
    suggested_reply_tone: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class EmailThreadListResponse(BaseModel):
    items: list[EmailThreadListItem]
    total: int
    page: int
    page_size: int


# ── DraftResponse schemas ──────────────────────────────────────────────────────

class DraftResponseResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    body_text: str
    status: DraftStatus
    reviewed_by_id: uuid.UUID | None
    created_at: datetime
    reviewed_at: datetime | None
    # Phase 2: revision tracking and AI metadata
    version: int = 1
    original_body_text: str | None = None
    ai_model: str | None = None
    ai_prompt_tokens: int | None = None
    ai_completion_tokens: int | None = None
    knowledge_entry_ids: list[Any] | None = None
    rejection_reason: str | None = None


class UpdateDraftRequest(BaseModel):
    """Edit draft text. Use dedicated approve/reject/send endpoints for status transitions."""
    body_text: str | None = None


class GenerateDraftRequest(BaseModel):
    """
    Optional request body for POST /emails/{thread_id}/generate-draft.
    Currently has no required fields — thread_id is sufficient context.
    Reserved for future per-request overrides (e.g. custom tone).
    """
    pass


class RejectDraftRequest(BaseModel):
    """Request body for POST .../reject. Rejection reason is required for audit purposes."""
    rejection_reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Why this draft was rejected. Used to improve future prompts.",
    )

