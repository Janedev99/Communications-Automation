"""
Audit logging utility.

`log_action()` is the single function all state-changing code should call.
It writes a record to the `audit_log` table, attached to the current DB session.
The caller's `db.commit()` persists it atomically with the business transaction.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log_action(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """
    Write an audit log entry and add it to the session.

    The entry is flushed immediately so it has an ID, but it is NOT committed.
    The commit happens as part of the caller's transaction, ensuring the audit
    record and the business change land atomically.

    Parameters
    ----------
    db:          Active SQLAlchemy session.
    action:      Dot-namespaced action string, e.g. "email.categorized".
    entity_type: The model/resource type, e.g. "email_thread".
    entity_id:   The ID of the affected record (string form).
    details:     Arbitrary JSON-serialisable dict with before/after state, etc.
    user_id:     UUID of the acting user; None for system/automated actions.
    ip_address:  IP address of the request origin.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry
