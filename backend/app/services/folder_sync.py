"""Reflect in-app thread filing into the real Outlook mailbox (iteration B).

Feature-flagged (OUTLOOK_FOLDER_SYNC, default off). On the existing filing
triggers, create a client folder under Inbox and move the thread's INBOUND
messages into it. Never raises — a filing sync must not break the send/save
that triggered it. Never deletes anything.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email import EmailThread, MessageDirection
from app.services.email_provider import get_email_provider
from app.utils.audit import log_action

logger = logging.getLogger(__name__)


def sync_thread_to_outlook_folder(
    db: Session,
    *,
    thread: EmailThread,
    folder_name: str | None,
    actor_id: uuid.UUID | None = None,
    request_ip: str | None = None,
) -> None:
    """Create the client folder under Inbox (if needed) and move the thread's
    inbound messages into it. No-op unless the flag is on and the provider is
    MSGraph. Logs and swallows all failures."""
    settings = get_settings()
    if not settings.outlook_folder_sync:
        return
    if settings.email_provider.lower() != "msgraph":
        return
    name = (folder_name or "").strip()
    if not name:
        return

    try:
        provider = get_email_provider()
        folder_id = provider.find_or_create_folder(name)
        if not folder_id:
            return
        moved = 0
        for msg in thread.messages:
            if msg.direction == MessageDirection.inbound and msg.message_id_header:
                provider.move_message_to_folder(msg.message_id_header, folder_id)
                moved += 1
        log_action(
            db,
            action="thread.outlook_folder_synced",
            entity_type="email_thread",
            entity_id=str(thread.id),
            user_id=actor_id,
            ip_address=request_ip,
            details={"folder": name, "moved": moved},
        )
    except Exception as exc:  # noqa: BLE001 — never break the triggering send/save
        logger.warning(
            "outlook folder sync failed for thread=%s folder=%r: %s",
            getattr(thread, "id", "?"), name, exc,
        )
