"""Runtime-toggleable system settings, backed by the `system_settings` table.

Each setting is a string key → string value. Helpers cast booleans to/from
the canonical lowercase strings ("true" / "false").

This is intentionally a tiny module — no caching layer for V1. Reads are a
single primary-key lookup; the inbox auto-send hot path reads
`auto_send_enabled` once per draft, so DB load is negligible.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)


# Known setting keys (use these constants instead of raw strings to avoid typos).
AUTO_SEND_ENABLED = "auto_send_enabled"
# Firm-level signature block: appended to T1 auto-sent mail (no human sender)
# and used as the fallback for users without a personal signature.
COMPANY_SIGNATURE = "company_signature"
# The retired global signature (pre-018, was `draft_signature` — Jane's
# personal block baked into draft bodies at generation time). Kept ONLY so the
# send path can strip it from old drafts during the transition. Do not edit.
LEGACY_DRAFT_SIGNATURE = "legacy_draft_signature"


def get_setting(db: Session, key: str) -> str | None:
    """Return the raw string value for `key`, or None if the row doesn't exist."""
    row = db.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    ).scalar_one_or_none()
    return row.value if row else None


def get_bool(db: Session, key: str, default: bool = False) -> bool:
    """Return the boolean value for `key`. Anything other than 'true' is False."""
    raw = get_setting(db, key)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def set_setting(
    db: Session,
    key: str,
    value: str,
    *,
    updated_by_id: uuid.UUID | None = None,
) -> SystemSetting:
    """Upsert a setting. Caller is responsible for db.commit()."""
    row = db.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    ).scalar_one_or_none()
    if row is None:
        row = SystemSetting(
            key=key,
            value=value,
            updated_by_id=updated_by_id,
        )
        db.add(row)
    else:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by_id = updated_by_id
    db.flush()
    return row


def set_bool(
    db: Session,
    key: str,
    value: bool,
    *,
    updated_by_id: uuid.UUID | None = None,
) -> SystemSetting:
    return set_setting(
        db, key, "true" if value else "false", updated_by_id=updated_by_id
    )
