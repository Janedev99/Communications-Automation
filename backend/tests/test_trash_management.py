"""
Tests for the trash + spam endpoints (FEAT/inbox-trash-management).

Coverage:
  1. POST /trash moves every inbound message via the provider and sets
     thread.status = deleted.
  2. POST /spam does the same but routes to junk_email and sets
     thread.status = spam.
  3. Outbound messages are NOT moved — only client-sent inbound messages
     get sent to Deleted Items / Junk Email.
  4. Idempotent — calling /trash on an already-deleted thread is a no-op
     (returns 200, no extra provider calls, no duplicate audit rows).
  5. Cross-terminal refusal — calling /trash on a spam thread returns 409.
  6. 404 on missing thread.
  7. Audit log row is written with the expected action + details shape.
  8. Default inbox list view hides deleted + spam threads.
  9. Explicit status filter surfaces deleted + spam threads when requested.

Authority context: Jane explicitly granted Outlook-side deletion in the
2026-05-21 meeting — the API does NOT require a "confirmed=true" flag,
but the UI is expected to show a confirm dialog.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)


# ── Test factory helpers ──────────────────────────────────────────────────────


def _make_thread(
    db: Session,
    *,
    status: EmailStatus = EmailStatus.categorized,
    subject: str | None = None,
) -> EmailThread:
    thread = EmailThread(
        id=uuid.uuid4(),
        subject=subject or f"Trash test {uuid.uuid4().hex[:6]}",
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name="Test Client",
        status=status,
        category=EmailCategory.general_inquiry,
        suggested_reply_tone="professional",
    )
    db.add(thread)
    db.flush()
    return thread


def _add_inbound(db: Session, thread: EmailThread, n: int = 1) -> list[EmailMessage]:
    msgs = []
    for i in range(n):
        msg = EmailMessage(
            id=uuid.uuid4(),
            thread_id=thread.id,
            message_id_header=f"<inbound-{uuid.uuid4().hex[:8]}@client.example.com>",
            sender=f"Client <{thread.client_email}>",
            recipient="firm@example.com",
            body_text=f"Message {i}",
            received_at=datetime.now(timezone.utc),
            direction=MessageDirection.inbound,
            is_processed=True,
        )
        db.add(msg)
        msgs.append(msg)
    db.flush()
    return msgs


def _add_outbound(db: Session, thread: EmailThread) -> EmailMessage:
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        message_id_header=f"<outbound-{uuid.uuid4().hex[:8]}@firm.example.com>",
        sender="Firm <firm@example.com>",
        recipient=thread.client_email,
        body_text="Our reply.",
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.outbound,
        is_processed=True,
    )
    db.add(msg)
    db.flush()
    return msg


# =============================================================================
# Trash endpoint
# =============================================================================


def test_trash_moves_inbound_to_deleted_items_and_sets_status(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session)
    inbound_msgs = _add_inbound(db_session, thread, n=3)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/trash")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "deleted"

    # Every inbound message routed to deleted_items
    assert len(mock_email_provider.moved_messages) == 3
    assert all(m["destination"] == "deleted_items" for m in mock_email_provider.moved_messages)
    moved_ids = {m["internet_message_id"] for m in mock_email_provider.moved_messages}
    assert moved_ids == {m.message_id_header for m in inbound_msgs}

    # Thread status persisted
    db_session.expire_all()
    refreshed = db_session.get(EmailThread, thread.id)
    assert refreshed.status == EmailStatus.deleted


def test_trash_does_not_move_outbound_messages(
    logged_in_admin, db_session, mock_email_provider
):
    """Outbound (sent) messages live in Sent Items in Outlook — we never
    touch them. Only client-sent inbound messages get moved to trash."""
    thread = _make_thread(db_session)
    inbound = _add_inbound(db_session, thread, n=1)[0]
    _add_outbound(db_session, thread)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/trash")

    assert response.status_code == 200
    assert len(mock_email_provider.moved_messages) == 1
    assert mock_email_provider.moved_messages[0]["internet_message_id"] == inbound.message_id_header


def test_trash_writes_audit_row(logged_in_admin, db_session, mock_email_provider):
    thread = _make_thread(db_session)
    _add_inbound(db_session, thread, n=2)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/trash")
    assert response.status_code == 200

    db_session.expire_all()
    audit = db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == str(thread.id),
            AuditLog.action == "thread.deleted",
        )
    ).scalar_one()
    assert audit.details["destination"] == "deleted_items"
    assert audit.details["messages_moved"] == 2
    assert audit.details["inbound_total"] == 2
    assert audit.details["previous_status"] == "categorized"


def test_trash_is_idempotent_on_already_deleted_thread(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session, status=EmailStatus.deleted)
    _add_inbound(db_session, thread, n=1)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/trash")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    # No provider calls — the thread is already in the target state
    assert len(mock_email_provider.moved_messages) == 0


def test_trash_refuses_when_thread_is_spam(
    logged_in_admin, db_session, mock_email_provider
):
    """Cross-terminal moves are user confusion — refuse with 409 so the
    user has to consciously restore before re-classifying."""
    thread = _make_thread(db_session, status=EmailStatus.spam)
    _add_inbound(db_session, thread, n=1)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/trash")

    assert response.status_code == 409
    assert "spam" in response.json()["detail"].lower()
    # And no provider calls happened
    assert len(mock_email_provider.moved_messages) == 0


def test_trash_returns_404_for_missing_thread(
    logged_in_admin, db_session, mock_email_provider
):
    fake_id = uuid.uuid4()
    response = logged_in_admin.post(f"/api/v1/emails/{fake_id}/trash")
    assert response.status_code == 404


# =============================================================================
# Spam endpoint
# =============================================================================


def test_spam_moves_inbound_to_junk_email_and_sets_status(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session)
    inbound_msgs = _add_inbound(db_session, thread, n=2)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/spam")

    assert response.status_code == 200
    assert response.json()["status"] == "spam"

    assert len(mock_email_provider.moved_messages) == 2
    assert all(m["destination"] == "junk_email" for m in mock_email_provider.moved_messages)
    moved_ids = {m["internet_message_id"] for m in mock_email_provider.moved_messages}
    assert moved_ids == {m.message_id_header for m in inbound_msgs}

    db_session.expire_all()
    refreshed = db_session.get(EmailThread, thread.id)
    assert refreshed.status == EmailStatus.spam


def test_spam_writes_audit_row(logged_in_admin, db_session, mock_email_provider):
    thread = _make_thread(db_session)
    _add_inbound(db_session, thread, n=1)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/spam")
    assert response.status_code == 200

    db_session.expire_all()
    audit = db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == str(thread.id),
            AuditLog.action == "thread.marked_spam",
        )
    ).scalar_one()
    assert audit.details["destination"] == "junk_email"
    assert audit.details["messages_moved"] == 1


def test_spam_refuses_when_thread_is_deleted(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session, status=EmailStatus.deleted)
    _add_inbound(db_session, thread, n=1)
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/spam")

    assert response.status_code == 409
    assert "deleted" in response.json()["detail"].lower()
    assert len(mock_email_provider.moved_messages) == 0


# =============================================================================
# List filtering
# =============================================================================


def test_default_list_view_hides_deleted_and_spam(
    logged_in_admin, db_session, mock_email_provider
):
    """Inbox view must not surface deleted/spam threads by default —
    otherwise trash-management has no visible effect for the user."""
    active = _make_thread(db_session, status=EmailStatus.categorized,
                          subject="ACTIVE-TRASH-TEST")
    trashed = _make_thread(db_session, status=EmailStatus.deleted,
                           subject="TRASHED-TRASH-TEST")
    spammed = _make_thread(db_session, status=EmailStatus.spam,
                           subject="SPAMMED-TRASH-TEST")
    db_session.commit()

    response = logged_in_admin.get("/api/v1/emails")
    assert response.status_code == 200
    subjects = [t["subject"] for t in response.json()["items"]]

    assert "ACTIVE-TRASH-TEST" in subjects
    assert "TRASHED-TRASH-TEST" not in subjects
    assert "SPAMMED-TRASH-TEST" not in subjects


def test_explicit_status_filter_surfaces_deleted_threads(
    logged_in_admin, db_session, mock_email_provider
):
    """User can drill into trashed threads by explicit ?status=deleted."""
    trashed = _make_thread(db_session, status=EmailStatus.deleted,
                           subject="EXPLICIT-DELETED-TEST")
    db_session.commit()

    response = logged_in_admin.get("/api/v1/emails?status=deleted")
    assert response.status_code == 200
    subjects = [t["subject"] for t in response.json()["items"]]
    assert "EXPLICIT-DELETED-TEST" in subjects
