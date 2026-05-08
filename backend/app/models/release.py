"""Release and UserReleaseDismissal models for the What's New feature."""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReleaseStatus(str, enum.Enum):
    draft = "draft"
    published = "published"


class GeneratedFromSource(str, enum.Enum):
    github_api = "github_api"
    manual_paste = "manual_paste"
    manual_only = "manual_only"


class HighlightCategory(str, enum.Enum):
    """Category badge shown on each highlight chip in the modal/archive."""
    new = "new"
    improved = "improved"
    fixed = "fixed"


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # body is preserved for backward compat with already-published releases
    # that pre-date the structured (summary + highlights) shape. New
    # publishes are blocked from body-only mode by API-layer validation.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # list[{category: "new"|"improved"|"fixed", text: str}] — see
    # HighlightCategory enum and the Pydantic Highlight schema for the
    # validated shape. Stored as generic JSON (works on Postgres + SQLite).
    highlights: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list,
    )
    status: Mapped[ReleaseStatus] = mapped_column(
        Enum(ReleaseStatus, name="release_status"),
        nullable=False, default=ReleaseStatus.draft, index=True,
    )
    generated_from: Mapped[GeneratedFromSource | None] = mapped_column(
        Enum(GeneratedFromSource, name="release_generated_from"),
        nullable=True,
    )
    commit_sha_at_release: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
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
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    created_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[created_by_id],
    )
    dismissals: Mapped[list["UserReleaseDismissal"]] = relationship(
        "UserReleaseDismissal",
        back_populates="release",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} title={self.title!r} status={self.status}>"


class UserReleaseDismissal(Base):
    __tablename__ = "user_release_dismissals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("releases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dont_show_again: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User")  # type: ignore[name-defined]
    release: Mapped["Release"] = relationship(
        "Release", back_populates="dismissals",
    )

    def __repr__(self) -> str:
        return (
            f"<UserReleaseDismissal user_id={self.user_id} "
            f"release_id={self.release_id} dont_show_again={self.dont_show_again}>"
        )
