"""Pydantic schemas for the What's New / release_notes feature."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.release import (
    GeneratedFromSource,
    HighlightCategory,
    ReleaseStatus,
)


# ── Highlights ───────────────────────────────────────────────────────────────


class Highlight(BaseModel):
    """One row in a release's highlights list — drives chip rendering."""
    model_config = ConfigDict(use_enum_values=True)

    category: HighlightCategory
    text: str = Field(min_length=1, max_length=140)


# ── User-facing ──────────────────────────────────────────────────────────────


class LatestUnreadResponse(BaseModel):
    id: uuid.UUID
    title: str
    # body is preserved for legacy releases that pre-date the structured
    # shape; new releases set summary + highlights and may set body=None.
    body: str | None
    summary: str | None
    highlights: list[Highlight]
    published_at: datetime


class ReleaseArchiveItem(BaseModel):
    """One entry in the /releases/archive paginated list. Same shape as
    LatestUnreadResponse — the frontend renders both via <ReleaseNoteCard />."""
    id: uuid.UUID
    title: str
    body: str | None
    summary: str | None
    highlights: list[Highlight]
    published_at: datetime


class ReleaseArchiveResponse(BaseModel):
    """Cursor-paginated archive of published releases (reverse-chrono).

    next_cursor is the id of the next release to fetch after this page,
    or None when the caller has reached the end.
    """
    items: list[ReleaseArchiveItem]
    next_cursor: uuid.UUID | None


class DismissRequest(BaseModel):
    dont_show_again: bool


class UpdateUserPreferencesRequest(BaseModel):
    hide_releases_forever: bool | None = None


# ── Admin-facing ─────────────────────────────────────────────────────────────


class CreatedByBrief(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class ReleaseAdminResponse(BaseModel):
    id: uuid.UUID
    title: str
    body: str | None
    summary: str | None
    highlights: list[Highlight]
    status: ReleaseStatus
    generated_from: GeneratedFromSource | None
    commit_sha_at_release: str | None
    created_by: CreatedByBrief
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class CreateReleaseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    # At least one of body / (summary + highlights) must be present —
    # enforced in the API layer because the rule is cross-field. The
    # publish endpoint additionally requires summary + highlights≥1.
    body: str | None = Field(default=None)
    summary: str | None = Field(default=None, max_length=400)
    highlights: list[Highlight] = Field(default_factory=list, max_length=20)
    generated_from: GeneratedFromSource | None = None
    commit_sha_at_release: str | None = Field(default=None, max_length=40)


class UpdateReleaseRequest(BaseModel):
    """All fields optional — patch semantics. Pass [] for highlights to clear."""
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None)
    summary: str | None = Field(default=None, max_length=400)
    highlights: list[Highlight] | None = Field(default=None, max_length=20)


# ── AI generation ────────────────────────────────────────────────────────────


class DraftFromCommitsRequest(BaseModel):
    """Single shape for the draft-from-commits endpoint.

    The endpoint now reads commits from the build-time release-meta.json
    snapshot — no source discriminator, no admin paste, no GitHub call.
    The optional since_sha boundary lets admins generate notes for a
    sub-range; when omitted, the endpoint defaults to the SHA of the
    last published release (or the full snapshot if none published yet).
    """
    since_sha: str | None = Field(default=None, max_length=40)


class DraftSuggestionResponse(BaseModel):
    title_suggestion: str
    summary_suggestion: str
    highlights_suggestion: list[Highlight]
    commit_count: int
    commit_sha_at_release: str | None
    generated_from: GeneratedFromSource
    low_confidence: bool
