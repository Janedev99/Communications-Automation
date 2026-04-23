"""
Tests for the email intake service.

Covers: deduplication, thread matching (In-Reply-To, References), bounce
filtering (sender, subject prefix, delivery status), and graceful handling
of a malformed sender.

All AI calls are mocked — intake tests should never hit Claude.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import make_raw_email


def _unique_id(prefix: str = "msg") -> str:
    """Generate a unique Message-ID for isolation between tests."""
    return f"<{prefix}-{uuid.uuid4()}@example.com>"


# ===========================================================================
# Helpers
# ===========================================================================

def _run_intake(db: Session, raw, *, categorizer_mock=None):
    """
    Run process_single_email with a mocked categorizer so tests don't call Claude.
    Returns thread_id or None (the function's return value).
    """
    from app.services.email_intake import process_single_email

    if categorizer_mock is None:
        from app.models.email import EmailCategory
        from app.schemas.email import CategorizationResult
        default_result = CategorizationResult(
            category=EmailCategory.general_inquiry,
            confidence=0.9,
            escalation_needed=False,
            escalation_reasons=[],
            summary="Test summary.",
            suggested_reply_tone="professional",
        )
        mock_cat = MagicMock()
        mock_cat.categorize.return_value = default_result
    else:
        mock_cat = categorizer_mock

    with patch("app.services.email_intake.get_categorizer", return_value=mock_cat), \
         patch("app.services.email_intake.get_escalation_engine") as mock_esc_factory:
        mock_engine = MagicMock()
        mock_engine.process.return_value = None
        mock_esc_factory.return_value = mock_engine
        return process_single_email(db, raw)


# ===========================================================================
# 1. Deduplication by Message-ID
# ===========================================================================

def test_dedup_by_message_id(db_session: Session):
    """
    Two emails with the same Message-ID must not create duplicate records.
    Second call returns None; only one EmailMessage row exists.
    """
    from app.models.email import EmailMessage

    mid = _unique_id("dedup")
    raw1 = make_raw_email(message_id=mid)
    raw2 = make_raw_email(message_id=mid)  # duplicate

    _run_intake(db_session, raw1)
    result2 = _run_intake(db_session, raw2)

    msgs = db_session.execute(
        select(EmailMessage).where(EmailMessage.message_id_header == mid)
    ).scalars().all()

    assert len(msgs) == 1, "Duplicate message_id must not create a second record"
    assert result2 is None, "Second intake of same message_id should return None"


# ===========================================================================
# 2. Thread matching by In-Reply-To
# ===========================================================================

def test_thread_matching_by_in_reply_to(db_session: Session):
    """
    An inbound reply with In-Reply-To pointing at an existing Message-ID
    must land in the same thread as the original.
    """
    from app.models.email import EmailMessage, EmailThread

    original_id = _unique_id("orig-reply-to")
    reply_id = _unique_id("reply")

    original = make_raw_email(
        message_id=original_id,
        subject="Tax question",
        sender="alice@example.com",
    )
    _run_intake(db_session, original)

    reply = make_raw_email(
        message_id=reply_id,
        subject="Re: Tax question",
        sender="alice@example.com",
        in_reply_to=original_id,
    )
    _run_intake(db_session, reply)

    # Both messages should share the same thread_id
    msgs = db_session.execute(
        select(EmailMessage).where(
            EmailMessage.message_id_header.in_([original_id, reply_id])
        )
    ).scalars().all()
    assert len(msgs) == 2
    assert msgs[0].thread_id == msgs[1].thread_id, "Reply should join the same thread"


# ===========================================================================
# 3. Thread matching by References header
# ===========================================================================

def test_thread_matching_by_references(db_session: Session):
    """
    An inbound message with a References header containing an existing Message-ID
    must be placed into that existing thread.
    """
    from app.models.email import EmailMessage

    root_id = _unique_id("root-refs")
    followup_id = _unique_id("followup")

    original = make_raw_email(message_id=root_id, sender="bob@example.com")
    _run_intake(db_session, original)

    follow_up = make_raw_email(
        message_id=followup_id,
        sender="bob@example.com",
        references=f"{root_id} <some-other@example.com>",
    )
    _run_intake(db_session, follow_up)

    msgs = db_session.execute(
        select(EmailMessage).where(
            EmailMessage.message_id_header.in_([root_id, followup_id])
        )
    ).scalars().all()
    assert len(msgs) == 2
    assert msgs[0].thread_id == msgs[1].thread_id, (
        "References-matched message should join same thread"
    )


# ===========================================================================
# 4. New thread when no headers match
# ===========================================================================

def test_new_thread_when_no_headers_match(db_session: Session):
    """
    Two unrelated emails (no shared headers) must create two separate threads.
    """
    from app.models.email import EmailMessage, EmailThread

    id_a = _unique_id("alpha")
    id_b = _unique_id("beta")

    raw_a = make_raw_email(message_id=id_a, subject="Alpha topic", sender="alice@new.com")
    raw_b = make_raw_email(message_id=id_b, subject="Beta topic", sender="bob@new.com")

    _run_intake(db_session, raw_a)
    _run_intake(db_session, raw_b)

    msgs = db_session.execute(
        select(EmailMessage).where(
            EmailMessage.message_id_header.in_([id_a, id_b])
        )
    ).scalars().all()
    assert len(msgs) == 2
    assert msgs[0].thread_id != msgs[1].thread_id, (
        "Unrelated emails must create separate threads"
    )


# ===========================================================================
# 5. Bounce filter — MAILER-DAEMON sender
# ===========================================================================

def test_bounce_filter_mailer_daemon(db_session: Session):
    """
    Email from MAILER-DAEMON@ is stored but categorizer is NOT called.
    """
    from app.models.email import EmailMessage
    from app.services.email_intake import process_single_email

    mid = _unique_id("bounce-mailer")
    raw = make_raw_email(
        message_id=mid,
        sender="MAILER-DAEMON@example.com",
        subject="Delivery Status",
    )

    mock_cat = MagicMock()
    with patch("app.services.email_intake.get_categorizer", return_value=mock_cat), \
         patch("app.services.email_intake.get_escalation_engine"):
        result = process_single_email(db_session, raw)

    # Stored in DB
    msgs = db_session.execute(
        select(EmailMessage).where(EmailMessage.message_id_header == mid)
    ).scalars().all()
    assert len(msgs) == 1, "Bounce email must be stored in DB"
    mock_cat.categorize.assert_not_called()
    assert result is None


# ===========================================================================
# 6. Bounce filter — subject "Undeliverable:"
# ===========================================================================

def test_bounce_filter_subject_undeliverable(db_session: Session):
    """
    Subject starting with 'Undeliverable:' skips categorization.
    """
    from app.models.email import EmailMessage
    from app.services.email_intake import process_single_email

    mid = _unique_id("bounce-undeliv")
    raw = make_raw_email(
        message_id=mid,
        sender="postmaster@mailserver.com",
        subject="Undeliverable: Your message to client",
    )

    mock_cat = MagicMock()
    with patch("app.services.email_intake.get_categorizer", return_value=mock_cat), \
         patch("app.services.email_intake.get_escalation_engine"):
        result = process_single_email(db_session, raw)

    msgs = db_session.execute(
        select(EmailMessage).where(EmailMessage.message_id_header == mid)
    ).scalars().all()
    assert len(msgs) == 1
    mock_cat.categorize.assert_not_called()
    assert result is None


# ===========================================================================
# 7. Bounce filter — subject "Delivery Status Notification"
# ===========================================================================

def test_bounce_filter_delivery_status(db_session: Session):
    """
    'Delivery Status Notification' subject is treated as bounce and skipped.
    """
    from app.services.email_intake import process_single_email

    mid = _unique_id("bounce-dsn")
    raw = make_raw_email(
        message_id=mid,
        sender="support@mail.example.com",
        subject="Delivery Status Notification",
    )

    mock_cat = MagicMock()
    with patch("app.services.email_intake.get_categorizer", return_value=mock_cat), \
         patch("app.services.email_intake.get_escalation_engine"):
        result = process_single_email(db_session, raw)

    mock_cat.categorize.assert_not_called()
    assert result is None


# ===========================================================================
# 8. Malformed sender tolerated
# ===========================================================================

def test_malformed_sender_tolerated(db_session: Session):
    """
    Empty/missing From header must not crash intake. Thread is still created.
    """
    from app.models.email import EmailMessage

    mid = _unique_id("malformed")
    raw = make_raw_email(
        message_id=mid,
        sender="",
        subject="Weird email",
        body_text="This email has no From header.",
    )

    _run_intake(db_session, raw)

    msgs = db_session.execute(
        select(EmailMessage).where(EmailMessage.message_id_header == mid)
    ).scalars().all()
    assert len(msgs) == 1, "Intake should still create a record for malformed senders"
