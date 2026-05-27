"""
Tests for the inline-image endpoint
(GET /emails/{thread_id}/messages/{message_id}/inline/{content_id}).

Inline images are fetched live from the provider by Content-ID — never stored —
so the message renderer can show embedded images like Outlook.
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


def _thread_with_inbound(db) -> tuple[EmailThread, EmailMessage]:
    thread = EmailThread(
        id=uuid.uuid4(),
        subject="Inline test",
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name="Test Client",
        status=EmailStatus.categorized,
        category=EmailCategory.general_inquiry,
        suggested_reply_tone="professional",
    )
    db.add(thread)
    db.flush()
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        message_id_header=f"<inbound-inline-{uuid.uuid4().hex[:8]}@client.example.com>",
        sender=f"Client <{thread.client_email}>",
        recipient="firm@example.com",
        body_text="See the image below.",
        body_html='<p>See the image below.</p><img src="cid:image001@x">',
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.inbound,
        is_processed=True,
    )
    db.add(msg)
    db.flush()
    return thread, msg


def test_inline_image_streams_bytes_and_passes_cid(
    logged_in_admin, db_session, mock_email_provider
):
    thread, msg = _thread_with_inbound(db_session)
    db_session.commit()

    resp = logged_in_admin.get(
        f"/api/v1/emails/{thread.id}/messages/{msg.id}/inline/image001@x"
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content == b"\x89PNG\r\n\x1a\nfake-image-bytes"
    # The provider was asked for the exact cid from the URL.
    assert mock_email_provider.inline_fetches[0]["content_id"] == "image001@x"
    assert (
        mock_email_provider.inline_fetches[0]["internet_message_id"]
        == msg.message_id_header
    )


def test_inline_image_404_for_missing_message(
    logged_in_admin, db_session, mock_email_provider
):
    thread, _ = _thread_with_inbound(db_session)
    db_session.commit()

    resp = logged_in_admin.get(
        f"/api/v1/emails/{thread.id}/messages/{uuid.uuid4()}/inline/whatever"
    )
    assert resp.status_code == 404
    # No provider call when the message can't be resolved.
    assert mock_email_provider.inline_fetches == []


def test_inline_image_404_when_cid_not_found(
    logged_in_admin, db_session, mock_email_provider
):
    thread, msg = _thread_with_inbound(db_session)
    db_session.commit()
    mock_email_provider.raise_on_inline = LookupError("Inline image not found")

    resp = logged_in_admin.get(
        f"/api/v1/emails/{thread.id}/messages/{msg.id}/inline/nope@x"
    )
    assert resp.status_code == 404
