"""
Dashboard routes.

GET /dashboard/stats          — high-level counts for the operations dashboard
GET /dashboard/activity       — recent audit log activity feed (last 20 entries)
GET /dashboard/health         — database + service health check (public); T1.13
GET /dashboard/system-status  — shadow mode + poller health + anthropic health; T2.4
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.database import check_db_connection, get_db
from app.models.audit import AuditLog
from app.models.email import DraftResponse, DraftStatus, EmailCategory, EmailStatus, EmailThread, KnowledgeEntry, ThreadTier
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Thresholds for health indicators (T1.13)
_POLLER_HEALTHY_THRESHOLD_MINUTES = 10
_ANTHROPIC_HEALTHY_THRESHOLD_MINUTES = 15

# ── Human-readable action descriptions ────────────────────────────────────────

_ACTION_DESCRIPTIONS: dict[str, str] = {
    "auth.login": "logged in",
    "auth.logout": "logged out",
    "auth.password_changed": "changed their password",
    "email.manually_categorized": "manually re-categorized a thread",
    "draft.manually_triggered": "triggered AI draft generation",
    "draft.generated": "AI generated a draft",
    "draft.updated": "edited a draft",
    "draft.approved": "approved a draft",
    "draft.rejected": "rejected a draft",
    "draft.sent": "sent an email",
    "draft.manual_created": "created a draft from template",
    "escalation.acknowledged": "acknowledged an escalation",
    "escalation.resolved": "resolved an escalation",
    "user.created": "created a new user",
    "user.updated": "updated a user",
    "knowledge.created": "added a knowledge entry",
    "knowledge.updated": "updated a knowledge entry",
    "knowledge.deleted": "deleted a knowledge entry",
}


@router.get("/stats")
def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Return aggregated stats for the dashboard:
      - Thread counts by status
      - Thread counts by category
      - Escalation counts by status and severity
      - Recent activity (last 24h)
    """
    # ── Threads by status ──────────────────────────────────────────────────────
    status_rows = db.execute(
        select(EmailThread.status, func.count(EmailThread.id).label("count"))
        .group_by(EmailThread.status)
    ).all()
    threads_by_status = {row.status.value: row.count for row in status_rows}

    # ── Threads by category ────────────────────────────────────────────────────
    category_rows = db.execute(
        select(EmailThread.category, func.count(EmailThread.id).label("count"))
        .group_by(EmailThread.category)
    ).all()
    threads_by_category = {row.category.value: row.count for row in category_rows}

    # ── Threads by tier (Phase 3) ──────────────────────────────────────────────
    tier_rows = db.execute(
        select(EmailThread.tier, func.count(EmailThread.id).label("count"))
        .group_by(EmailThread.tier)
    ).all()
    threads_by_tier = {row.tier.value: row.count for row in tier_rows}

    # The Escalated lane in the UI matches "tier=t3_escalate OR status=escalated"
    # (the two columns can drift — see comment in api/emails.py:list_threads).
    # Recount t3 to include status-only escalations so the tab badge matches the
    # list it links to.
    t3_combined = db.execute(
        select(func.count(EmailThread.id)).where(
            or_(
                EmailThread.tier == ThreadTier.t3_escalate,
                EmailThread.status == EmailStatus.escalated,
            )
        )
    ).scalar_one()
    threads_by_tier[ThreadTier.t3_escalate.value] = t3_combined

    # ── Escalations by status ──────────────────────────────────────────────────
    esc_status_rows = db.execute(
        select(Escalation.status, func.count(Escalation.id).label("count"))
        .group_by(Escalation.status)
    ).all()
    escalations_by_status = {row.status.value: row.count for row in esc_status_rows}

    # ── Escalations by severity ────────────────────────────────────────────────
    esc_severity_rows = db.execute(
        select(Escalation.severity, func.count(Escalation.id).label("count"))
        .group_by(Escalation.severity)
    ).all()
    escalations_by_severity = {row.severity.value: row.count for row in esc_severity_rows}

    # ── Totals + last-24h counts in a single pass ──────────────────────────────
    # Combine thread total, pending escalations, and 24h activity into fewer queries.
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    thread_summary = db.execute(
        select(
            func.count(EmailThread.id).label("total"),
            func.count(EmailThread.id).filter(EmailThread.created_at >= since).label("last_24h"),
        )
    ).one()
    total_threads = thread_summary.total
    new_threads_24h = thread_summary.last_24h

    esc_summary = db.execute(
        select(
            func.count(Escalation.id).filter(
                Escalation.status == EscalationStatus.pending
            ).label("pending"),
            func.count(Escalation.id).filter(Escalation.created_at >= since).label("last_24h"),
        )
    ).one()
    pending_escalations = esc_summary.pending
    new_escalations_24h = esc_summary.last_24h

    # ── Phase 2: Draft stats ───────────────────────────────────────────────────
    drafts_pending_review = db.execute(
        select(func.count(DraftResponse.id)).where(
            DraftResponse.status.in_([DraftStatus.pending, DraftStatus.edited])
        )
    ).scalar_one()

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    drafts_sent_today = db.execute(
        select(func.count(DraftResponse.id)).where(
            DraftResponse.status == DraftStatus.sent,
            DraftResponse.reviewed_at >= today_start,
        )
    ).scalar_one()

    knowledge_entries_active = db.execute(
        select(func.count(KnowledgeEntry.id)).where(
            KnowledgeEntry.is_active == True  # noqa: E712
        )
    ).scalar_one()

    # ── AI usage this month ────────────────────────────────────────────────────
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    ai_token_rows = db.execute(
        select(
            func.count(DraftResponse.id).label("call_count"),
            func.coalesce(func.sum(DraftResponse.ai_prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(DraftResponse.ai_completion_tokens), 0).label("completion_tokens"),
        ).where(
            DraftResponse.ai_model.isnot(None),
            DraftResponse.created_at >= month_start,
        )
    ).one()
    # Approximate Claude Sonnet pricing: $3/M prompt, $15/M completion
    estimated_cost_usd = (
        (ai_token_rows.prompt_tokens / 1_000_000 * 3.0) +
        (ai_token_rows.completion_tokens / 1_000_000 * 15.0)
    )

    return {
        "totals": {
            "threads": total_threads,
            "pending_escalations": pending_escalations,
        },
        "threads_by_status": threads_by_status,
        "threads_by_category": threads_by_category,
        "threads_by_tier": threads_by_tier,
        "escalations_by_status": escalations_by_status,
        "escalations_by_severity": escalations_by_severity,
        "last_24h": {
            "new_threads": new_threads_24h,
            "new_escalations": new_escalations_24h,
        },
        # Phase 2: response assistance stats
        "drafts": {
            "pending_review": drafts_pending_review,
            "sent_today": drafts_sent_today,
        },
        "knowledge_entries_active": knowledge_entries_active,
        # AI usage for current calendar month
        "ai_usage": {
            "calls_this_month": ai_token_rows.call_count,
            "prompt_tokens": int(ai_token_rows.prompt_tokens),
            "completion_tokens": int(ai_token_rows.completion_tokens),
            "estimated_cost_usd": round(estimated_cost_usd, 4),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/activity")
def get_activity(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Return the most recent audit log entries with human-readable descriptions.
    Used for the dashboard activity feed.
    """
    rows = db.execute(
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).scalars().all()

    result = []
    for entry in rows:
        actor = entry.user.name if entry.user else "System"
        verb = _ACTION_DESCRIPTIONS.get(entry.action, entry.action)
        # Enrich with thread subject from details if available
        subject_hint = ""
        if entry.details and isinstance(entry.details, dict):
            if "thread_id" in entry.details:
                subject_hint = f" (thread {str(entry.details['thread_id'])[:8]}…)"
        description = f"{actor} {verb}{subject_hint}"
        result.append({
            "id": str(entry.id),
            "action": entry.action,
            "description": description,
            "actor": actor,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "created_at": entry.created_at.isoformat(),
        })

    return result


@router.get("/health")
def health_check() -> dict[str, Any]:
    """
    Public health check endpoint. Does not require authentication.

    T1.13: Returns database reachability, poller health, and Anthropic reachability.
      - poller_healthy: True if last_successful_poll_at < 10 min ago
      - anthropic_reachable: True if last successful Anthropic call < 15 min ago
    """
    from app.services.email_intake import last_successful_poll_at, last_successful_anthropic_at

    db_ok = check_db_connection()
    now = datetime.now(timezone.utc)

    poller_healthy: bool
    if last_successful_poll_at is None:
        poller_healthy = False
    else:
        age_minutes = (now - last_successful_poll_at).total_seconds() / 60
        poller_healthy = age_minutes < _POLLER_HEALTHY_THRESHOLD_MINUTES

    anthropic_reachable: bool
    if last_successful_anthropic_at is None:
        # If we've never made an Anthropic call yet, don't flag as unreachable
        # (system may have just started with no emails yet)
        anthropic_reachable = True
    else:
        age_minutes = (now - last_successful_anthropic_at).total_seconds() / 60
        anthropic_reachable = age_minutes < _ANTHROPIC_HEALTHY_THRESHOLD_MINUTES

    overall = db_ok and poller_healthy
    return {
        "status": "ok" if overall else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "poller_healthy": poller_healthy,
        "anthropic_reachable": anthropic_reachable,
        "last_successful_poll_at": last_successful_poll_at.isoformat() if last_successful_poll_at else None,
        "last_successful_anthropic_at": last_successful_anthropic_at.isoformat() if last_successful_anthropic_at else None,
        "timestamp": now.isoformat(),
    }


@router.get("/system-status")
def system_status(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    T2.4: Authenticated system status endpoint.

    Returns:
      - shadow_mode: whether auto-draft generation is disabled
      - last_successful_poll_at: ISO timestamp or null
      - poller_healthy: bool
      - anthropic_reachable: bool
    """
    from app.config import get_settings
    from app.services.email_intake import last_successful_poll_at, last_successful_anthropic_at

    settings = get_settings()
    now = datetime.now(timezone.utc)

    poller_healthy: bool
    if last_successful_poll_at is None:
        poller_healthy = False
    else:
        age_minutes = (now - last_successful_poll_at).total_seconds() / 60
        poller_healthy = age_minutes < _POLLER_HEALTHY_THRESHOLD_MINUTES

    anthropic_reachable: bool
    if last_successful_anthropic_at is None:
        anthropic_reachable = True
    else:
        age_minutes = (now - last_successful_anthropic_at).total_seconds() / 60
        anthropic_reachable = age_minutes < _ANTHROPIC_HEALTHY_THRESHOLD_MINUTES

    return {
        "shadow_mode": settings.shadow_mode,
        "last_successful_poll_at": last_successful_poll_at.isoformat() if last_successful_poll_at else None,
        "poller_healthy": poller_healthy,
        "anthropic_reachable": anthropic_reachable,
        "timestamp": now.isoformat(),
    }
