"""
Dashboard routes.

GET /dashboard/stats         — high-level counts for the operations dashboard
GET /dashboard/activity      — recent audit log activity feed (last 20 entries)
GET /dashboard/health        — database + service health check (public)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.database import check_db_connection, get_db
from app.models.audit import AuditLog
from app.models.email import DraftResponse, DraftStatus, EmailCategory, EmailStatus, EmailThread, KnowledgeEntry
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

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

    # ── Recent activity (last 24 hours) ────────────────────────────────────────
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    new_threads_24h = db.execute(
        select(func.count(EmailThread.id)).where(EmailThread.created_at >= since)
    ).scalar_one()
    new_escalations_24h = db.execute(
        select(func.count(Escalation.id)).where(Escalation.created_at >= since)
    ).scalar_one()

    # ── Totals ──────────────────────────────────────────────────────────────────
    total_threads = db.execute(select(func.count(EmailThread.id))).scalar_one()
    pending_escalations = db.execute(
        select(func.count(Escalation.id)).where(
            Escalation.status == EscalationStatus.pending
        )
    ).scalar_one()

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
    Returns database reachability and app version.
    """
    db_ok = check_db_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
