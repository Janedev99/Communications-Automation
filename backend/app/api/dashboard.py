"""
Dashboard routes.

GET /dashboard/stats — high-level counts for the operations dashboard
GET /dashboard/health — database + service health check (public)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import check_db_connection, get_db
from app.models.email import DraftResponse, DraftStatus, EmailCategory, EmailStatus, EmailThread, KnowledgeEntry
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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
