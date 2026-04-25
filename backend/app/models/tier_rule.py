"""TierRule model — per-category triage rule (T1 eligibility + threshold).

Each category has exactly one row in tier_rules. Admins can flip
`t1_eligible` or adjust `t1_min_confidence` via the API.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.email import EmailCategory


class TierRule(Base):
    __tablename__ = "tier_rules"
    __table_args__ = (
        UniqueConstraint("category", name="uq_tier_rules_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category: Mapped[EmailCategory] = mapped_column(
        Enum(EmailCategory, name="email_category"),
        nullable=False,
    )
    t1_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    t1_min_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.92
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<TierRule category={self.category} t1_eligible={self.t1_eligible} "
            f"min_conf={self.t1_min_confidence}>"
        )
