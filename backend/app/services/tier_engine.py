"""
Tier engine — decides T1 / T2 / T3 from a categorization result + escalation flag.

Decision order (first match wins):
  1. Escalation triggered  →  T3 (escalate)
  2. Source = rules_fallback  →  T2 (never auto-send a fallback result)
  3. Category in tier_rules with t1_eligible=true AND confidence ≥ threshold  →  T1
  4. Otherwise  →  T2 (staff review)

Reads tier_rules from the DB. Caching is disabled for V1 — admin changes
take effect immediately. Add a TTL cache later if rules_engine becomes hot.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import CategorizationSource, EmailCategory, ThreadTier
from app.models.tier_rule import TierRule
from app.schemas.email import CategorizationResult

logger = logging.getLogger(__name__)


@dataclass
class TierDecision:
    tier: ThreadTier
    reason: str  # human-readable, for audit log


def decide_tier(
    db: Session,
    *,
    result: CategorizationResult,
    source: CategorizationSource,
) -> TierDecision:
    """Decide which tier this thread belongs to.

    Args:
      db: open SQLAlchemy session — used to fetch the per-category rule.
      result: categorization output (category, confidence, escalation flag).
      source: where the categorization came from (Claude vs rules fallback).
    """
    # 1. Escalation always wins
    if result.escalation_needed:
        return TierDecision(
            tier=ThreadTier.t3_escalate,
            reason="Escalation criteria matched",
        )

    # 2. Rules-fallback never auto-sends — confidence is unreliable
    if source == CategorizationSource.rules_fallback:
        return TierDecision(
            tier=ThreadTier.t2_review,
            reason="Categorized via rules fallback — staff review required",
        )

    # 3. Look up per-category rule
    rule = db.execute(
        select(TierRule).where(TierRule.category == result.category)
    ).scalar_one_or_none()

    if rule is None:
        # Defensive: if no rule row exists for this category, default to T2.
        # Should not happen in practice — migration 009 seeds a row per category.
        logger.warning(
            "tier_engine: no tier_rule for category=%s — defaulting to T2",
            result.category.value,
        )
        return TierDecision(
            tier=ThreadTier.t2_review,
            reason=f"No tier rule for category {result.category.value}",
        )

    if rule.t1_eligible and result.confidence >= rule.t1_min_confidence:
        return TierDecision(
            tier=ThreadTier.t1_auto,
            reason=(
                f"T1-eligible category {result.category.value} "
                f"with confidence {result.confidence:.2f} ≥ {rule.t1_min_confidence:.2f}"
            ),
        )

    if rule.t1_eligible and result.confidence < rule.t1_min_confidence:
        return TierDecision(
            tier=ThreadTier.t2_review,
            reason=(
                f"Confidence {result.confidence:.2f} below T1 threshold "
                f"{rule.t1_min_confidence:.2f} for {result.category.value}"
            ),
        )

    return TierDecision(
        tier=ThreadTier.t2_review,
        reason=f"Category {result.category.value} not enabled for T1 auto-send",
    )
