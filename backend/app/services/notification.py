"""
Notification service — V1 implementation.

V1 uses structured log output only.  The interface is designed so that
Slack, email, or webhook notifications can be added later without changing
callers.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NotificationService:
    """
    V1 notification service: writes structured JSON lines to stdout and
    optionally to a log file.

    Future versions can add Slack/email channels by overriding or extending
    the `_dispatch` method.
    """

    def __init__(self, log_file: str | None = None) -> None:
        self._log_file_path: Path | None = Path(log_file) if log_file else None
        if self._log_file_path:
            self._log_file_path.parent.mkdir(parents=True, exist_ok=True)

    def _dispatch(self, event_type: str, payload: dict[str, Any]) -> None:
        """Write a notification event to the log."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **payload,
        }
        line = json.dumps(record)
        logger.info("[NOTIFICATION] %s", line)

        if self._log_file_path:
            try:
                with self._log_file_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as exc:
                logger.warning("Could not write to notification log file: %s", exc)

    def notify_escalation(
        self,
        *,
        thread_id: str,
        severity: str,
        reason: str,
        client_email: str,
        subject: str,
    ) -> None:
        """Notify staff that a new escalation has been created."""
        self._dispatch("escalation.created", {
            "thread_id": thread_id,
            "severity": severity,
            "reason": reason,
            "client_email": client_email,
            "subject": subject,
        })
        logger.warning(
            "ESCALATION [%s] — client=%s subject=%r reason=%s",
            severity.upper(), client_email, subject, reason,
        )

    def notify_new_email(
        self,
        *,
        thread_id: str,
        client_email: str,
        subject: str,
        category: str,
    ) -> None:
        """Notify staff that a new inbound email has been received and categorized."""
        self._dispatch("email.received", {
            "thread_id": thread_id,
            "client_email": client_email,
            "subject": subject,
            "category": category,
        })

    def notify_draft_ready(
        self,
        *,
        thread_id: str,
        draft_id: str,
        client_email: str,
    ) -> None:
        """Notify staff that an AI draft is ready for review."""
        self._dispatch("draft.ready", {
            "thread_id": thread_id,
            "draft_id": draft_id,
            "client_email": client_email,
        })

    def notify_auto_sent(
        self,
        *,
        thread_id: str,
        draft_id: str,
        client_email: str,
        subject: str,
        category: str,
        confidence: float | None,
    ) -> None:
        """Audit channel for a T1 auto-send success — fires whenever email leaves the
        system without staff approval. High-visibility logging."""
        self._dispatch("thread.auto_sent", {
            "thread_id": thread_id,
            "draft_id": draft_id,
            "client_email": client_email,
            "subject": subject,
            "category": category,
            "confidence": confidence,
        })
        logger.warning(
            "AUTO-SENT — thread=%s client=%s subject=%r category=%s confidence=%s",
            thread_id, client_email, subject, category, confidence,
        )

    def notify_auto_send_failed(
        self,
        *,
        thread_id: str,
        draft_id: str,
        client_email: str,
        error: str,
    ) -> None:
        """Auto-send attempted but the provider call failed. Staff must follow up."""
        self._dispatch("thread.auto_send_failed", {
            "thread_id": thread_id,
            "draft_id": draft_id,
            "client_email": client_email,
            "error": error,
        })
        logger.error(
            "AUTO-SEND FAILED — thread=%s client=%s error=%s",
            thread_id, client_email, error,
        )


_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    global _service
    if _service is None:
        from app.config import get_settings
        settings = get_settings()
        _service = NotificationService(log_file=settings.notify_log_file or None)
    return _service
