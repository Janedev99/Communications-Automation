"""
Tests for FeedbackRetrievalService — the implicit-feedback retrieval layer
that feeds approvals, saved messages, and rejection reasons back into the
draft-generation prompt.

Covers the risk register from FEAT/draft-feedback-loop Stage 1:
  R1 — bad approval mimicked: status filter enforced
  R2 — PII leakage: threads with PII-marked escalations excluded
  R3 — inbound saved message mistaken for "good draft": direction filter
  R4 — prompt bloat: per-block char cap enforced in formatters
  R5 — bootstrap: empty retrievals → empty formatted blocks
  R6 — recency: ORDER BY .desc() on reviewed_at / saved_at
  R7 — regenerate-placeholder noise: filtered from rejection patterns
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.services.draft_feedback import (
    FeedbackRetrievalService,
    _BLOCK_CHARS,
    _PER_EXAMPLE_CHARS,
)

# Categories used per test — distinct per test to keep the StaticPool DB's
# accumulated rows from cross-contaminating queries. conftest.py warns:
# "tests must not rely on absence of data created by other tests."
_CAT_POS = EmailCategory.status_update
_CAT_PII = EmailCategory.document_request
_CAT_CURATED_OUTBOUND = EmailCategory.appointment
_CAT_CURATED_INBOUND_FILTER = EmailCategory.clarification
_CAT_NEG = EmailCategory.general_inquiry
_CAT_NEG_PLACEHOLDER = EmailCategory.complaint
_CAT_BLOAT = EmailCategory.urgent


# ── Helpers to seed data quickly ──────────────────────────────────────────────

def _make_thread(
    db: Session,
    *,
    category: EmailCategory,
    tone: str | None = "professional",
    subject: str | None = None,
) -> EmailThread:
    thread = EmailThread(
        subject=subject or f"Test subject {uuid.uuid4()}",
        client_email=f"client-{uuid.uuid4()}@example.com",
        client_name="Test Client",
        status=EmailStatus.new,
        category=category,
        suggested_reply_tone=tone,
    )
    db.add(thread)
    db.flush()
    return thread


def _make_draft(
    db: Session,
    *,
    thread: EmailThread,
    status: DraftStatus,
    body: str = "Hello — thanks for reaching out, we'll review and follow up shortly.",
    rejection_reason: str | None = None,
    reviewed_at: datetime | None = None,
    reviewed_by_id=None,
) -> DraftResponse:
    draft = DraftResponse(
        thread_id=thread.id,
        body_text=body,
        status=status,
        rejection_reason=rejection_reason,
        reviewed_at=reviewed_at,
        reviewed_by_id=reviewed_by_id,
        created_at=reviewed_at or datetime.now(timezone.utc),
    )
    db.add(draft)
    db.flush()
    return draft


def _make_message(
    db: Session,
    *,
    thread: EmailThread,
    direction: MessageDirection,
    body: str,
    is_saved: bool = False,
    saved_at: datetime | None = None,
) -> EmailMessage:
    msg = EmailMessage(
        thread_id=thread.id,
        message_id_header=f"<{uuid.uuid4()}@test>",
        sender="someone@example.com",
        body_text=body,
        received_at=saved_at or datetime.now(timezone.utc),
        direction=direction,
        is_saved=is_saved,
        saved_at=saved_at if is_saved else None,
    )
    db.add(msg)
    db.flush()
    return msg


def _make_pii_escalation(db: Session, *, thread: EmailThread) -> Escalation:
    esc = Escalation(
        thread_id=thread.id,
        reason="Thread contains sensitive client data (SSN detected)",
        severity=EscalationSeverity.high,
        status=EscalationStatus.pending,
    )
    db.add(esc)
    db.flush()
    return esc


# =============================================================================
# Positive examples — approved drafts in same category, recency-ordered
# =============================================================================

def test_positive_examples_returns_approved_in_category(db_session: Session):
    """R6: most recent approved drafts come first."""
    now = datetime.now(timezone.utc)
    thread_old = _make_thread(db_session, category=_CAT_POS)
    thread_new = _make_thread(db_session, category=_CAT_POS)
    _make_draft(
        db_session, thread=thread_old, status=DraftStatus.approved,
        body="OLD draft", reviewed_at=now - timedelta(days=5),
    )
    _make_draft(
        db_session, thread=thread_new, status=DraftStatus.approved,
        body="NEW draft", reviewed_at=now - timedelta(hours=1),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=_CAT_POS.value, limit=5)

    bodies = [r.body for r in results]
    assert "NEW draft" in bodies
    assert "OLD draft" in bodies
    # Most-recent first
    assert bodies.index("NEW draft") < bodies.index("OLD draft")


def test_positive_examples_excludes_non_approved_statuses(db_session: Session):
    """R1: edited/rejected/pending drafts must not surface as positive examples."""
    cat = EmailCategory.complaint  # distinct from other tests
    thread = _make_thread(db_session, category=cat)
    _make_draft(db_session, thread=thread, status=DraftStatus.pending, body="PENDING")
    _make_draft(db_session, thread=thread, status=DraftStatus.edited, body="EDITED")
    _make_draft(db_session, thread=thread, status=DraftStatus.rejected, body="REJECTED",
                rejection_reason="too formal")

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value)

    bodies = [r.body for r in results]
    assert "PENDING" not in bodies
    assert "EDITED" not in bodies
    assert "REJECTED" not in bodies


def test_positive_examples_excludes_pii_threads(db_session: Session):
    """R2: drafts from threads with a PII escalation must never surface."""
    thread_safe = _make_thread(db_session, category=_CAT_PII)
    thread_pii = _make_thread(db_session, category=_CAT_PII)
    _make_pii_escalation(db_session, thread=thread_pii)

    _make_draft(db_session, thread=thread_safe, status=DraftStatus.approved,
                body="SAFE", reviewed_at=datetime.now(timezone.utc))
    _make_draft(db_session, thread=thread_pii, status=DraftStatus.approved,
                body="PII LEAK CANDIDATE", reviewed_at=datetime.now(timezone.utc))

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=_CAT_PII.value)

    bodies = [r.body for r in results]
    assert "SAFE" in bodies
    assert "PII LEAK CANDIDATE" not in bodies


def test_positive_examples_respects_limit(db_session: Session):
    cat = EmailCategory.uncategorized  # exclusive to this test
    for i in range(5):
        thread = _make_thread(db_session, category=cat)
        _make_draft(
            db_session, thread=thread, status=DraftStatus.approved,
            body=f"draft-{i}",
            reviewed_at=datetime.now(timezone.utc) - timedelta(minutes=i),
        )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value, limit=2)
    assert len(results) == 2


def test_positive_examples_includes_sent_drafts(db_session: Session):
    """
    Regression guard: in the normal flow staff approve → send within
    seconds, so the `approved` state is ephemeral. An approved-only filter
    surfaces zero examples for any staff member who routinely sends what
    they approve. Both `approved` and `sent` must qualify as positive
    examples or the feedback loop accumulates nothing over time.
    """
    # `clarification` only carries EmailMessage seeds in other tests
    # (curated-inbound paths) — no drafts, so seeding 2 here doesn't
    # contaminate any sibling test's `len(results) == N` assertion.
    cat = EmailCategory.clarification
    now = datetime.now(timezone.utc)
    thread_a = _make_thread(db_session, category=cat)
    thread_s = _make_thread(db_session, category=cat)
    _make_draft(
        db_session, thread=thread_a, status=DraftStatus.approved,
        body="APPROVED body", reviewed_at=now - timedelta(minutes=10),
    )
    _make_draft(
        db_session, thread=thread_s, status=DraftStatus.sent,
        body="SENT body", reviewed_at=now - timedelta(minutes=1),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value, limit=5)
    bodies = [r.body for r in results]

    assert "APPROVED body" in bodies, (
        "Approved drafts must remain positive examples"
    )
    assert "SENT body" in bodies, (
        "Sent drafts must surface as positive examples — the approve→send "
        "transition happens in seconds and an approved-only filter loses "
        "every example as soon as it ships"
    )
    # Recency order: SENT was reviewed more recently
    assert bodies.index("SENT body") < bodies.index("APPROVED body")


def test_positive_examples_excludes_send_failed(db_session: Session):
    """
    `send_failed` bodies are approved-but-never-delivered. Treating them as
    positive examples would train the prompt on text the recipient never
    saw — and the body is commonly stale (Jane edits before retrying). Pin
    the exclusion so a future "include every status that was once approved"
    refactor doesn't accidentally pull these in.
    """
    # `clarification` only carries EmailMessage seeds in other tests
    # (curated-inbound-filter path) — no draft pollution.
    cat = EmailCategory.clarification
    thread = _make_thread(db_session, category=cat)
    _make_draft(
        db_session, thread=thread, status=DraftStatus.send_failed,
        body="STALE FAILED BODY",
        reviewed_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value)
    bodies = [r.body for r in results]

    assert "STALE FAILED BODY" not in bodies


# =============================================================================
# Curated examples — outbound saved messages only
# =============================================================================

def test_curated_examples_includes_outbound_excludes_inbound(db_session: Session):
    """R3: inbound saved messages must not be treated as good drafts."""
    thread = _make_thread(db_session, category=_CAT_CURATED_OUTBOUND)
    _make_message(
        db_session, thread=thread, direction=MessageDirection.outbound,
        body="OUTBOUND-GOOD", is_saved=True,
        saved_at=datetime.now(timezone.utc),
    )
    _make_message(
        db_session, thread=thread, direction=MessageDirection.inbound,
        body="INBOUND-CLIENT", is_saved=True,
        saved_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_curated_examples(db_session, category=_CAT_CURATED_OUTBOUND.value)

    bodies = [r.body for r in results]
    assert "OUTBOUND-GOOD" in bodies
    assert "INBOUND-CLIENT" not in bodies


def test_curated_examples_excludes_unsaved_messages(db_session: Session):
    thread = _make_thread(db_session, category=_CAT_CURATED_INBOUND_FILTER)
    _make_message(
        db_session, thread=thread, direction=MessageDirection.outbound,
        body="NOT-SAVED", is_saved=False,
    )

    svc = FeedbackRetrievalService()
    results = svc.get_curated_examples(db_session, category=_CAT_CURATED_INBOUND_FILTER.value)
    assert results == []


# =============================================================================
# Negative patterns — rejection reasons
# =============================================================================

def test_negative_patterns_returns_real_rejection_reasons(db_session: Session):
    thread = _make_thread(db_session, category=_CAT_NEG)
    _make_draft(
        db_session, thread=thread, status=DraftStatus.rejected,
        body="...", rejection_reason="too formal for ongoing client",
        reviewed_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_negative_patterns(db_session, category=_CAT_NEG.value)

    reasons = [n.reason for n in results]
    assert "too formal for ongoing client" in reasons


def test_negative_patterns_excludes_regenerate_placeholder(db_session: Session):
    """R7: the auto-set 'Regenerated by staff' placeholder must be filtered."""
    thread = _make_thread(db_session, category=_CAT_NEG_PLACEHOLDER)
    _make_draft(
        db_session, thread=thread, status=DraftStatus.rejected,
        body="...", rejection_reason="Regenerated by staff",
        reviewed_at=datetime.now(timezone.utc),
    )
    _make_draft(
        db_session, thread=thread, status=DraftStatus.rejected,
        body="...", rejection_reason="missed the deadline",
        reviewed_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_negative_patterns(db_session, category=_CAT_NEG_PLACEHOLDER.value)

    reasons = [n.reason for n in results]
    assert "Regenerated by staff" not in reasons
    assert "missed the deadline" in reasons


# =============================================================================
# Formatters
# =============================================================================

def test_format_examples_empty_inputs_returns_empty_string():
    """R5: bootstrap state — empty data must produce empty block, not a placeholder."""
    svc = FeedbackRetrievalService()
    assert svc.format_examples([], []) == ""


def test_format_negatives_empty_input_returns_empty_string():
    svc = FeedbackRetrievalService()
    assert svc.format_negatives([]) == ""


def _example(source: str, body: str, *, tone: str | None = None) -> "FeedbackExample":
    """Test helper — constructs a FeedbackExample with sensible defaults."""
    from app.services.draft_feedback import FeedbackExample
    now = datetime.now(timezone.utc)
    return FeedbackExample(
        source=source,
        body=body,
        occurred_at=now,
        tone=tone,
        subject=None,
        actor_name=None,
    )


def test_format_examples_deduplicates_across_positive_and_curated():
    """The same body shouldn't render twice if it's both approved and saved."""
    shared = _example("approved", "identical body")
    saved_dupe = _example("saved", "identical body")

    svc = FeedbackRetrievalService()
    output = svc.format_examples([shared], [saved_dupe])

    # Only one rendering of the body — and the saved label wins (rendered first)
    assert output.count("identical body") == 1
    assert "[SAVED" in output
    # Approved label should NOT appear because the saved version pre-empted it
    assert "[APPROVED" not in output


def test_format_examples_caps_total_block_size():
    """R4: prompt bloat — total formatted block stays under the budget."""
    huge = "A" * _PER_EXAMPLE_CHARS  # already truncated by retrieval, but assert formatter cap too
    examples = [_example("approved", huge) for _ in range(10)]

    svc = FeedbackRetrievalService()
    output = svc.format_examples([], examples)
    # Block cap is a *soft* cap (last entry that exceeds is dropped) — assert
    # the rendered length is comfortably bounded.
    assert len(output) <= _BLOCK_CHARS + 200  # header + closing "---" overhead


# =============================================================================
# Enrichment fields — tone, subject, actor_name (v1.1)
# =============================================================================

def test_positive_examples_surface_thread_tone_and_subject(db_session: Session):
    """Enrichment: tone + subject populate from the source thread."""
    cat = EmailCategory.appointment  # distinct from other tests
    thread = _make_thread(
        db_session,
        category=cat,
        tone="empathetic",
        subject="Re: Reschedule next week's review",
    )
    _make_draft(
        db_session, thread=thread, status=DraftStatus.approved,
        body="Sure, let's move it.", reviewed_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value)

    assert len(results) == 1
    assert results[0].tone == "empathetic"
    assert results[0].subject == "Re: Reschedule next week's review"
    # No reviewer attached → actor_name is None (still a valid example)
    assert results[0].actor_name is None


def test_positive_examples_surface_reviewer_name(db_session: Session, admin_user):
    """Enrichment: actor_name reflects who approved the draft."""
    cat = EmailCategory.general_inquiry  # distinct from earlier tests
    thread = _make_thread(db_session, category=cat, tone="direct")
    _make_draft(
        db_session, thread=thread, status=DraftStatus.approved,
        body="Looks good.", reviewed_at=datetime.now(timezone.utc),
        reviewed_by_id=admin_user.id,
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value)

    assert len(results) == 1
    assert results[0].actor_name == "Jane Admin"


def test_format_examples_includes_tone_in_prompt_label():
    """Tone is a steering signal — must surface in the prompt label."""
    ex = _example("approved", "body text", tone="empathetic")
    svc = FeedbackRetrievalService()
    output = svc.format_examples([], [ex])
    assert "empathetic tone" in output
    assert "[APPROVED · empathetic tone" in output


def test_format_examples_omits_tone_when_missing():
    """Threads without a tone shouldn't produce ' ·  · ' artefacts in the label."""
    ex = _example("approved", "body text", tone=None)
    svc = FeedbackRetrievalService()
    output = svc.format_examples([], [ex])
    # Label should be "[APPROVED · <date>]" — no double separators or empty tokens
    assert "·  ·" not in output
    assert "tone" not in output


