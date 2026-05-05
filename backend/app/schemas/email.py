"""Pydantic schemas for EmailThread, EmailMessage, DraftResponse, KnowledgeEntry."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.email import (
    CategorizationSource,
    DraftStatus,
    EmailCategory,
    EmailStatus,
    MessageDirection,
    ThreadTier,
)


# ── Attachment metadata (embedded in EmailMessageResponse) ────────────────────

class AttachmentInfo(BaseModel):
    filename: str
    size: int | None = None        # size in bytes; None if provider didn't report it
    content_type: str | None = None


# ── Categorization result (from AI) ───────────────────────────────────────────

class CategorizationResult(BaseModel):
    """Structured output returned by the categorizer service."""
    category: EmailCategory
    confidence: float = Field(ge=0.0, le=1.0)
    escalation_needed: bool
    escalation_reasons: list[str] = Field(default_factory=list)
    summary: str
    suggested_reply_tone: str = "professional"  # e.g. "professional", "empathetic", "urgent"
    # Phase 3: tracks which engine produced this result. Defaults to claude
    # so all existing call sites continue to work.
    source: CategorizationSource = CategorizationSource.claude


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
    attachments: list[AttachmentInfo] | None = None
    # Per-message save state — mirrors EmailThread save fields.
    # saved_by_name is omitted here (cf. EmailThreadResponse) because
    # messages are usually serialised in bulk via from_attributes and
    # eagerly resolving the FK adds noise. The user id is enough for
    # auditing; the UI doesn't render a name on the bubble itself.
    is_saved: bool = False
    saved_folder: str | None = None
    saved_note: str | None = None
    saved_at: datetime | None = None
    saved_by_id: uuid.UUID | None = None


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
    assigned_to_id: uuid.UUID | None = None
    assigned_to_name: str | None = None
    # T2.5: Draft generation failure tracking
    draft_generation_failed: bool = False
    draft_generation_failed_at: datetime | None = None
    # Phase 3: Tier-based triage
    tier: ThreadTier = ThreadTier.t2_review
    tier_set_at: datetime | None = None
    tier_set_by: str | None = None
    categorization_source: CategorizationSource = CategorizationSource.claude
    auto_sent_at: datetime | None = None
    # Save-to-folder state
    is_saved: bool = False
    saved_folder: str | None = None
    saved_note: str | None = None
    saved_at: datetime | None = None
    saved_by_id: uuid.UUID | None = None
    saved_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[EmailMessageResponse] = Field(default_factory=list)

    @classmethod
    def from_thread(cls, thread: Any) -> "EmailThreadResponse":
        """Build from an EmailThread ORM object, resolving assigned_to_name."""
        data = {
            "id": thread.id,
            "subject": thread.subject,
            "client_email": thread.client_email,
            "client_name": thread.client_name,
            "status": thread.status,
            "category": thread.category,
            "category_confidence": thread.category_confidence,
            "ai_summary": thread.ai_summary,
            "suggested_reply_tone": thread.suggested_reply_tone,
            "assigned_to_id": thread.assigned_to_id,
            "assigned_to_name": thread.assigned_to.name if thread.assigned_to else None,
            "draft_generation_failed": getattr(thread, "draft_generation_failed", False),
            "draft_generation_failed_at": getattr(thread, "draft_generation_failed_at", None),
            "tier": thread.tier,
            "tier_set_at": thread.tier_set_at,
            "tier_set_by": thread.tier_set_by,
            "categorization_source": thread.categorization_source,
            "auto_sent_at": thread.auto_sent_at,
            "is_saved": getattr(thread, "is_saved", False),
            "saved_folder": getattr(thread, "saved_folder", None),
            "saved_note": getattr(thread, "saved_note", None),
            "saved_at": getattr(thread, "saved_at", None),
            "saved_by_id": getattr(thread, "saved_by_id", None),
            "saved_by_name": (
                thread.saved_by.name
                if getattr(thread, "saved_by", None) is not None
                else None
            ),
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
            "messages": thread.messages,
        }
        return cls.model_validate(data)


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
    assigned_to_id: uuid.UUID | None = None
    assigned_to_name: str | None = None
    # T2.5: Draft generation failure tracking
    draft_generation_failed: bool = False
    # Phase 3: Tier-based triage
    tier: ThreadTier = ThreadTier.t2_review
    categorization_source: CategorizationSource = CategorizationSource.claude
    auto_sent_at: datetime | None = None
    is_saved: bool = False
    saved_folder: str | None = None
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
    # T1.12: Idempotent send tracking
    send_attempts: int = 0
    send_idempotency_key: str | None = None


class UpdateDraftRequest(BaseModel):
    """Edit draft text. Use dedicated approve/reject/send endpoints for status transitions."""
    body_text: str | None = None


class GenerateDraftRequest(BaseModel):
    """
    Optional request body for POST /emails/{thread_id}/generate-draft.
    tone: optional override for the AI draft tone (e.g. 'professional', 'empathetic').
    """
    tone: str | None = None


class ManualDraftRequest(BaseModel):
    """Request body for POST /emails/{thread_id}/drafts (manual/template-based draft)."""
    body_text: str = Field(min_length=1, max_length=50_000)


class RejectDraftRequest(BaseModel):
    """Request body for POST .../reject. Rejection reason is required for audit purposes."""
    rejection_reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Why this draft was rejected. Used to improve future prompts.",
    )


class SendDraftRequest(BaseModel):
    """
    Optional request body for POST .../send.

    idempotency_key: client-supplied key (e.g. UUID or nonce) used to deduplicate
    retries. If omitted the server generates one. On retry with the same key the
    server returns the previously recorded result without calling the email provider.
    """
    idempotency_key: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_\-]{1,128}$",
        description=(
            "Client-supplied idempotency key for safe retries. "
            "Must contain only alphanumeric characters, hyphens, or underscores "
            "(1–128 chars). Null bytes, unicode, and special characters are rejected."
        ),
    )


# ── Assignment / Status change request schemas ────────────────────────────────

class AssignRequest(BaseModel):
    """Body for PUT /emails/{thread_id}/assign. Pass user_id=null to unassign."""
    user_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the user to assign, or null to unassign.",
    )


class StatusChangeRequest(BaseModel):
    """Body for PUT /emails/{thread_id}/status."""
    status: EmailStatus


class SaveThreadRequest(BaseModel):
    """Body for POST /emails/{thread_id}/save and POST /messages/{id}/save."""
    folder: str | None = Field(
        default=None,
        max_length=128,
        description="Folder name to save under (e.g. a client name). Omit to save unfiled.",
    )
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional note explaining why this was saved.",
    )


class SavedFolder(BaseModel):
    """Entry returned by GET /emails/saved/folders."""
    name: str | None = Field(
        default=None,
        description="Folder name. Null indicates the unsorted/unfiled saved bucket.",
    )
    count: int
    # Per-folder breakdown so the frontend can show e.g. "Smith folder
    # holds 2 threads + 3 individual emails" without two separate calls.
    thread_count: int = 0
    message_count: int = 0


class SavedMessageItem(BaseModel):
    """
    Flat representation of a saved individual message + its thread context.

    Returned by GET /emails/saved/messages so the /saved view can render
    each saved bubble inline with the parent subject + client info,
    without forcing the client to fan out to /threads/{id} per message.
    """
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    sender: str
    recipient: str | None
    body_text: str | None
    received_at: datetime
    direction: MessageDirection
    saved_folder: str | None = None
    saved_note: str | None = None
    saved_at: datetime | None = None
    # Thread context (denormalised so the list renders without joins client-side)
    thread_subject: str
    thread_client_email: str
    thread_client_name: str | None = None


# ── Bulk action request schema ────────────────────────────────────────────────

class BulkActionParams(BaseModel):
    """Optional parameters for bulk actions (e.g. user_id for assign)."""
    user_id: uuid.UUID | None = None


class BulkActionRequest(BaseModel):
    """Body for POST /emails/bulk."""
    thread_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: str = Field(
        description="One of: close, assign, recategorize",
        pattern="^(close|assign|recategorize)$",
    )
    params: BulkActionParams = Field(default_factory=BulkActionParams)


class BulkActionResponse(BaseModel):
    succeeded: int
    failed: int
    errors: list[str] = Field(default_factory=list)

