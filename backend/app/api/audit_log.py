"""
Audit log viewer — admin-only.

GET /audit-log            — paginated, filterable list of audit entries
GET /audit-log/actions    — distinct action names (for filter dropdown)
GET /audit-log/entities   — distinct entity_types (for filter dropdown)

Records are immutable; this is a read-only API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.database import get_db
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


def _entry_to_dict(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "details": entry.details,
        "user_id": str(entry.user_id) if entry.user_id else None,
        "user_name": entry.user.name if entry.user else None,
        "user_email": entry.user.email if entry.user else None,
        "ip_address": entry.ip_address,
        "created_at": entry.created_at.isoformat(),
    }


@router.get("")
def list_audit_log(
    action: str | None = Query(default=None, description="Filter by exact action name"),
    entity_type: str | None = Query(default=None),
    user_id: str | None = Query(
        default=None,
        description="UUID of acting user, or 'system' for non-user actions",
    ),
    since: str | None = Query(
        default=None,
        description="ISO 8601 datetime — return entries on/after this timestamp",
    ),
    until: str | None = Query(
        default=None,
        description="ISO 8601 datetime — return entries before this timestamp",
    ),
    q: str | None = Query(
        default=None,
        description="Free-text search across action, entity_id, and details (JSON text)",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(AuditLog).options(joinedload(AuditLog.user))

    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if user_id:
        if user_id == "system":
            query = query.where(AuditLog.user_id.is_(None))
        else:
            try:
                uid = uuid.UUID(user_id)
                query = query.where(AuditLog.user_id == uid)
            except ValueError:
                # Invalid UUID — return empty result rather than 422 to keep filter UX smooth
                query = query.where(AuditLog.id == uuid.UUID(int=0))
    if since:
        try:
            dt = datetime.fromisoformat(since)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            query = query.where(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if until:
        try:
            dt = datetime.fromisoformat(until)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            query = query.where(AuditLog.created_at < dt)
        except ValueError:
            pass
    if q:
        # Escape SQL LIKE wildcards so a user typing '%' or '_' doesn't get
        # spurious matches — same approach as emails.py:list_threads.
        safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{safe_q}%"
        # JSON cast → text for substring search; cheap on the small audit table.
        # NOTE: this is O(n) — for production scale (>100k rows) migrate
        # `details` to JSONB and add a GIN index, or require a date filter
        # alongside `q` to keep the scan bounded.
        query = query.where(
            or_(
                AuditLog.action.ilike(term, escape="\\"),
                AuditLog.entity_id.ilike(term, escape="\\"),
                cast(AuditLog.details, Text).ilike(term, escape="\\"),
            )
        )

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    offset = (page - 1) * page_size
    rows = db.execute(
        query.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).scalars().all()

    return {
        "items": [_entry_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/actions")
def list_actions(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[str]:
    """Distinct action names — used by the filter dropdown."""
    rows = db.execute(
        select(AuditLog.action).distinct().order_by(AuditLog.action)
    ).scalars().all()
    return list(rows)


@router.get("/entities")
def list_entity_types(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[str]:
    """Distinct entity_type values — used by the filter dropdown."""
    rows = db.execute(
        select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)
    ).scalars().all()
    return list(rows)
