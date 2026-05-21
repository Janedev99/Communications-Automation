"""
Auto-folder service.

After a successful send (manual approve+send or T1 auto-send), park the
thread in a folder named after the client so the inbox naturally organizes
itself over time. From the 2026-05-21 client meeting:

    Jane (04:27:55): "after I have replied or dealt with it somehow.
    Then after that happens, I'd like it to create the folder and save
    it in that client's folder."

Behaviour:
  - Only fires after a SUCCESSFUL send. Failed sends (send_failed) skip
    the auto-save — the email never reached the recipient, so there's
    no "dealt with it" event to organize around.
  - Idempotent over the existing save state: if the thread is already
    saved (to any folder, including an explicit user-chosen one), the
    helper is a no-op. Never clobbers a user's deliberate choice.
  - Folder name resolves from `thread.client_name` → `thread.client_email`
    → "Unsorted". Real-world client names like "Caroline Apex" or
    "Doug Conquest" land cleanly; bare email-only contacts get grouped
    by their address; mystery senders end up in a single bucket for
    later triage rather than producing nameless folders.
  - Writes an audit row (`thread.auto_saved`) so the action is traceable
    — the user didn't explicitly click Save, so the audit log is the
    only signal that an auto-save happened.

Call sites: ``api/drafts.py`` (manual send) and ``services/auto_send.py``
(T1 auto-send). Both call this helper after setting ``thread.status =
sent`` but before committing the transaction.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.email import EmailThread
from app.utils.audit import log_action

logger = logging.getLogger(__name__)


def _resolve_client_folder_name(thread: EmailThread) -> str:
    """
    Best-effort human-readable folder name for the thread's client.

    Preference order:
      1. ``client_name`` — e.g. "Caroline Apex". Most useful for browsing.
      2. ``client_email`` — fallback when no name was parsed from headers.
         Still groups all emails from one address together.
      3. The literal ``"Unsorted"`` — last-resort bucket so we never
         persist an empty / null folder name. Keeps the saved-threads
         view from acquiring nameless rows.

    Strip-and-check on each candidate so a whitespace-only field doesn't
    win against a real fallback.
    """
    name = (thread.client_name or "").strip()
    if name:
        return name
    email = (thread.client_email or "").strip()
    if email:
        return email
    return "Unsorted"


def auto_save_to_client_folder(
    db: Session,
    *,
    thread: EmailThread,
    actor_id: uuid.UUID | None,
    request_ip: str | None,
) -> bool:
    """
    Save the thread to a client-named folder. Returns True if the save
    actually happened, False if it was skipped (already saved).

    ``actor_id`` should be the user who triggered the send. For T1
    auto-send (no human in the loop), pass ``None`` — the audit row
    will record the action without a user, mirroring how
    ``auto_send.py`` audits ``thread.auto_sent`` with no actor.

    Never raises on a save-related failure: this is a convenience layer
    on top of a successful send, and an error here must not roll back
    the send itself. Errors are logged and swallowed.
    """
    try:
        if thread.is_saved:
            # Respect an existing save — the user (or a prior auto-save)
            # already placed this thread, and we'd rather under-save than
            # silently re-categorize someone's deliberate organisation.
            return False

        folder_name = _resolve_client_folder_name(thread)
        thread.is_saved = True
        thread.saved_folder = folder_name
        thread.saved_at = datetime.now(timezone.utc)
        thread.saved_by_id = actor_id
        thread.updated_at = datetime.now(timezone.utc)

        log_action(
            db,
            action="thread.auto_saved",
            entity_type="email_thread",
            entity_id=str(thread.id),
            user_id=actor_id,
            ip_address=request_ip,
            details={
                "folder": folder_name,
                "trigger": "send",
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001
        # Log + swallow — the send itself already succeeded; we don't
        # want the post-send convenience to corrupt the send transaction.
        logger.warning(
            "auto_save_to_client_folder failed for thread=%s: %s",
            getattr(thread, "id", "?"), exc,
        )
        return False
