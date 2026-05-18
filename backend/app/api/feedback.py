"""
Feedback context routes.

GET /feedback/preview?category=<EmailCategory>

Returns the same positive examples, curated saved messages, and negative
patterns that ``DraftGeneratorService.generate()`` injects into the prompt
for that category. Powers two UI surfaces:

  - The "Informed by N examples" panel on a draft card (read-only view
    that lets staff see what shaped the AI's output)
  - The admin debug page at /settings/ai/feedback-debug

Single endpoint, single shape. Authenticated (any user role) — the data
is already visible to anyone who can see drafts, so no separate admin
gate beyond the standard session check.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.email import EmailCategory
from app.models.user import User
from app.services.draft_feedback import (
    FeedbackExample,
    FeedbackNegative,
    get_feedback_service,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


# ── Response shapes ───────────────────────────────────────────────────────────


class FeedbackExampleOut(BaseModel):
    source: str  # "approved" | "saved"
    body: str
    occurred_at: str
    tone: str | None = None
    subject: str | None = None
    actor_name: str | None = None  # who approved (drafts) or saved (messages)


class FeedbackNegativeOut(BaseModel):
    reason: str
    occurred_at: str
    tone: str | None = None
    subject: str | None = None
    actor_name: str | None = None  # who rejected


class FeedbackCountsOut(BaseModel):
    positive: int
    curated: int
    negative: int


class FeedbackPreviewResponse(BaseModel):
    category: str
    positive: list[FeedbackExampleOut]
    curated: list[FeedbackExampleOut]
    negative: list[FeedbackNegativeOut]
    counts: FeedbackCountsOut


def _example_out(ex: FeedbackExample) -> FeedbackExampleOut:
    return FeedbackExampleOut(
        source=ex.source,
        body=ex.body,
        occurred_at=ex.occurred_at.isoformat(),
        tone=ex.tone,
        subject=ex.subject,
        actor_name=ex.actor_name,
    )


def _negative_out(neg: FeedbackNegative) -> FeedbackNegativeOut:
    return FeedbackNegativeOut(
        reason=neg.reason,
        occurred_at=neg.occurred_at.isoformat(),
        tone=neg.tone,
        subject=neg.subject,
        actor_name=neg.actor_name,
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/preview", response_model=FeedbackPreviewResponse)
def preview_feedback(
    category: EmailCategory = Query(
        ..., description="EmailCategory enum value (e.g. status_update)"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FeedbackPreviewResponse:
    """
    Return the implicit-feedback context the AI would see for this category.

    Same retrieval used by the draft generator — applies the PII filter,
    outbound-only filter on saved messages, status filter on drafts, and
    regenerate-placeholder filter on rejection reasons (see
    services/draft_feedback.py for the full risk register).
    """
    svc = get_feedback_service()
    positive = svc.get_positive_examples(db, category=category.value)
    curated = svc.get_curated_examples(db, category=category.value)
    negative = svc.get_negative_patterns(db, category=category.value)

    return FeedbackPreviewResponse(
        category=category.value,
        positive=[_example_out(e) for e in positive],
        curated=[_example_out(e) for e in curated],
        negative=[_negative_out(n) for n in negative],
        counts=FeedbackCountsOut(
            positive=len(positive),
            curated=len(curated),
            negative=len(negative),
        ),
    )
