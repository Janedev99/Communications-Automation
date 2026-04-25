"""
Triage tier rules — admin-only.

GET   /tier-rules            — list all rules (one per category)
PATCH /tier-rules/{category} — update one rule (t1_eligible / t1_min_confidence)

Rules drive the tier_engine's decision: which categories may be auto-handled
(T1) and at what minimum confidence level. Default state is everything off.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, require_admin, require_csrf
from app.database import get_db
from app.models.email import EmailCategory
from app.models.tier_rule import TierRule
from app.models.user import User
from app.schemas.tier_rule import TierRuleResponse, TierRuleUpdate
from app.utils.audit import log_action

# Categories that may NEVER be enabled for T1 auto-send. Hard-coded safety
# rail — staff must always review these regardless of admin choice. Rationale:
# - complaint  : an angry client should never get an auto-reply.
# - urgent     : high-stakes by definition; needs human eyes.
# - uncategorized : we don't even know what it is — defer to staff.
T1_LOCKED_CATEGORIES: frozenset[EmailCategory] = frozenset({
    EmailCategory.complaint,
    EmailCategory.urgent,
    EmailCategory.uncategorized,
})


router = APIRouter(prefix="/tier-rules", tags=["tier-rules"])


def _to_response(rule: TierRule, updated_by: User | None) -> TierRuleResponse:
    return TierRuleResponse(
        id=rule.id,
        category=rule.category,
        t1_eligible=rule.t1_eligible,
        t1_min_confidence=rule.t1_min_confidence,
        updated_at=rule.updated_at,
        updated_by_id=rule.updated_by_id,
        updated_by_name=updated_by.name if updated_by else None,
    )


@router.get("", response_model=list[TierRuleResponse])
def list_tier_rules(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TierRuleResponse]:
    """List all tier rules. One row per category (seeded by migration 009)."""
    rows = db.execute(
        select(TierRule).order_by(TierRule.category)
    ).scalars().all()

    # Resolve updated_by names in one pass
    user_ids = {r.updated_by_id for r in rows if r.updated_by_id}
    user_map: dict = {}
    if user_ids:
        users = db.execute(
            select(User).where(User.id.in_(user_ids))
        ).scalars().all()
        user_map = {u.id: u for u in users}

    return [_to_response(r, user_map.get(r.updated_by_id)) for r in rows]


@router.patch("/{category}", response_model=TierRuleResponse)
def update_tier_rule(
    category: EmailCategory,
    payload: TierRuleUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    _: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TierRuleResponse:
    """Update T1 eligibility and/or threshold for one category.

    Body fields are optional; omitting one leaves it unchanged.
    """
    rule = db.execute(
        select(TierRule).where(TierRule.category == category)
    ).scalar_one_or_none()

    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No tier rule for category {category.value}",
        )

    # Hard safety rail: cannot enable T1 for high-risk categories (defense in depth).
    if (
        payload.t1_eligible is True
        and category in T1_LOCKED_CATEGORIES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Category '{category.value}' cannot be enabled for T1 auto-send. "
                "These messages always require staff review."
            ),
        )

    # Capture before-state for audit
    before = {
        "t1_eligible": rule.t1_eligible,
        "t1_min_confidence": rule.t1_min_confidence,
    }

    changed = False
    if payload.t1_eligible is not None and payload.t1_eligible != rule.t1_eligible:
        rule.t1_eligible = payload.t1_eligible
        changed = True
    if (
        payload.t1_min_confidence is not None
        and payload.t1_min_confidence != rule.t1_min_confidence
    ):
        rule.t1_min_confidence = payload.t1_min_confidence
        changed = True

    if not changed:
        return _to_response(rule, current_user)

    rule.updated_at = datetime.now(timezone.utc)
    rule.updated_by_id = current_user.id

    log_action(
        db,
        action="tier_rule.updated",
        entity_type="tier_rule",
        entity_id=str(rule.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "category": category.value,
            "before": before,
            "after": {
                "t1_eligible": rule.t1_eligible,
                "t1_min_confidence": rule.t1_min_confidence,
            },
        },
    )

    db.commit()
    db.refresh(rule)
    return _to_response(rule, current_user)
