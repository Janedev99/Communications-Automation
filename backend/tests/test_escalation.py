"""
Tests for the escalation engine.

Covers:
  - Severity mapping from AI escalation reasons
  - No duplicate escalation created for the same thread
  - Notification service is called once on escalation creation
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import make_raw_email


def _uid(prefix: str = "msg") -> str:
    return f"<{prefix}-{uuid.uuid4()}@example.com>"


def _make_thread(db, *, subject: str = "Test"):
    """Create and flush a bare EmailThread for escalation tests."""
    from app.models.email import EmailCategory, EmailStatus, EmailThread
    thread = EmailThread(
        subject=subject,
        client_email=f"client-{uuid.uuid4()}@example.com",
        status=EmailStatus.categorized,
        category=EmailCategory.general_inquiry,
    )
    db.add(thread)
    db.flush()
    return thread


def _make_result(
    *,
    escalation_needed: bool = True,
    reasons: list[str] | None = None,
    severity_hint: str | None = None,
):
    """Build a CategorizationResult for escalation tests."""
    from app.models.email import EmailCategory
    from app.schemas.email import CategorizationResult

    if reasons is None:
        reasons = ["General escalation reason"]
    return CategorizationResult(
        category=EmailCategory.general_inquiry,
        confidence=0.9,
        escalation_needed=escalation_needed,
        escalation_reasons=reasons,
        summary="Test email.",
        suggested_reply_tone="professional",
    )


# ===========================================================================
# 1. Severity mapping from AI escalation reasons
# ===========================================================================

def test_severity_mapping_from_ai(db_session: Session):
    """
    When Claude returns reasons containing 'irs audit', the escalation engine
    must create an escalation record with severity=critical.
    """
    from app.models.escalation import Escalation, EscalationSeverity
    from app.services.escalation import EscalationEngine

    thread = _make_thread(db_session, subject="IRS Audit Notice")
    result = _make_result(
        reasons=["IRS audit notice mentioned in email; immediate attention required"],
        escalation_needed=True,
    )

    engine = EscalationEngine()

    with patch("app.services.escalation.get_notification_service") as mock_notif_factory:
        mock_notif = MagicMock()
        mock_notif_factory.return_value = mock_notif
        escalation = engine.process(db_session, thread, result)

    assert escalation is not None
    assert escalation.severity == EscalationSeverity.critical, (
        f"Expected critical severity for IRS audit reason, got {escalation.severity}"
    )


def test_severity_high_for_liability_reason(db_session: Session):
    """
    Escalation reasons containing 'liability' or 'financial risk' must
    map to high severity.
    """
    from app.models.escalation import Escalation, EscalationSeverity
    from app.services.escalation import EscalationEngine

    thread = _make_thread(db_session, subject="Liability question")
    result = _make_result(
        reasons=["Client raising financial risk concerns about tax liability"],
    )

    engine = EscalationEngine()
    with patch("app.services.escalation.get_notification_service") as mock_notif_factory:
        mock_notif_factory.return_value = MagicMock()
        escalation = engine.process(db_session, thread, result)

    assert escalation is not None
    assert escalation.severity == EscalationSeverity.high


# ===========================================================================
# 2. No duplicate escalation for the same thread
# ===========================================================================

def test_no_duplicate_escalation_for_same_thread(db_session: Session):
    """
    Two escalation attempts on the same thread (e.g. two pollings) must not
    create two escalation records. The second call returns the existing one.
    """
    from app.models.escalation import Escalation
    from app.services.escalation import EscalationEngine

    thread = _make_thread(db_session, subject="Duplicate escalation test")
    result = _make_result(reasons=["Fraud mentioned in email"])

    engine = EscalationEngine()

    with patch("app.services.escalation.get_notification_service") as mock_notif_factory:
        mock_notif = MagicMock()
        mock_notif_factory.return_value = mock_notif

        esc1 = engine.process(db_session, thread, result)
        esc2 = engine.process(db_session, thread, result)

    # Only one escalation record in DB for this thread
    escalations = db_session.execute(
        select(Escalation).where(Escalation.thread_id == thread.id)
    ).scalars().all()
    assert len(escalations) == 1, (
        "Two escalation calls on same thread must produce only one record"
    )
    assert esc1.id == esc2.id, (
        "Second escalation process call must return the existing escalation"
    )


# ===========================================================================
# 3. Notification fires on escalation creation
# ===========================================================================

def test_notification_fires_on_escalation_create(db_session: Session):
    """
    When an escalation is created, notify_escalation must be called exactly once
    on the notification service.
    """
    from app.services.escalation import EscalationEngine

    thread = _make_thread(db_session, subject="Penalty notice received")
    result = _make_result(reasons=["Penalty assessed by IRS"])

    engine = EscalationEngine()

    with patch("app.services.escalation.get_notification_service") as mock_notif_factory:
        mock_notif = MagicMock()
        mock_notif_factory.return_value = mock_notif
        escalation = engine.process(db_session, thread, result)

    assert escalation is not None
    mock_notif.notify_escalation.assert_called_once()

    # Verify the notification received the right thread_id
    call_kwargs = mock_notif.notify_escalation.call_args.kwargs
    assert call_kwargs["thread_id"] == str(thread.id)
