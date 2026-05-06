"""
Escalation engine.

Reads categorization output, applies severity rules, creates Escalation
records, and triggers notifications.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import EmailStatus, EmailThread
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.models.user import User, UserRole
from app.schemas.email import CategorizationResult
from app.services.notification import get_notification_service

logger = logging.getLogger(__name__)


# ── Severity rules ─────────────────────────────────────────────────────────────
# Maps keywords found in escalation_reasons → severity level.
# The highest matching severity wins.

_CRITICAL_KEYWORDS = [
    "irs audit", "examination", "lawsuit", "attorney",
    "penalty", "fraud", "criminal", "tax evasion",
]
_HIGH_KEYWORDS = [
    "liability", "financial risk", "regulatory", "compliance",
    "refund demand", "pricing dispute", "fee disagreement",
    "formal complaint", "dissatisfaction",
]
_MEDIUM_KEYWORDS = [
    "new client", "onboarding", "scope",
    # PII detector emits "sensitive client data detected" — surface it as
    # medium so it's distinguishable from low-severity miscellany but not
    # confused with critical legal-risk threads.
    "sensitive client data",
]


def _determine_severity(reasons: list[str]) -> EscalationSeverity:
    combined = " ".join(reasons).lower()
    for keyword in _CRITICAL_KEYWORDS:
        if keyword in combined:
            return EscalationSeverity.critical
    for keyword in _HIGH_KEYWORDS:
        if keyword in combined:
            return EscalationSeverity.high
    for keyword in _MEDIUM_KEYWORDS:
        if keyword in combined:
            return EscalationSeverity.medium
    return EscalationSeverity.low


def _find_admin_user(db: Session) -> User | None:
    """Find Jane (the admin) to auto-assign escalations."""
    return db.execute(
        select(User).where(
            User.role == UserRole.admin,
            User.is_active == True,  # noqa: E712
        )
    ).scalars().first()


class EscalationEngine:
    """Processes categorization results and creates escalation records."""

    def process(
        self,
        db: Session,
        thread: EmailThread,
        result: CategorizationResult,
    ) -> Escalation | None:
        """
        Given a categorization result, create an Escalation if warranted.

        Returns the created Escalation or None if no escalation was needed.
        """
        if not result.escalation_needed:
            return None

        # Check if an open escalation already exists for this thread
        existing = db.execute(
            select(Escalation).where(
                Escalation.thread_id == thread.id,
                Escalation.status != EscalationStatus.resolved,
            )
        ).scalars().first()

        if existing is not None:
            logger.info(
                "Escalation already exists for thread %s (id=%s), skipping creation",
                thread.id, existing.id,
            )
            return existing

        severity = _determine_severity(result.escalation_reasons)
        reason = "; ".join(result.escalation_reasons) or "AI flagged for escalation"
        admin = _find_admin_user(db)

        escalation = Escalation(
            thread_id=thread.id,
            reason=reason,
            severity=severity,
            status=EscalationStatus.pending,
            assigned_to_id=admin.id if admin else None,
        )
        db.add(escalation)

        # Update thread status to escalated
        thread.status = EmailStatus.escalated
        thread.updated_at = datetime.now(timezone.utc)

        db.flush()

        logger.warning(
            "ESCALATION created: thread=%s severity=%s reason=%r",
            thread.id, severity, reason,
        )

        # Fire notification (non-blocking; logs on failure)
        try:
            notifier = get_notification_service()
            notifier.notify_escalation(
                thread_id=str(thread.id),
                severity=severity.value,
                reason=reason,
                client_email=thread.client_email,
                subject=thread.subject,
            )
        except Exception as exc:
            logger.error("Failed to send escalation notification: %s", exc)

        return escalation


_engine: EscalationEngine | None = None


def get_escalation_engine() -> EscalationEngine:
    global _engine
    if _engine is None:
        _engine = EscalationEngine()
    return _engine
