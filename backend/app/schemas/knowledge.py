"""Pydantic schemas for KnowledgeEntry CRUD operations."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valid entry types — kept as a Literal so FastAPI renders them in OpenAPI docs
EntryType = Literal["response_template", "policy", "snippet"]

VALID_ENTRY_TYPES: set[str] = {"response_template", "policy", "snippet"}


# ── Request schemas ────────────────────────────────────────────────────────────

class CreateKnowledgeEntryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    category: str | None = Field(
        default=None,
        max_length=128,
        description="EmailCategory value this entry targets (e.g. 'status_update'). "
                    "Leave null for policy entries that apply to all categories.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Additional category values this entry should be retrieved for.",
    )
    entry_type: EntryType = Field(
        default="snippet",
        description="Type of entry: 'response_template', 'policy', or 'snippet'.",
    )


class UpdateKnowledgeEntryRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    content: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = None
    entry_type: EntryType | None = None
    is_active: bool | None = None


# ── Response schemas ───────────────────────────────────────────────────────────

class KnowledgeEntryResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    content: str
    category: str | None
    is_active: bool
    tags: list[str] | None
    entry_type: str
    usage_count: int
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class KnowledgeEntryListResponse(BaseModel):
    items: list[KnowledgeEntryResponse]
    total: int
    page: int
    page_size: int
