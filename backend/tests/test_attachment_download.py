"""
Tests for the attachment download endpoint.

Endpoint: GET /api/v1/emails/{thread_id}/messages/{message_id}/attachments/{index}/download

Streams an attachment binary from the email provider (MS Graph). Verifies:
  - Auth required (no anonymous downloads of client documents)
  - Thread / message membership enforced (you can't pivot via thread_id+message_id)
  - Attachment index bounds enforced
  - Persisted attachment_id path (new poll data) uses it directly
  - Index fallback works for legacy rows (no attachment_id stored)
  - Provider errors map to clean HTTP statuses (404 / 409 / 501)
  - Audit log entry written for every successful download
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.audit import AuditLog
from app.models.email import (
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)
from sqlalchemy import select


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_thread_with_message(db_session, *, attachments: list[dict]) -> tuple[EmailThread, EmailMessage]:
    """Insert a thread + a single inbound message with attachments metadata.

    Uses a per-call uuid in message_id_header so tests don't collide on the
    UNIQUE constraint (conftest's in-memory DB persists rows across tests).
    """
    unique = uuid.uuid4().hex
    thread = EmailThread(
        id=uuid.uuid4(),
        subject="Test thread",
        client_email=f"client-{unique}@example.com",
        status=EmailStatus.categorized,
    )
    db_session.add(thread)
    db_session.flush()
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        message_id_header=f"<test-graph-msg-{unique}@example.com>",
        sender="Client <client@example.com>",
        recipient="jane@schilcpa.com",
        body_text="Please find attached.",
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.inbound,
        is_processed=True,
        attachments=attachments,
    )
    db_session.add(msg)
    db_session.commit()
    return thread, msg


# ── 1. Auth required ──────────────────────────────────────────────────────────

def test_download_requires_authentication(client, db_session):
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "doc.pdf", "size": 100, "content_type": "application/pdf", "attachment_id": "att-1"}],
    )
    resp = client.get(
        f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
    )
    assert resp.status_code == 401


# ── 2. Happy path: persisted attachment_id ───────────────────────────────────

def test_download_with_persisted_attachment_id(logged_in_staff, db_session):
    """New polls store attachment_id; download uses it directly (one Graph call to /attachments/{id})."""
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "tax-doc.pdf", "size": 1234, "content_type": "application/pdf", "attachment_id": "att-graph-id-1"}],
    )

    payload = (b"fake pdf binary content for test", "tax-doc.pdf", "application/pdf")
    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.return_value = payload
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )

    assert resp.status_code == 200
    assert resp.content == b"fake pdf binary content for test"
    assert resp.headers["content-type"].startswith("application/pdf")
    # Filename should be in Content-Disposition (both ASCII fallback and UTF-8)
    assert 'filename="tax-doc.pdf"' in resp.headers["content-disposition"]

    # Provider called with the persisted attachment_id, NOT attachment_index
    call = prov.fetch_attachment.call_args
    assert call.kwargs["attachment_id"] == "att-graph-id-1"
    assert call.kwargs["attachment_index"] is None
    # internet_message_id should be the stored header value (unique per test)
    assert call.kwargs["internet_message_id"] == msg.message_id_header


# ── 3. Legacy fallback: no persisted attachment_id ────────────────────────────

def test_download_falls_back_to_index_for_legacy_rows(logged_in_staff, db_session):
    """Pre-existing rows without attachment_id should still work via index lookup."""
    thread, msg = _make_thread_with_message(
        db_session,
        # No attachment_id key (or explicitly null) — legacy row
        attachments=[{"filename": "legacy.pdf", "size": 500, "content_type": "application/pdf"}],
    )

    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.return_value = (b"legacy content", "legacy.pdf", "application/pdf")
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )

    assert resp.status_code == 200
    call = prov.fetch_attachment.call_args
    assert call.kwargs["attachment_id"] is None
    assert call.kwargs["attachment_index"] == 0


# ── 4. Membership: message must belong to thread ──────────────────────────────

def test_download_404_when_message_not_in_thread(logged_in_staff, db_session):
    """Path-parameter pivot guard — can't download via mismatched thread_id."""
    other_thread = EmailThread(id=uuid.uuid4(), subject="Other", client_email="x@example.com", status=EmailStatus.categorized)
    db_session.add(other_thread)
    _, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "doc.pdf", "size": 100, "content_type": "application/pdf"}],
    )
    db_session.commit()

    resp = logged_in_staff.get(
        f"/api/v1/emails/{other_thread.id}/messages/{msg.id}/attachments/0/download"
    )
    assert resp.status_code == 404


