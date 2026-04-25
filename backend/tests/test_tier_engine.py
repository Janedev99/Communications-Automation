"""
Tests for the tier_engine — the function that maps a CategorizationResult
plus its source into a triage tier (T1/T2/T3).

Decision rules (from app/services/tier_engine.py):
  1. escalation_needed=True  →  T3 escalate
  2. source=rules_fallback   →  T2 review (regardless of confidence)
  3. category in tier_rules with t1_eligible=True AND confidence ≥ threshold  →  T1
  4. else  →  T2 review
"""
from __future__ import annotations

import uuid
from typing import Iterable

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.email import (
    CategorizationSource,
    EmailCategory,
    ThreadTier,
)
from app.models.tier_rule import TierRule
from app.schemas.email import CategorizationResult
from app.services.tier_engine import decide_tier


# ── Test helpers ──────────────────────────────────────────────────────────────


def _result(
    *,
    category: EmailCategory = EmailCategory.status_update,
    confidence: float = 0.95,
    escalate: bool = False,
    source: CategorizationSource = CategorizationSource.claude,
) -> CategorizationResult:
    return CategorizationResult(
        category=category,
        confidence=confidence,
        escalation_needed=escalate,
        escalation_reasons=["test"] if escalate else [],
        summary="test",
        suggested_reply_tone="professional",
        source=source,
    )


@pytest.fixture()
def seeded_rules(db_session: Session):
    """Wipe + reseed tier_rules with known state for these tests.

    `status_update` is enabled at threshold 0.90;
    `appointment` is enabled at 0.95;
    everything else is disabled.
    """
    db_session.execute(delete(TierRule))
    rules: Iterable[tuple[EmailCategory, bool, float]] = [
        (EmailCategory.status_update,    True,  0.90),
        (EmailCategory.appointment,      True,  0.95),
        (EmailCategory.document_request, False, 0.92),
        (EmailCategory.clarification,    False, 0.92),
        (EmailCategory.general_inquiry,  False, 0.92),
        (EmailCategory.complaint,        False, 0.99),
        (EmailCategory.urgent,           False, 0.99),
        (EmailCategory.uncategorized,    False, 0.99),
    ]
    for cat, eligible, threshold in rules:
        db_session.add(
            TierRule(
                id=uuid.uuid4(),
                category=cat,
                t1_eligible=eligible,
                t1_min_confidence=threshold,
            )
        )
    db_session.flush()
    yield
    # Clean up so other tests see no tier rules
    db_session.execute(delete(TierRule))
    db_session.flush()


# ── 1. Escalation always wins ─────────────────────────────────────────────────


def test_escalation_routes_to_t3(seeded_rules, db_session):
    """Even if the category is T1-eligible and confidence is high."""
    result = _result(
        category=EmailCategory.status_update,
        confidence=0.99,
        escalate=True,
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t3_escalate
    assert "escalation" in decision.reason.lower()


def test_escalation_beats_high_confidence_appointment(seeded_rules, db_session):
    result = _result(
        category=EmailCategory.appointment,
        confidence=0.99,
        escalate=True,
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t3_escalate


# ── 2. Rules-fallback never auto-sends ────────────────────────────────────────


def test_rules_fallback_source_blocks_t1_even_at_high_confidence(seeded_rules, db_session):
    """A rules_fallback result is never trusted for T1 (its confidence is unreliable)."""
    result = _result(
        category=EmailCategory.status_update,
        confidence=0.99,  # absurdly high — can't happen in real fallback (capped at 0.5)
        source=CategorizationSource.rules_fallback,
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.rules_fallback)
    assert decision.tier == ThreadTier.t2_review
    assert "fallback" in decision.reason.lower()


# ── 3. Allowlist + threshold logic ────────────────────────────────────────────


def test_eligible_category_above_threshold_becomes_t1(seeded_rules, db_session):
    result = _result(
        category=EmailCategory.status_update,
        confidence=0.95,  # above 0.90 threshold
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t1_auto


def test_eligible_category_at_exact_threshold_becomes_t1(seeded_rules, db_session):
    """Boundary check: ≥ threshold qualifies (inclusive)."""
    result = _result(
        category=EmailCategory.status_update,
        confidence=0.90,  # exactly the threshold
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t1_auto


def test_eligible_category_below_threshold_becomes_t2(seeded_rules, db_session):
    result = _result(
        category=EmailCategory.status_update,
        confidence=0.89,  # just below 0.90
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t2_review
    assert "below" in decision.reason.lower() or "threshold" in decision.reason.lower()


def test_appointment_threshold_is_higher(seeded_rules, db_session):
    """Appointment is configured stricter (0.95). Confirm 0.93 is rejected."""
    result = _result(category=EmailCategory.appointment, confidence=0.93)
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t2_review

    # And 0.96 makes it
    result_pass = _result(category=EmailCategory.appointment, confidence=0.96)
    decision_pass = decide_tier(
        db_session, result=result_pass, source=CategorizationSource.claude
    )
    assert decision_pass.tier == ThreadTier.t1_auto


# ── 4. Non-allowlisted categories stay T2 even at high confidence ─────────────


def test_disabled_category_stays_t2_at_high_confidence(seeded_rules, db_session):
    result = _result(
        category=EmailCategory.document_request,  # t1_eligible=False in fixture
        confidence=0.99,
    )
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t2_review


def test_complaint_never_becomes_t1(seeded_rules, db_session):
    """Complaint must always route to staff — risk floor."""
    result = _result(category=EmailCategory.complaint, confidence=0.99)
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t2_review


# ── 5. Defensive: missing tier_rule row → T2 ──────────────────────────────────


def test_missing_rule_defaults_to_t2(db_session):
    """If somehow no rule exists for the category, default to T2 (don't crash)."""
    # NB: no seeded_rules fixture — table is empty
    db_session.execute(delete(TierRule))
    db_session.flush()

    result = _result(category=EmailCategory.status_update, confidence=0.99)
    decision = decide_tier(db_session, result=result, source=CategorizationSource.claude)
    assert decision.tier == ThreadTier.t2_review
    assert "no tier rule" in decision.reason.lower()
