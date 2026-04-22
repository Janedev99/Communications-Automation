"""
Tests for the draft send workflow.

Covers:
  - Idempotency key and send_attempts are written (flushed) before provider call
  - Provider error triggers rollback — draft status reverts to approved
  - Already-sent draft returns success without calling provider again
  - References header is built from parent's References + parent Message-ID
  - Concurrent send: only one provider call occurs (idempotency protection)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from tests.conftest import make_raw_email


def _uid(prefix: str = "msg") -> str:
    return f"<{prefix}-{uuid.uuid4()}@test.local>"


# ===========================================================================
# Helpers
# ===========================================================================

def _seed_thread_with_draft(
    *,
    subject: str = "Tax question",
    sender_email: str = "client@example.com",
    draft_body: str = "Dear client, here is your answer.",
    inbound_references: str | None = None,
):
    """
    Create a thread + inbound message + approved draft in a dedicated session.
    Each call generates unique Message-IDs, so tests don't collide.
    Returns (thread_id, draft_id, inbound_message_id) as strings.
    """
    from app.database import SessionLocal
    from app.models.email import (
        DraftResponse, DraftStatus, EmailCategory,
        EmailMessage, EmailStatus, EmailThread, MessageDirection,
    )
    import app.database as _db_mod

    inbound_mid = _uid("inbound")

    db = _db_mod.SessionLocal()
    try:
        thread = EmailThread(
            subject=subject,
            client_email=sender_email,
            status=EmailStatus.categorized,
            category=EmailCategory.general_inquiry,
        )
        db.add(thread)
        db.flush()

        raw_headers: dict = {}
        if inbound_references:
            raw_headers["References"] = inbound_references

        msg = EmailMessage(
            thread_id=thread.id,
            message_id_header=inbound_mid,
            sender=sender_email,
            recipient="firm@example.com",
            body_text="Client question.",
            received_at=datetime.now(timezone.utc),
            direction=MessageDirection.inbound,
            is_processed=True,
            raw_headers=raw_headers,
        )
        db.add(msg)
        db.flush()

        draft = DraftResponse(
            thread_id=thread.id,
            body_text=draft_body,
            status=DraftStatus.approved,
            send_attempts=0,
        )
        db.add(draft)
        db.commit()

        return str(thread.id), str(draft.id), inbound_mid
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ===========================================================================
# 1. Idempotency key and send_attempts written before provider call
# ===========================================================================

def test_send_persists_idempotency_key_before_provider_call(
    logged_in_admin,
    mock_email_provider,
):
    """
    The send endpoint must write send_idempotency_key and increment
    send_attempts (via db.flush) BEFORE calling the email provider.
    """
    import app.database as _db_mod
    from app.models.email import DraftResponse as DR
    from sqlalchemy import select

    thread_id, draft_id, _ = _seed_thread_with_draft()

    captured = {}
    original_send = mock_email_provider.send_email

    def capturing_send(**kwargs):
        db = _db_mod.SessionLocal()
        try:
            d = db.execute(select(DR).where(DR.id == uuid.UUID(draft_id))).scalar_one()
            captured["send_attempts"] = d.send_attempts
            captured["idempotency_key"] = d.send_idempotency_key
        finally:
            db.close()
        return original_send(**kwargs)

    mock_email_provider.send_email = capturing_send

    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 200

    assert captured.get("send_attempts") == 1, (
        "send_attempts must be 1 when provider is called"
    )
    assert captured.get("idempotency_key") is not None, (
        "send_idempotency_key must be set before provider is called"
    )


# ===========================================================================
# 2. Provider error rolls back send status
# ===========================================================================

def test_provider_error_rolls_back_send_status(
    logged_in_admin,
    mock_email_provider,
):
    """
    Provider exception → HTTP 502. Draft status reverts to 'approved'
    because the entire transaction rolls back.
    """
    import app.database as _db_mod
    from app.models.email import DraftResponse, DraftStatus
    from sqlalchemy import select

    thread_id, draft_id, _ = _seed_thread_with_draft()
    mock_email_provider.raise_on_send = RuntimeError("SMTP refused")

    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 502

    db = _db_mod.SessionLocal()
    try:
        d = db.execute(
            select(DraftResponse).where(DraftResponse.id == uuid.UUID(draft_id))
        ).scalar_one()
        assert d.status == DraftStatus.approved, (
            "Provider failure must roll back draft status to approved"
        )
    finally:
        db.close()


# ===========================================================================
# 3. Retry on already-sent draft is a no-op
# ===========================================================================

def test_retry_with_already_sent_draft_is_noop(
    logged_in_admin,
    mock_email_provider,
):
    """
    Second POST /send on an already-sent draft returns 200 without calling
    the provider again.
    """
    thread_id, draft_id, _ = _seed_thread_with_draft()

    resp1 = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp1.status_code == 200

    calls_after_first = len(mock_email_provider.sent_emails)

    resp2 = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp2.status_code == 200

    calls_after_second = len(mock_email_provider.sent_emails)
    assert calls_after_second == calls_after_first, (
        "Provider must not be called again for already-sent draft"
    )
    assert resp2.json()["status"] == "sent"


# ===========================================================================
# 4. Concurrent send: only one provider call
# ===========================================================================

def test_concurrent_send_prevented(
    logged_in_admin,
    mock_email_provider,
):
    """
    Two sequential /send calls on the same draft result in only ONE provider
    call. On SQLite, SELECT FOR UPDATE is a no-op — idempotency (early return
    when status == 'sent') is the observable protection.
    """
    thread_id, draft_id, _ = _seed_thread_with_draft()

    resp1 = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    resp2 = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(mock_email_provider.sent_emails) == 1, (
        "Email provider must be called exactly once"
    )


# ===========================================================================
# 5. References header preserves thread chain
# ===========================================================================

def test_references_header_preserves_chain(
    logged_in_admin,
    mock_email_provider,
):
    """
    When the inbound message has a References header, the outbound reply must
    build References = parent.References + " " + parent.Message-ID (T2.1).
    """
    parent_refs = "<root@example.com>"

    thread_id, draft_id, inbound_mid = _seed_thread_with_draft(
        inbound_references=parent_refs,
    )

    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 200, resp.text

    assert len(mock_email_provider.sent_emails) == 1
    sent = mock_email_provider.sent_emails[0]

    expected_refs = f"{parent_refs} {inbound_mid}"
    assert sent["references_header"] == expected_refs, (
        f"References header should be '{expected_refs}', got {sent['references_header']!r}"
    )
    assert sent["reply_to_message_id"] == inbound_mid