def test_format_negatives_includes_tone_when_present():
    """Tone helps steer Claude away from 'professional tone got rejected as too formal'."""
    from app.services.draft_feedback import FeedbackNegative
    now = datetime.now(timezone.utc)
    neg = FeedbackNegative(
        reason="too formal for ongoing client",
        occurred_at=now,
        tone="professional",
        subject=None,
        actor_name=None,
    )
    svc = FeedbackRetrievalService()
    output = svc.format_negatives([neg])
    assert "too formal for ongoing client (professional tone)" in output


def test_retrieval_returns_full_body_for_ui_budget(db_session: Session):
    """UI gets the long body; prompt formatter trims separately."""
    from app.services.draft_feedback import (
        _PER_EXAMPLE_CHARS_PROMPT,
        _PER_EXAMPLE_CHARS_UI,
    )
    cat = EmailCategory.appointment  # reused from earlier tone test, distinct row
    thread = _make_thread(db_session, category=cat, subject="Long body test")
    # Body well over the prompt cap but under the UI cap
    long_body = "B" * (_PER_EXAMPLE_CHARS_PROMPT + 800)
    _make_draft(
        db_session, thread=thread, status=DraftStatus.approved,
        body=long_body, reviewed_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value)
    long_one = next((r for r in results if r.body.startswith("B")), None)
    assert long_one is not None
    # UI-side: body should be (close to) the full thing — not the 400-cap
    assert len(long_one.body) > _PER_EXAMPLE_CHARS_PROMPT
    assert len(long_one.body) <= _PER_EXAMPLE_CHARS_UI + 1  # +1 for trailing ellipsis

    # Prompt-side: formatter must still clip to the prompt budget
    output = svc.format_examples([long_one], [])
    # Count Bs in the rendered prompt to verify the formatter clipped
    rendered_b_count = output.count("B")
    assert rendered_b_count <= _PER_EXAMPLE_CHARS_PROMPT


def test_subject_is_truncated_for_long_titles(db_session: Session):
    """Subjects past _SUBJECT_CHARS get trimmed with an ellipsis."""
    from app.services.draft_feedback import _SUBJECT_CHARS
    cat = EmailCategory.uncategorized
    long_subject = "X" * (_SUBJECT_CHARS + 50)
    thread = _make_thread(db_session, category=cat, subject=long_subject)
    _make_draft(
        db_session, thread=thread, status=DraftStatus.approved,
        body="ok", reviewed_at=datetime.now(timezone.utc),
    )

    svc = FeedbackRetrievalService()
    results = svc.get_positive_examples(db_session, category=cat.value)
    # Pick the one with the long subject (uncategorized may contain other rows
    # from earlier tests; filter)
    long_one = next((r for r in results if r.subject and r.subject.startswith("X")), None)
    assert long_one is not None
    assert long_one.subject is not None
    assert len(long_one.subject) <= _SUBJECT_CHARS + 1  # +1 for ellipsis
    assert long_one.subject.endswith("…")
