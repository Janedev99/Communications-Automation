"""
Analytics routes — read-only aggregates for the /analytics page.

GET /analytics?days=N — token usage (vs the daily AI budget), email volume,
draft workflow funnel, and escalation trends over the last N days.

Visible to ALL staff (get_current_user, not require_admin): nothing here is
sensitive, and staff seeing the token budget helps them self-regulate
regenerate usage. Every aggregate is computed on demand — no new tables, no
denormalized counters to drift.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.ai_budget import AIBudgetUsage
from app.models.email import DraftResponse, EmailThread
from app.models.escalation import Escalation, EscalationStatus
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsResponse,
    DailyCount,
    DailyTokens,
    DraftWorkflowSection,
    EmailVolumeSection,
    EscalationsSection,
    TokenUsageSection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates — used to zero-fill series so charts never gap."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _zero_filled_counts(
    db: Session, *, model, dt_column, start: date, end: date
) -> list[DailyCount]:
    """Per-day row counts for `model` grouped on date(dt_column), zero-filled."""
    rows = db.execute(
        select(func.date(dt_column), func.count(model.id))
        .where(func.date(dt_column) >= start.isoformat())
        .group_by(func.date(dt_column))
    ).all()
    # func.date returns `date` on Postgres but a string on SQLite — normalize.
    counts = {
        (d if isinstance(d, date) else date.fromisoformat(str(d))): c
        for d, c in rows
    }
    return [DailyCount(date=d, count=counts.get(d, 0)) for d in _date_range(start, end)]


@router.get("", response_model=AnalyticsResponse)
def get_analytics(
    days: int = Query(default=30, ge=7, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsResponse:
    """Aggregated metrics over the trailing `days` window (today inclusive)."""
    settings = get_settings()
    today = date.today()
    start = today - timedelta(days=days - 1)

    # ── Token usage ───────────────────────────────────────────────────────────
    usage_rows = db.execute(
        select(AIBudgetUsage).where(AIBudgetUsage.date >= start)
    ).scalars().all()
    usage_by_date = {u.date: u for u in usage_rows}
    daily_tokens = [
        DailyTokens(
            date=d,
            input_tokens=usage_by_date[d].input_tokens if d in usage_by_date else 0,
            output_tokens=usage_by_date[d].output_tokens if d in usage_by_date else 0,
        )
        for d in _date_range(start, today)
    ]
    today_usage = usage_by_date.get(today)
    budget = settings.daily_token_budget
    exhausted = (
        sum(
            1 for t in daily_tokens
            if (t.input_tokens + t.output_tokens) >= budget
        )
        if budget > 0 else 0
    )
    token_usage = TokenUsageSection(
        daily=daily_tokens,
        today_input_tokens=today_usage.input_tokens if today_usage else 0,
        today_output_tokens=today_usage.output_tokens if today_usage else 0,
        daily_budget=budget,
        budget_exhausted_days=exhausted,
    )

    # ── Email volume ──────────────────────────────────────────────────────────
    threads_per_day = _zero_filled_counts(
        db, model=EmailThread, dt_column=EmailThread.created_at, start=start, end=today
    )
    by_category = {
        cat.value: count
        for cat, count in db.execute(
            select(EmailThread.category, func.count(EmailThread.id))
            .where(func.date(EmailThread.created_at) >= start.isoformat())
            .group_by(EmailThread.category)
        ).all()
    }
    by_tier = {
        tier.value: count
        for tier, count in db.execute(
            select(EmailThread.tier, func.count(EmailThread.id))
            .where(func.date(EmailThread.created_at) >= start.isoformat())
            .group_by(EmailThread.tier)
        ).all()
    }
    email_volume = EmailVolumeSection(
        threads_per_day=threads_per_day,
        by_category=by_category,
        by_tier=by_tier,
        total_threads=sum(d.count for d in threads_per_day),
    )

    # ── Draft workflow ────────────────────────────────────────────────────────
    draft_window = func.date(DraftResponse.created_at) >= start.isoformat()
    by_status = {
        status.value: count
        for status, count in db.execute(
            select(DraftResponse.status, func.count(DraftResponse.id))
            .where(draft_window)
            .group_by(DraftResponse.status)
        ).all()
    }
    edited_count = db.execute(
        select(func.count(DraftResponse.id)).where(
            draft_window,
            DraftResponse.original_body_text.is_not(None),
            DraftResponse.original_body_text != DraftResponse.body_text,
        )
    ).scalar_one()
    draft_workflow = DraftWorkflowSection(
        by_status=by_status,
        total=sum(by_status.values()),
        edited_count=edited_count,
        sent_count=by_status.get("sent", 0),
        rejected_count=by_status.get("rejected", 0),
    )

    # ── Escalations ───────────────────────────────────────────────────────────
    created_per_day = _zero_filled_counts(
        db, model=Escalation, dt_column=Escalation.created_at, start=start, end=today
    )
    esc_window = func.date(Escalation.created_at) >= start.isoformat()
    esc_by_severity = {
        sev.value: count
        for sev, count in db.execute(
            select(Escalation.severity, func.count(Escalation.id))
            .where(esc_window)
            .group_by(Escalation.severity)
        ).all()
    }
    esc_by_status = {
        st.value: count
        for st, count in db.execute(
            select(Escalation.status, func.count(Escalation.id))
            .where(esc_window)
            .group_by(Escalation.status)
        ).all()
    }
    # Open = needs attention NOW — deliberately all-time, not windowed.
    open_count = db.execute(
        select(func.count(Escalation.id)).where(
            Escalation.status.in_(
                [EscalationStatus.pending, EscalationStatus.acknowledged]
            )
        )
    ).scalar_one()
    escalations = EscalationsSection(
        created_per_day=created_per_day,
        by_severity=esc_by_severity,
        by_status=esc_by_status,
        open_count=open_count,
    )

    return AnalyticsResponse(
        days=days,
        start_date=start,
        token_usage=token_usage,
        email_volume=email_volume,
        draft_workflow=draft_workflow,
        escalations=escalations,
    )
