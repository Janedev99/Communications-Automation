"""Escalation model — tracks emails that need Jane's direct attention."""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EscalationSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class EscalationStatus(str, enum.Enum):
    pending = "pending"             # Just created, not yet seen
    acknowledged = "acknowledged"  # Jane has seen it
    resolved = "resolved"          # Jane has handled it


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("email_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[EscalationSeverity] = mapped_column(
        Enum(EscalationSeverity, name="escalation_severity"),
        nullable=False,
        default=EscalationSeverity.medium,
        index=True,
    )
    status: Mapped[EscalationStatus] = mapped_column(
        Enum(EscalationStatus, name="escalation_status"),
        nullable=False,
        default=EscalationStatus.pending,
        index=True,
    )
    # Which staff member (or Jane) this is assigned to
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    thread: Mapped["EmailThread"] = relationship(  # type: ignore[name-defined]
        "EmailThread", back_populates="escalations"
    )
    assigned_to: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[assigned_to_id],
        back_populates="assigned_escalations",
    )
    resolved_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[resolved_by_id],
        back_populates="resolved_escalations",
    )

    def __repr__(self) -> str:
        return (
            f"<Escalation id={self.id} thread_id={self.thread_id} "
            f"severity={self.severity} status={self.status}>"
        )
