"""
Integration tests for POST /api/v1/emails/compose — the brand-new outbound
email ("New Email") + send-with-attachments flow.

These were the explicit gap called out in the WIP commit ("endpoint tests
still to come"). They characterise the already-implemented backend:

* happy path persists a thread + outbound message and calls the provider
* Jane's configured signature is appended at send
* extra To recipients fold into Cc; explicit Cc is preserved
* attachments reach the provider as EmailAttachment payloads
* the total-size cap returns 413
* missing / malformed input returns 422
* a provider send failure returns 502 and rolls back (nothing persisted)
* auth / CSRF is required

The shared `mock_email_provider` fixture (a RecordingEmailProvider) captures
every send so we can assert on what would have gone out, without a real SMTP /
Graph call.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from datetime import datetime, timezone

from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)

COMPOSE_URL = "/api/v1/emails/compose"
LIST_URL = "/api/v1/emails"


def _unique_subject(prefix: str = "Compose") -> str:
    """Subjects must be unique per test — the in-memory DB accumulates rows
    across tests (StaticPool), so we filter by a per-test marker."""
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# ── Happy path ────────────────────────────────────────────────────────────────

def test_compose_sends_and_persists_thread(logged_in_admin, mock_email_provider):
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={
            "to": "client@example.com",
            "subject": subject,
            "body": "Hello, just following up on your return.",
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["subject"] == subject
    assert payload["client_email"] == "client@example.com"
    assert payload["status"] == EmailStatus.sent.value

    # Provider was asked to send exactly once with the right envelope.
    assert len(mock_email_provider.sent_emails) == 1
    sent = mock_email_provider.sent_emails[0]
    assert sent["to"] == "client@example.com"
    assert sent["subject"] == subject
    assert "following up" in sent["body_text"]
    assert sent["cc"] == []
    assert mock_email_provider.connect_calls >= 1


def test_compose_persists_outbound_message(logged_in_admin, mock_email_provider, db_session):
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "Body text here."},
    )
    assert resp.status_code == 200, resp.text
    thread_id = uuid.UUID(resp.json()["id"])

    msgs = db_session.execute(
        select(EmailMessage).where(EmailMessage.thread_id == thread_id)
    ).scalars().all()
    assert len(msgs) == 1
    assert msgs[0].direction == MessageDirection.outbound
    assert msgs[0].is_processed is True


# ── Signature enforcement ───────────────────────────────────────────────────────

def test_compose_appends_configured_signature(logged_in_admin, mock_email_provider, db_session):
    # Sender (the admin) has no personal signature → company fallback applies.
    from app.services import system_settings as ss

    signature = "—\nJane Schilmoeller, CPA\nSchilmoeller & Schoenfield, PC"
    ss.set_setting(db_session, ss.COMPANY_SIGNATURE, signature)
    db_session.commit()

    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "Quick note."},
    )
    assert resp.status_code == 200, resp.text

    sent_body = mock_email_provider.sent_emails[-1]["body_text"]
    assert sent_body.endswith(signature)
    assert "Quick note." in sent_body


# ── Recipient handling ──────────────────────────────────────────────────────────

def test_compose_folds_extra_to_into_cc(logged_in_admin, mock_email_provider):
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={
            "to": "primary@example.com, second@example.com",
            "cc": "boss@example.com",
            "subject": subject,
            "body": "Hello everyone.",
        },
    )
    assert resp.status_code == 200, resp.text
    sent = mock_email_provider.sent_emails[-1]
    # send_email takes a single `to`; the extra To addr + explicit Cc all land in Cc.
    assert sent["to"] == "primary@example.com"
    assert sent["cc"] == ["second@example.com", "boss@example.com"]


def test_compose_dedupes_and_validates_recipients(logged_in_admin, mock_email_provider):
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={
            "to": "dup@example.com; dup@example.com",
            "subject": subject,
            "body": "Body.",
        },
    )
    assert resp.status_code == 200, resp.text
    sent = mock_email_provider.sent_emails[-1]
    assert sent["to"] == "dup@example.com"
    assert sent["cc"] == []  # the duplicate was collapsed, not folded into Cc


# ── Attachments ─────────────────────────────────────────────────────────────────

def test_compose_with_attachments(logged_in_admin, mock_email_provider):
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "See attached."},
        files=[
            ("attachments", ("return.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")),
            ("attachments", ("notes.txt", b"plain text notes", "text/plain")),
        ],
    )
    assert resp.status_code == 200, resp.text

    sent = mock_email_provider.sent_emails[-1]
    atts = sent["attachments"]
    assert len(atts) == 2
    names = {a.filename for a in atts}
    assert names == {"return.pdf", "notes.txt"}
    pdf = next(a for a in atts if a.filename == "return.pdf")
    assert pdf.content == b"%PDF-1.4 fake pdf bytes"
    assert pdf.content_type == "application/pdf"


def test_compose_persists_attachment_metadata(
    logged_in_admin, mock_email_provider, db_session
):
    """The outbound EmailMessage records {filename, size, content_type}
    metadata so the thread view renders sent attachments exactly like inbound
    ones, and stores the provider-returned (Exchange-assigned) Message-ID so
    the download endpoint can resolve the sent copy in the mailbox."""
    # Unique per test — message_id_header has a UNIQUE constraint and the
    # test DB is shared across files (test_drafts_send uses its own id).
    mock_email_provider.send_returns = "<real-graph-id-compose@outlook.com>"
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "See attached."},
        files=[
            ("attachments", ("return.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")),
        ],
    )
    assert resp.status_code == 200, resp.text
    thread_id = uuid.UUID(resp.json()["id"])

    outbound = db_session.execute(
        select(EmailMessage).where(EmailMessage.thread_id == thread_id)
    ).scalar_one()
    assert outbound.attachments == [
        {
            "filename": "return.pdf",
            "size": len(b"%PDF-1.4 fake pdf bytes"),
            "content_type": "application/pdf",
            "attachment_id": None,
        }
    ]
    assert outbound.message_id_header == "<real-graph-id-compose@outlook.com>"


def test_compose_without_attachments_stores_no_metadata(
    logged_in_admin, mock_email_provider, db_session
):
    """A bare compose leaves EmailMessage.attachments NULL — no empty-list rows."""
    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "No files."},
    )
    assert resp.status_code == 200, resp.text
    thread_id = uuid.UUID(resp.json()["id"])

    outbound = db_session.execute(
        select(EmailMessage).where(EmailMessage.thread_id == thread_id)
    ).scalar_one()
    assert outbound.attachments is None


def test_compose_rejects_attachments_over_total_limit(
    logged_in_admin, mock_email_provider, monkeypatch
):
    # Shrink the cap so we don't have to ship 25 MB through the test client.
    # The endpoint imports the constant at call time, so patching the module
    # attribute is sufficient.
    import app.services.email_provider as prov
    monkeypatch.setattr(prov, "MAX_TOTAL_ATTACHMENT_SIZE", 10)

    subject = _unique_subject()
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "Too big."},
        files=[("attachments", ("big.bin", b"x" * 5000, "application/octet-stream"))],
    )
    assert resp.status_code == 413, resp.text
    # Nothing should have been sent.
    assert all(s["subject"] != subject for s in mock_email_provider.sent_emails)


# ── Validation ──────────────────────────────────────────────────────────────────

def test_compose_requires_to(logged_in_admin, mock_email_provider):
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "   ", "subject": _unique_subject(), "body": "Body."},
    )
    assert resp.status_code == 422, resp.text


def test_compose_rejects_invalid_email(logged_in_admin, mock_email_provider):
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "not-an-email", "subject": _unique_subject(), "body": "Body."},
    )
    assert resp.status_code == 422, resp.text


def test_compose_requires_subject(logged_in_admin, mock_email_provider):
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": "   ", "body": "Body."},
    )
    assert resp.status_code == 422, resp.text


def test_compose_requires_body(logged_in_admin, mock_email_provider):
    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": _unique_subject(), "body": "   "},
    )
    assert resp.status_code == 422, resp.text


# ── Send failure → rollback ─────────────────────────────────────────────────────

def test_compose_rolls_back_on_send_failure(
    logged_in_admin, mock_email_provider, db_session
):
    mock_email_provider.raise_on_send = RuntimeError("smtp connection refused")
    subject = _unique_subject()

    resp = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "Will fail."},
    )
    assert resp.status_code == 502, resp.text

    # The thread + message must NOT have been persisted (transaction rolled back).
    threads = db_session.execute(
        select(EmailThread).where(EmailThread.subject == subject)
    ).scalars().all()
    assert threads == []


# ── Auth / CSRF ─────────────────────────────────────────────────────────────────

def test_compose_requires_auth(client, mock_email_provider):
    resp = client.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": _unique_subject(), "body": "Body."},
    )
    # Unauthenticated + no CSRF token — either gate may trip first.
    assert resp.status_code in (401, 403), resp.text
    assert mock_email_provider.sent_emails == []


# ── Sent folder (sent_only filter) ──────────────────────────────────────────────

def test_composed_thread_appears_in_sent_folder(logged_in_admin, mock_email_provider):
    subject = _unique_subject("Sent")
    compose = logged_in_admin.post(
        COMPOSE_URL,
        data={"to": "client@example.com", "subject": subject, "body": "Sent body."},
    )
    assert compose.status_code == 200, compose.text
    thread_id = compose.json()["id"]

    resp = logged_in_admin.get(LIST_URL, params={"sent_only": "true", "page_size": 100})
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert thread_id in ids


def test_inbound_only_thread_excluded_from_sent_folder(
    logged_in_admin, db_session
):
    # A thread that only ever received mail (no outbound) must NOT be in Sent.
    subject = _unique_subject("InboundOnly")
    thread = EmailThread(
        subject=subject,
        client_email="someone@example.com",
        status=EmailStatus.new,
        category=EmailCategory.uncategorized,
    )
    db_session.add(thread)
    db_session.flush()
    db_session.add(
        EmailMessage(
            thread_id=thread.id,
            message_id_header=f"<inbound-{thread.id}@example.com>",
            sender="someone@example.com",
            recipient="firm@example.com",
            body_text="Incoming question.",
            received_at=datetime.now(timezone.utc),
            direction=MessageDirection.inbound,
            is_processed=True,
        )
    )
    db_session.commit()

    sent = logged_in_admin.get(LIST_URL, params={"sent_only": "true", "page_size": 100})
    assert sent.status_code == 200, sent.text
    sent_ids = {item["id"] for item in sent.json()["items"]}
    assert str(thread.id) not in sent_ids

    # Sanity: it DOES show in the default (inbox) listing.
    inbox = logged_in_admin.get(LIST_URL, params={"page_size": 100})
    inbox_ids = {item["id"] for item in inbox.json()["items"]}
    assert str(thread.id) in inbox_ids
