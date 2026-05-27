"""
Tests for bulk delete / spam / save via POST /emails/bulk
(FEAT/bulk-trash-actions).

The single-thread trash/spam paths are covered in test_trash_management.py;
here we verify the bulk loop reuses the same mover (_perform_terminal_move),
routes to the right Outlook folder, and aggregates per-thread succeeded/failed
counts instead of aborting the whole batch on one bad thread.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)


def _make_thread(db, *, status=EmailStatus.categorized, subject=None):
    thread = EmailThread(
        id=uuid.uuid4(),
        subject=subject or f"Bulk test {uuid.uuid4().hex[:6]}",
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name="Test Client",
        status=status,
        category=EmailCategory.general_inquiry,
        suggested_reply_tone="professional",
    )
    db.add(thread)
    db.flush()
    return thread


def _add_inbound(db, thread, n=1):
    for i in range(n):
        db.add(
            EmailMessage(
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
        )
    db.flush()


def test_bulk_delete_moves_inbound_and_sets_status(
    logged_in_admin, db_session, mock_email_provider
):
    t1 = _make_thread(db_session)
    t2 = _make_thread(db_session)
    _add_inbound(db_session, t1, n=2)
    _add_inbound(db_session, t2, n=1)
    db_session.commit()

    resp = logged_in_admin.post(
        "/api/v1/emails/bulk",
        json={"thread_ids": [str(t1.id), str(t2.id)], "action": "delete"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0

    assert len(mock_email_provider.moved_messages) == 3
    assert all(m["destination"] == "deleted_items" for m in mock_email_provider.moved_messages)

    db_session.expire_all()
    assert db_session.get(EmailThread, t1.id).status == EmailStatus.deleted
    assert db_session.get(EmailThread, t2.id).status == EmailStatus.deleted


def test_bulk_spam_routes_to_junk(logged_in_admin, db_session, mock_email_provider):
    t1 = _make_thread(db_session)
    _add_inbound(db_session, t1, n=1)
    db_session.commit()

    resp = logged_in_admin.post(
        "/api/v1/emails/bulk",
        json={"thread_ids": [str(t1.id)], "action": "spam"},
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 1
    assert all(m["destination"] == "junk_email" for m in mock_email_provider.moved_messages)
    db_session.expire_all()
    assert db_session.get(EmailThread, t1.id).status == EmailStatus.spam


def test_bulk_save_sets_saved_with_folder(
    logged_in_admin, db_session, mock_email_provider
):
    t1 = _make_thread(db_session)
    t2 = _make_thread(db_session)
    db_session.commit()

    resp = logged_in_admin.post(
        "/api/v1/emails/bulk",
        json={
            "thread_ids": [str(t1.id), str(t2.id)],
            "action": "save",
            "params": {"folder": "Q3 Clients"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 2
    # A save never touches Outlook.
    assert len(mock_email_provider.moved_messages) == 0

    db_session.expire_all()
    for tid in (t1.id, t2.id):
        refreshed = db_session.get(EmailThread, tid)
        assert refreshed.is_saved is True
        assert refreshed.saved_folder == "Q3 Clients"


def test_bulk_delete_refuses_cross_terminal_and_continues(
    logged_in_admin, db_session, mock_email_provider
):
    """A thread already in spam can't be bulk-deleted — it's counted as failed
    while the rest of the batch still succeeds."""
    spammed = _make_thread(db_session, status=EmailStatus.spam)
    active = _make_thread(db_session, status=EmailStatus.categorized)
    _add_inbound(db_session, spammed, n=1)
    _add_inbound(db_session, active, n=1)
    db_session.commit()

    resp = logged_in_admin.post(
        "/api/v1/emails/bulk",
        json={"thread_ids": [str(spammed.id), str(active.id)], "action": "delete"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert any("restore before re-classifying" in e for e in body["errors"])

    db_session.expire_all()
    assert db_session.get(EmailThread, spammed.id).status == EmailStatus.spam  # untouched
    assert db_session.get(EmailThread, active.id).status == EmailStatus.deleted
