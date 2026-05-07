"""Pydantic schemas for the What's New / release_notes feature."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.release import GeneratedFromSource, ReleaseStatus


# ── User-facing ──────────────────────────────────────────────────────────────


class LatestUnreadResponse(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    published_at: datetime


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
    body: str
    status: ReleaseStatus
    generated_from: GeneratedFromSource | None
    commit_sha_at_release: str | None
    created_by: CreatedByBrief
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class CreateReleaseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1)
    generated_from: GeneratedFromSource | None = None
    commit_sha_at_release: str | None = Field(default=None, max_length=40)


class UpdateReleaseRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1)


# ── AI generation ────────────────────────────────────────────────────────────


class DraftFromCommitsGitHubRequest(BaseModel):
    source: Literal["github_api"]
    since_sha: str | None = Field(default=None, max_length=40)


class DraftFromCommitsManualRequest(BaseModel):
    source: Literal["manual_paste"]
    commits: list[str] = Field(min_length=1, max_length=500)


class DraftSuggestionResponse(BaseModel):
    title_suggestion: str
    body_suggestion: str
    commit_count: int
    commit_sha_at_release: str | None
    generated_from: GeneratedFromSource
    low_confidence: bool
