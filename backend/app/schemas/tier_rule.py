"""Pydantic schemas for tier_rules CRUD."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.email import EmailCategory


class TierRuleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    category: EmailCategory
    t1_eligible: bool
    t1_min_confidence: float
    updated_at: datetime
    updated_by_id: uuid.UUID | None = None
    updated_by_name: str | None = None


class TierRuleUpdate(BaseModel):
    """Partial update — both fields optional. PATCH semantics."""
    t1_eligible: bool | None = None
    t1_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
