"""
Email-related models:
  - EmailThread    — a conversation (groups messages by subject/references)
  - EmailMessage   — an individual email message within a thread
  - DraftResponse  — a pending AI-generated reply awaiting staff approval
  - KnowledgeEntry — knowledge base entries used to improve AI responses
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EmailStatus(str, enum.Enum):
    new = "new"                     # Just arrived, not yet processed
    categorized = "categorized"     # AI has categorized it
    draft_ready = "draft_ready"     # Draft response prepared
    pending_review = "pending_review"  # Staff reviewing draft
    sent = "sent"                   # Response sent
    escalated = "escalated"         # Sent to Jane for review
    closed = "closed"               # Thread resolved


class EmailCategory(str, enum.Enum):
    status_update = "status_update"
    document_request = "document_request"
    appointment = "appointment"
    clarification = "clarification"
    general_inquiry = "general_inquiry"
    complaint = "complaint"
    urgent = "urgent"
    uncategorized = "uncategorized"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class DraftStatus(str, enum.Enum):
    pending = "pending"       # Awaiting staff review
    edited = "edited"         # Staff has modified the AI draft, ready for final approval
    approved = "approved"     # Staff approved, ready to send
    rejected = "rejected"     # Staff rejected, needs revision
    sent = "sent"             # Successfully sent
    send_failed = "send_failed"  # Provider call failed; idempotency key retained for retry


class EmailThread(Base):
    __tablename__ = "email_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject: Mapped[str] = mapped_column(String(998), nullable=False)  # RFC 5322 max
    client_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, name="email_status"),
        nullable=False,
        default=EmailStatus.new,
        index=True,
    )
    category: Mapped[EmailCategory] = mapped_column(
        Enum(EmailCategory, name="email_category"),
        nullable=False,
        default=EmailCategory.uncategorized,
        index=True,
    )
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_reply_tone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default="professional"
    )
    # The external thread ID from the mail provider (e.g., MS Graph conversationId)
    provider_thread_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    # Staff assignment: which user currently owns this thread
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # T2.5: Draft generation failure tracking
    draft_generation_failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    draft_generation_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    messages: Mapped[list["EmailMessage"]] = relationship(
        "EmailMessage", back_populates="thread", cascade="all, delete-orphan",
        order_by="EmailMessage.received_at"
    )
    escalations: Mapped[list["Escalation"]] = relationship(  # type: ignore[name-defined]
        "Escalation", back_populates="thread", cascade="all, delete-orphan"
    )
    drafts: Mapped[list["DraftResponse"]] = relationship(
        "DraftResponse", back_populates="thread", cascade="all, delete-orphan"
    )
    assigned_to: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[assigned_to_id]
    )

    def __repr__(self) -> str:
        return f"<EmailThread id={self.id} subject={self.subject!r} status={self.status}>"


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        # Prevent storing the same raw email twice
        UniqueConstraint("message_id_header", name="uq_message_id_header"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("email_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The Message-ID header value — globally unique per RFC 5322
    message_id_header: Mapped[str] = mapped_column(String(998), nullable=False, unique=True)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction"),
        nullable=False,
        default=MessageDirection.inbound,
    )
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Raw headers stored as JSON for debugging / replay
    raw_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Attachment metadata: list of {filename, size, content_type}
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Relationships
    thread: Mapped["EmailThread"] = relationship("EmailThread", back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<EmailMessage id={self.id} sender={self.sender} "
            f"received={self.received_at} direction={self.direction}>"
        )


class DraftResponse(Base):
    __tablename__ = "draft_responses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("email_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus, name="draft_status"),
        nullable=False,
        default=DraftStatus.pending,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Phase 2: revision tracking and AI metadata
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    original_body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_entry_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # T1.12: Idempotent send tracking — prevent double-send on retry
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    thread: Mapped["EmailThread"] = relationship("EmailThread", back_populates="drafts")
    reviewed_by: Mapped["User | None"] = relationship("User", foreign_keys=[reviewed_by_id])  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f"<DraftResponse id={self.id} thread_id={self.thread_id} status={self.status}>"


class KnowledgeEntry(Base):
    """
    A knowledge base entry. Staff and Jane can add entries that the AI
    uses as context when drafting responses.
    """
    __tablename__ = "knowledge_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # Phase 2: cross-category tagging, entry classification, and usage tracking
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)), nullable=True)
    entry_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="snippet"
    )  # one of: 'response_template', 'policy', 'snippet'
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f"<KnowledgeEntry id={self.id} title={self.title!r} entry_type={self.entry_type}>"