# ── 5. Index out of range ─────────────────────────────────────────────────────

def test_download_404_on_index_out_of_range(logged_in_staff, db_session):
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "only.pdf", "size": 100, "content_type": "application/pdf"}],
    )
    resp = logged_in_staff.get(
        f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/5/download"
    )
    assert resp.status_code == 404
    assert "out of range" in resp.json()["detail"]


# ── 6. Provider says message is gone (deleted) ────────────────────────────────

def test_download_404_when_provider_message_not_found(logged_in_staff, db_session):
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "doc.pdf", "size": 100, "content_type": "application/pdf", "attachment_id": "att-1"}],
    )
    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.side_effect = LookupError("Message not found in mailbox")
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ── 6b. Upstream Graph 5xx maps to 502 Bad Gateway ────────────────────────────

def test_download_502_when_upstream_graph_returns_5xx(logged_in_staff, db_session):
    """When Graph returns a 5xx and the provider's raise_for_status() bubbles
    it up as httpx.HTTPStatusError, the route should surface 502 Bad Gateway
    (not a generic 500). The failure is upstream, not in our service."""
    import httpx

    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "doc.pdf", "size": 100, "content_type": "application/pdf", "attachment_id": "att-1"}],
    )

    # Build a realistic httpx.HTTPStatusError with a 503 response
    fake_request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/users/x/messages/y/attachments/z")
    fake_response = httpx.Response(503, request=fake_request, text="ServiceUnavailable")
    err = httpx.HTTPStatusError("503 from Graph", request=fake_request, response=fake_response)

    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.side_effect = err
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )

    assert resp.status_code == 502
    # The client message should mention the upstream status so callers can
    # retry intelligently, but not leak Graph internals like response_body.
    detail = resp.json()["detail"]
    assert "503" in detail
    assert "ServiceUnavailable" not in detail  # no upstream body bleed-through


# ── 7. Provider doesn't support download (e.g. IMAP) ──────────────────────────

def test_download_501_when_provider_doesnt_support(logged_in_staff, db_session):
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "doc.pdf", "size": 100, "content_type": "application/pdf"}],
    )
    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.side_effect = NotImplementedError("IMAPProvider does not support")
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )
    assert resp.status_code == 501


# ── 8. Audit log written on success ───────────────────────────────────────────

def test_download_writes_audit_log_entry(logged_in_staff, db_session):
    """Tax documents flow through this path; downloads must be traceable."""
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "K-1.pdf", "size": 2048, "content_type": "application/pdf", "attachment_id": "att-1"}],
    )
    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.return_value = (b"x" * 2048, "K-1.pdf", "application/pdf")
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )
    assert resp.status_code == 200

    # Find the audit entry
    audits = db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "email.attachment_downloaded",
            AuditLog.entity_id == str(msg.id),
        )
    ).scalars().all()
    assert len(audits) == 1, "Exactly one audit row expected per download"
    details = audits[0].details
    assert details["filename"] == "K-1.pdf"
    assert details["size"] == 2048
    assert details["thread_id"] == str(thread.id)


# ── 9. Filename with non-ASCII (RFC 5987) ─────────────────────────────────────

def test_download_handles_non_ascii_filename(logged_in_staff, db_session):
    """Filenames with accents / unicode must not break the Content-Disposition header."""
    thread, msg = _make_thread_with_message(
        db_session,
        attachments=[{"filename": "déclaration_fiscale_2025.pdf", "size": 100, "content_type": "application/pdf", "attachment_id": "att-1"}],
    )
    with patch("app.services.email_provider.get_email_provider") as get_prov:
        prov = MagicMock()
        prov.fetch_attachment.return_value = (b"content", "déclaration_fiscale_2025.pdf", "application/pdf")
        get_prov.return_value = prov

        resp = logged_in_staff.get(
            f"/api/v1/emails/{thread.id}/messages/{msg.id}/attachments/0/download"
        )
    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    # Both forms present: ASCII fallback + UTF-8 RFC 5987 encoding
    assert "filename=" in cd
    assert "filename*=UTF-8''" in cd
    assert "d%C3%A9claration" in cd or "déclaration" in cd
