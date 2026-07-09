"""
Tests for FEAT/reply-recipients: reply-all + forward support.

Covers:
  1. app.utils.recipients — pure-function unit tests (parse/dedupe/validate/cap,
     compute_reply_all incl. self-exclusion, "Name <addr>" senders, NULL legacy).
  2. Ingest — Graph + IMAP parse capture To/CC onto EmailMessage.
  3. Send path — CC passed to provider, To-folding, NULL-fallback legacy draft,
     audit details, idempotent retry preserves recipients.
  4. PUT draft recipient validation — invalid email, empty To, over-cap,
     [] clears Cc, None leaves unchanged, locked after approval.
  5. GET reply-all-recipients endpoint.
  6. POST forward endpoint — Graph success, IMAP/NotImplemented -> 501,
     missing message -> 404, empty to -> 422.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.utils.recipients import (
    MAX_RECIPIENTS,
    InvalidRecipient,
    compute_reply_all,
    enforce_recipient_cap,
    own_addresses,
    parse_recipient_items,
    parse_recipient_list,
)


def _uid(prefix: str = "msg") -> str:
    return f"<{prefix}-{uuid.uuid4()}@test.local>"


# ===========================================================================
# 1. app.utils.recipients — pure functions
# ===========================================================================

class _FakeSettings:
    def __init__(self, **kwargs):
        self.msgraph_mailbox = kwargs.get("msgraph_mailbox", "")
        self.imap_username = kwargs.get("imap_username", "")
        self.smtp_username = kwargs.get("smtp_username", "")
        self.firm_owner_email = kwargs.get("firm_owner_email", "")


class _FakeInboundMessage:
    def __init__(self, sender, to_recipients=None, cc_recipients=None):
        self.sender = sender
        self.to_recipients = to_recipients
        self.cc_recipients = cc_recipients


class TestParseRecipientList:
    def test_empty_and_none(self):
        assert parse_recipient_list(None) == []
        assert parse_recipient_list("") == []
        assert parse_recipient_list("   ") == []

    def test_splits_comma_and_semicolon(self):
        assert parse_recipient_list("a@x.com, b@x.com; c@x.com") == [
            "a@x.com", "b@x.com", "c@x.com",
        ]

    def test_dedupes_case_insensitively_preserving_order(self):
        assert parse_recipient_list("a@x.com, A@X.COM, b@x.com") == [
            "a@x.com", "b@x.com",
        ]

    def test_rejects_invalid_address(self):
        with pytest.raises(InvalidRecipient):
            parse_recipient_list("not-an-email")

    def test_rejects_one_bad_address_among_good_ones(self):
        with pytest.raises(InvalidRecipient):
            parse_recipient_list("good@x.com, bad, also-good@x.com")


class TestParseRecipientItems:
    def test_element_wise_validation(self):
        assert parse_recipient_items(["a@x.com", "b@x.com"]) == ["a@x.com", "b@x.com"]

    def test_empty_and_none(self):
        assert parse_recipient_items([]) == []
        assert parse_recipient_items(None) == []

    def test_rejects_invalid_element(self):
        with pytest.raises(InvalidRecipient):
            parse_recipient_items(["a@x.com", "not-an-email"])

    def test_dedupes(self):
        assert parse_recipient_items(["a@x.com", "A@x.com"]) == ["a@x.com"]


class TestEnforceRecipientCap:
    def test_allows_at_limit(self):
        to = [f"user{i}@x.com" for i in range(MAX_RECIPIENTS)]
        enforce_recipient_cap(to, [])  # must not raise

    def test_rejects_over_limit(self):
        to = [f"user{i}@x.com" for i in range(MAX_RECIPIENTS + 1)]
        with pytest.raises(InvalidRecipient):
            enforce_recipient_cap(to, [])

    def test_combines_to_and_cc(self):
        to = [f"user{i}@x.com" for i in range(30)]
        cc = [f"cc{i}@x.com" for i in range(25)]
        with pytest.raises(InvalidRecipient):
            enforce_recipient_cap(to, cc)


class TestOwnAddresses:
    def test_lowercases_and_drops_empties(self):
        settings = _FakeSettings(
            msgraph_mailbox="Firm@Example.com",
            imap_username="",
            smtp_username="firm@example.com",
            firm_owner_email="Jane@Example.com",
        )
        assert own_addresses(settings) == {"firm@example.com", "jane@example.com"}

    def test_all_empty(self):
        assert own_addresses(_FakeSettings()) == set()


class TestComputeReplyAll:
    def test_null_inbound_falls_back_to_sender_only(self):
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(sender="Client <client@example.com>")
        to, cc = compute_reply_all(msg, settings)
        assert to == ["client@example.com"]
        assert cc == []

    def test_excludes_self_and_sender_from_to(self):
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(
            sender="Client <client@example.com>",
            to_recipients=["firm@example.com", "client@example.com", "other@example.com"],
            cc_recipients=["cc1@example.com"],
        )
        to, cc = compute_reply_all(msg, settings)
        assert to == ["client@example.com", "other@example.com"]
        assert cc == ["cc1@example.com"]

    def test_excludes_self_from_cc(self):
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(
            sender="Client <client@example.com>",
            to_recipients=[],
            cc_recipients=["firm@example.com", "cc1@example.com"],
        )
        to, cc = compute_reply_all(msg, settings)
        assert to == ["client@example.com"]
        assert cc == ["cc1@example.com"]

    def test_dedupes_across_to_and_cc(self):
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(
            sender="Client <client@example.com>",
            to_recipients=["other@example.com"],
            cc_recipients=["OTHER@example.com", "cc1@example.com"],
        )
        to, cc = compute_reply_all(msg, settings)
        assert to == ["client@example.com", "other@example.com"]
        assert cc == ["cc1@example.com"]

    def test_plain_sender_no_angle_brackets(self):
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(sender="client@example.com")
        to, cc = compute_reply_all(msg, settings)
        assert to == ["client@example.com"]
        assert cc == []

    def test_raises_over_cap(self):
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        lots = [f"user{i}@example.com" for i in range(MAX_RECIPIENTS + 5)]
        msg = _FakeInboundMessage(sender="client@example.com", to_recipients=lots)
        with pytest.raises(InvalidRecipient):
            compute_reply_all(msg, settings)

    def test_filters_malformed_stored_addresses(self):
        """
        to_recipients/cc_recipients are populated by provider-side header
        parsing (Graph/IMAP), not our own validation — a malformed legacy
        address must never flow into a 200 response that would only 422
        later when the UI tries to PUT it onto the draft.
        """
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(
            sender="Client <client@example.com>",
            to_recipients=["firm@example.com", "not-an-email", "other@example.com"],
            cc_recipients=["also-not-an-email", "cc1@example.com"],
        )
        to, cc = compute_reply_all(msg, settings)
        assert to == ["client@example.com", "other@example.com"]
        assert cc == ["cc1@example.com"]

    def test_filters_malformed_sender(self):
        """A malformed From header (rare, but seen from broken auto-mailers)
        must not produce an unvalidated address in the To list."""
        settings = _FakeSettings(msgraph_mailbox="firm@example.com")
        msg = _FakeInboundMessage(sender="not-a-valid-sender")
        to, cc = compute_reply_all(msg, settings)
        assert to == []
        assert cc == []


# ===========================================================================
# 2. Ingest — Graph + IMAP capture To/CC
# ===========================================================================

def _fake_graph_response(messages: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"value": messages}
    resp.raise_for_status.return_value = None
    return resp


def _base_graph_message(**overrides) -> dict:
    msg = {
        "id": "graph-id-1",
        "internetMessageId": _uid("graph"),
        "subject": "Test subject",
        "from": {"emailAddress": {"address": "client@example.com"}},
        "toRecipients": [{"emailAddress": {"address": "firm@example.com"}}],
        "ccRecipients": [{"emailAddress": {"address": "cc1@example.com"}}],
        "receivedDateTime": "2026-05-19T10:00:00Z",
        "conversationId": "conv-1",
        "internetMessageHeaders": [],
        "hasAttachments": False,
        "attachments": [],
        "body": {"contentType": "text", "content": "Hello."},
    }
    msg.update(overrides)
    return msg


class TestGraphIngestRecipients:
    def test_fetch_new_emails_captures_to_and_cc(self):
        from app.services.email_provider import MSGraphProvider

        provider = MSGraphProvider(get_settings())
        provider._access_token = "test-token"
        provider._token_expires_at = datetime.now(timezone.utc).replace(year=2099)
        provider._client = MagicMock()
        provider._client.get.return_value = _fake_graph_response([
            _base_graph_message(
                toRecipients=[
                    {"emailAddress": {"address": "firm@example.com"}},
                    {"emailAddress": {"address": "other@example.com"}},
                ],
                ccRecipients=[{"emailAddress": {"address": "cc1@example.com"}}],
            ),
        ])

        results = provider.fetch_new_emails()

        assert len(results) == 1
        assert results[0].to_recipients == ["firm@example.com", "other@example.com"]
        assert results[0].cc_recipients == ["cc1@example.com"]

    def test_fetch_new_emails_empty_recipients_yield_empty_lists(self):
        from app.services.email_provider import MSGraphProvider

        provider = MSGraphProvider(get_settings())
        provider._access_token = "test-token"
        provider._token_expires_at = datetime.now(timezone.utc).replace(year=2099)
        provider._client = MagicMock()
        msg = _base_graph_message(toRecipients=[], ccRecipients=[])
        provider._client.get.return_value = _fake_graph_response([msg])

        results = provider.fetch_new_emails()

        assert results[0].to_recipients == []
        assert results[0].cc_recipients == []

    def test_select_clause_includes_cc_recipients(self):
        from app.services.email_provider import MSGraphProvider

        provider = MSGraphProvider(get_settings())
        provider._access_token = "test-token"
        provider._token_expires_at = datetime.now(timezone.utc).replace(year=2099)
        provider._client = MagicMock()
        provider._client.get.return_value = _fake_graph_response([])

        provider.fetch_new_emails()

        called_url = provider._client.get.call_args[0][0]
        assert "ccRecipients" in called_url
        assert "toRecipients" in called_url


class TestImapIngestRecipients:
    def _build_message(self, *, to: str, cc: str | None = None) -> "email.message.Message":
        import email as email_lib
        from email.mime.text import MIMEText

        msg = MIMEText("Hello there.")
        msg["Message-ID"] = _uid("imap")
        msg["From"] = "Client <client@example.com>"
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = "Test subject"
        msg["Date"] = "Mon, 19 May 2026 10:00:00 +0000"
        return email_lib.message_from_string(msg.as_string())

    def test_parse_message_captures_to_and_cc(self):
        from app.services.email_provider import IMAPProvider

        provider = IMAPProvider(get_settings())
        msg = self._build_message(
            to="firm@example.com, Other <other@example.com>",
            cc="cc1@example.com",
        )
        raw = provider._parse_message(msg)

        assert raw is not None
        assert raw.to_recipients == ["firm@example.com", "other@example.com"]
        assert raw.cc_recipients == ["cc1@example.com"]

    def test_parse_message_no_cc_yields_empty_list(self):
        from app.services.email_provider import IMAPProvider

        provider = IMAPProvider(get_settings())
        msg = self._build_message(to="firm@example.com")
        raw = provider._parse_message(msg)

        assert raw is not None
        assert raw.to_recipients == ["firm@example.com"]
        assert raw.cc_recipients == []


class TestStoreMessagePersistsRecipients:
    def test_store_message_persists_to_and_cc(self, db_session: Session):
        from app.services.email_intake import _find_or_create_thread, _store_message
        from tests.conftest import make_raw_email

        raw = make_raw_email(
            message_id=_uid("store"),
            to_recipients=["firm@example.com"],
            cc_recipients=["cc1@example.com"],
        )
        thread = _find_or_create_thread(db_session, raw)
        message = _store_message(db_session, thread, raw)

        assert message is not None
        assert message.to_recipients == ["firm@example.com"]
        assert message.cc_recipients == ["cc1@example.com"]

    def test_store_message_empty_recipients_store_as_null(self, db_session: Session):
        from app.services.email_intake import _find_or_create_thread, _store_message
        from tests.conftest import make_raw_email

        raw = make_raw_email(message_id=_uid("store-empty"))
        thread = _find_or_create_thread(db_session, raw)
        message = _store_message(db_session, thread, raw)

        assert message is not None
        assert message.to_recipients is None
        assert message.cc_recipients is None


# ===========================================================================
# 3. Send path
# ===========================================================================

def _seed_thread_with_draft(
    *,
    subject: str = "Reply recipients test",
    sender_email: str = "client@example.com",
    draft_body: str = "Dear client, here is your answer.",
    draft_to: list[str] | None = "__unset__",
    draft_cc: list[str] | None = "__unset__",
):
    """Create a thread + inbound message + approved draft. Passing the
    sentinel default for draft_to/draft_cc leaves those columns unset (NULL)
    so send_draft's fallback path is exercised; pass explicit lists/None to
    control them directly."""
    from app.database import SessionLocal
    from app.models.email import (
        DraftResponse, DraftStatus, EmailCategory,
        EmailMessage, EmailStatus, EmailThread, MessageDirection,
    )

    inbound_mid = _uid("inbound")

    db = SessionLocal()
    try:
        thread = EmailThread(
            subject=subject,
            client_email=sender_email,
            status=EmailStatus.categorized,
            category=EmailCategory.general_inquiry,
        )
        db.add(thread)
        db.flush()

        msg = EmailMessage(
            thread_id=thread.id,
            message_id_header=inbound_mid,
            sender=sender_email,
            recipient="firm@example.com",
            body_text="Client question.",
            received_at=datetime.now(timezone.utc),
            direction=MessageDirection.inbound,
            is_processed=True,
        )
        db.add(msg)
        db.flush()

        draft_kwargs = dict(
            thread_id=thread.id,
            body_text=draft_body,
            status=DraftStatus.approved,
            send_attempts=0,
        )
        if draft_to != "__unset__":
            draft_kwargs["to_recipients"] = draft_to
        if draft_cc != "__unset__":
            draft_kwargs["cc_recipients"] = draft_cc

        draft = DraftResponse(**draft_kwargs)
        db.add(draft)
        db.commit()

        return str(thread.id), str(draft.id), inbound_mid
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class TestSendPathRecipients:
    def test_null_fallback_legacy_draft_sends_to_client_email(
        self, logged_in_admin, mock_email_provider,
    ):
        thread_id, draft_id, _ = _seed_thread_with_draft(sender_email="legacy@example.com")

        resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
        assert resp.status_code == 200, resp.text

        sent = mock_email_provider.sent_emails[0]
        assert sent["to"] == "legacy@example.com"
        assert sent["cc"] == []

    def test_cc_passed_to_provider(self, logged_in_admin, mock_email_provider):
        thread_id, draft_id, _ = _seed_thread_with_draft(
            draft_to=["primary@example.com"],
            draft_cc=["cc1@example.com", "cc2@example.com"],
        )

        resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
        assert resp.status_code == 200, resp.text

        sent = mock_email_provider.sent_emails[0]
        assert sent["to"] == "primary@example.com"
        assert sent["cc"] == ["cc1@example.com", "cc2@example.com"]

    def test_multi_to_folds_extras_into_cc(self, logged_in_admin, mock_email_provider):
        thread_id, draft_id, _ = _seed_thread_with_draft(
            draft_to=["primary@example.com", "second@example.com"],
            draft_cc=["cc1@example.com"],
        )

        resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
        assert resp.status_code == 200, resp.text

        sent = mock_email_provider.sent_emails[0]
        assert sent["to"] == "primary@example.com"
        assert sent["cc"] == ["second@example.com", "cc1@example.com"]

    def test_outbound_message_records_to_and_cc(
        self, logged_in_admin, mock_email_provider, db_session,
    ):
        from sqlalchemy import select
        from app.models.email import EmailMessage, MessageDirection

        thread_id, draft_id, _ = _seed_thread_with_draft(
            draft_to=["primary@example.com", "second@example.com"],
            draft_cc=["cc1@example.com"],
        )

        resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
        assert resp.status_code == 200, resp.text

        outbound = db_session.execute(
            select(EmailMessage).where(
                EmailMessage.thread_id == uuid.UUID(thread_id),
                EmailMessage.direction == MessageDirection.outbound,
            )
        ).scalar_one()
        assert outbound.to_recipients == ["primary@example.com", "second@example.com"]
        assert outbound.cc_recipients == ["cc1@example.com"]

    def test_audit_details_include_to_and_cc(
        self, logged_in_admin, mock_email_provider, db_session,
    ):
        from sqlalchemy import select
        from app.models.audit import AuditLog

        thread_id, draft_id, _ = _seed_thread_with_draft(
            draft_to=["primary@example.com"],
            draft_cc=["cc1@example.com"],
        )

        resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
        assert resp.status_code == 200, resp.text

        entry = db_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "draft.sent", AuditLog.entity_id == draft_id)
            .order_by(AuditLog.created_at.desc())
        ).scalars().first()
        assert entry is not None
        assert entry.details["to"] == ["primary@example.com"]
        assert entry.details["cc"] == ["cc1@example.com"]

    def test_empty_to_recipients_returns_422(self, logged_in_admin, mock_email_provider):
        thread_id, draft_id, _ = _seed_thread_with_draft(draft_to=[], draft_cc=[])

        resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
        assert resp.status_code == 422, resp.text
        assert mock_email_provider.sent_emails == []

    def test_idempotent_retry_preserves_recipients(
        self, logged_in_admin, mock_email_provider,
    ):
        """A provider failure followed by a retry (same idempotency key) must
        send to the exact same recipient set both times."""
        thread_id, draft_id, _ = _seed_thread_with_draft(
            draft_to=["primary@example.com"],
            draft_cc=["cc1@example.com"],
        )
        idem_key = "retry-key-recipients-1"
        mock_email_provider.raise_on_send = RuntimeError("SMTP refused")

        resp1 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send",
            data={"idempotency_key": idem_key},
        )
        assert resp1.status_code == 502

        mock_email_provider.raise_on_send = None
        resp2 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send",
            data={"idempotency_key": idem_key},
        )
        assert resp2.status_code == 200, resp2.text

        assert len(mock_email_provider.sent_emails) == 1
        sent = mock_email_provider.sent_emails[0]
        assert sent["to"] == "primary@example.com"
        assert sent["cc"] == ["cc1@example.com"]


# ===========================================================================
# 4. PUT draft recipient validation
# ===========================================================================

class TestUpdateDraftRecipients:
    def _seed_pending_draft(self):
        from app.database import SessionLocal
        from app.models.email import (
            DraftResponse, DraftStatus, EmailCategory,
            EmailMessage, EmailStatus, EmailThread, MessageDirection,
        )
        db = SessionLocal()
        try:
            thread = EmailThread(
                subject="Update recipients test",
                client_email="client@example.com",
                status=EmailStatus.categorized,
                category=EmailCategory.general_inquiry,
            )
            db.add(thread)
            db.flush()
            db.add(EmailMessage(
                thread_id=thread.id,
                message_id_header=_uid("inbound-update"),
                sender="client@example.com",
                recipient="firm@example.com",
                body_text="Client question.",
                received_at=datetime.now(timezone.utc),
                direction=MessageDirection.inbound,
                is_processed=True,
            ))
            draft = DraftResponse(
                thread_id=thread.id,
                body_text="Draft body.",
                status=DraftStatus.pending,
                to_recipients=["client@example.com"],
                cc_recipients=[],
            )
            db.add(draft)
            db.commit()
            return str(thread.id), str(draft.id)
        finally:
            db.close()

    def test_invalid_email_on_pending_draft_returns_422(self, logged_in_admin):
        thread_id, draft_id = self._seed_pending_draft()
        resp = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"to_recipients": ["not-an-email"]},
        )
        assert resp.status_code == 422, resp.text

    def test_empty_to_recipients_returns_422(self, logged_in_admin):
        thread_id, draft_id = self._seed_pending_draft()
        resp = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"to_recipients": []},
        )
        assert resp.status_code == 422, resp.text

    def test_over_cap_returns_422(self, logged_in_admin):
        thread_id, draft_id = self._seed_pending_draft()
        lots = [f"user{i}@example.com" for i in range(MAX_RECIPIENTS + 1)]
        resp = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"to_recipients": lots},
        )
        assert resp.status_code == 422, resp.text

    def test_empty_cc_list_clears_cc(self, logged_in_admin):
        thread_id, draft_id = self._seed_pending_draft()
        # First set a Cc
        resp1 = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"cc_recipients": ["cc1@example.com"]},
        )
        assert resp1.status_code == 200, resp1.text
        assert resp1.json()["cc_recipients"] == ["cc1@example.com"]

        resp2 = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"cc_recipients": []},
        )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["cc_recipients"] == []

    def test_none_leaves_recipients_unchanged(self, logged_in_admin):
        thread_id, draft_id = self._seed_pending_draft()
        resp = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"body_text": "Updated body only."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["to_recipients"] == ["client@example.com"]
        assert resp.json()["cc_recipients"] == []

    def test_locked_after_approval(self, logged_in_admin):
        thread_id, draft_id = self._seed_pending_draft()
        approve_resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}/approve"
        )
        assert approve_resp.status_code == 200, approve_resp.text

        resp = logged_in_admin.put(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}",
            json={"to_recipients": ["newperson@example.com"]},
        )
        assert resp.status_code == 409, resp.text


# ===========================================================================
# 5. GET reply-all-recipients
# ===========================================================================

class TestReplyAllRecipientsEndpoint:
    def _seed_thread_with_inbound(
        self, *, to_recipients=None, cc_recipients=None, sender="Client <client@example.com>"
    ):
        from app.database import SessionLocal
        from app.models.email import (
            DraftResponse, DraftStatus, EmailCategory,
            EmailMessage, EmailStatus, EmailThread, MessageDirection,
        )
        db = SessionLocal()
        try:
            thread = EmailThread(
                subject="Reply all test",
                client_email="client@example.com",
                status=EmailStatus.categorized,
                category=EmailCategory.general_inquiry,
            )
            db.add(thread)
            db.flush()
            db.add(EmailMessage(
                thread_id=thread.id,
                message_id_header=_uid("inbound-reply-all"),
                sender=sender,
                recipient="firm@example.com",
                to_recipients=to_recipients,
                cc_recipients=cc_recipients,
                body_text="Client question.",
                received_at=datetime.now(timezone.utc),
                direction=MessageDirection.inbound,
                is_processed=True,
            ))
            draft = DraftResponse(
                thread_id=thread.id,
                body_text="Draft body.",
                status=DraftStatus.pending,
                to_recipients=["client@example.com"],
                cc_recipients=[],
            )
            db.add(draft)
            db.commit()
            return str(thread.id), str(draft.id)
        finally:
            db.close()

    def test_computes_full_thread_set(self, logged_in_admin):
        # "test@example.com" matches IMAP_USERNAME/SMTP_USERNAME set in
        # conftest.py's test env — it must be excluded as "self".
        thread_id, draft_id = self._seed_thread_with_inbound(
            to_recipients=["test@example.com", "other@example.com"],
            cc_recipients=["cc1@example.com"],
        )
        resp = logged_in_admin.get(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}/reply-all-recipients"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["to"] == ["client@example.com", "other@example.com"]
        assert body["cc"] == ["cc1@example.com"]

    def test_null_inbound_recipients_falls_back_to_sender(self, logged_in_admin):
        thread_id, draft_id = self._seed_thread_with_inbound()
        resp = logged_in_admin.get(
            f"/api/v1/emails/{thread_id}/drafts/{draft_id}/reply-all-recipients"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["to"] == ["client@example.com"]
        assert body["cc"] == []

    def test_404_when_draft_not_found(self, logged_in_admin):
        thread_id, _ = self._seed_thread_with_inbound()
        resp = logged_in_admin.get(
            f"/api/v1/emails/{thread_id}/drafts/{uuid.uuid4()}/reply-all-recipients"
        )
        assert resp.status_code == 404


# ===========================================================================
# 6. Forward endpoint
# ===========================================================================

class TestForwardEndpoint:
    def _seed_message(self):
        from app.database import SessionLocal
        from app.models.email import (
            EmailCategory, EmailMessage, EmailStatus, EmailThread, MessageDirection,
        )
        db = SessionLocal()
        try:
            thread = EmailThread(
                subject="Forward test",
                client_email="client@example.com",
                status=EmailStatus.categorized,
                category=EmailCategory.general_inquiry,
            )
            db.add(thread)
            db.flush()
            msg = EmailMessage(
                thread_id=thread.id,
                message_id_header=_uid("inbound-forward"),
                sender="Client <client@example.com>",
                recipient="firm@example.com",
                body_text="Original message body.",
                received_at=datetime.now(timezone.utc),
                direction=MessageDirection.inbound,
                is_processed=True,
            )
            db.add(msg)
            db.commit()
            return str(thread.id), str(msg.id)
        finally:
            db.close()

    def test_forward_success_records_outbound_and_audit(
        self, logged_in_admin, mock_email_provider, db_session,
    ):
        from sqlalchemy import select
        from app.models.audit import AuditLog
        from app.models.email import EmailMessage, MessageDirection

        thread_id, message_id = self._seed_message()

        resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com", "note": "FYI, see below."},
        )
        assert resp.status_code == 200, resp.text

        assert len(mock_email_provider.forwarded_messages) == 1
        fwd = mock_email_provider.forwarded_messages[0]
        assert fwd["to"] == ["forward-to@example.com"]

        outbound = db_session.execute(
            select(EmailMessage).where(
                EmailMessage.thread_id == uuid.UUID(thread_id),
                EmailMessage.direction == MessageDirection.outbound,
            )
        ).scalar_one()
        assert outbound.to_recipients == ["forward-to@example.com"]
        assert "FYI, see below." in outbound.body_text
        assert "Original message body." in outbound.body_text

        entry = db_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "thread.forwarded")
            .order_by(AuditLog.created_at.desc())
        ).scalars().first()
        assert entry is not None
        assert entry.details["to"] == ["forward-to@example.com"]
        assert entry.details["source_message_id"] == message_id

    def test_forward_not_implemented_returns_501(self, logged_in_admin, mock_email_provider):
        thread_id, message_id = self._seed_message()
        mock_email_provider.raise_on_forward = NotImplementedError("not supported")

        resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com"},
        )
        assert resp.status_code == 501, resp.text

    def test_forward_missing_message_returns_404(self, logged_in_admin, mock_email_provider):
        thread_id, message_id = self._seed_message()
        mock_email_provider.raise_on_forward = LookupError("message not found")

        resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com"},
        )
        assert resp.status_code == 404, resp.text

    def test_forward_empty_to_returns_422(self, logged_in_admin, mock_email_provider):
        thread_id, message_id = self._seed_message()

        resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "   "},
        )
        assert resp.status_code == 422, resp.text
        assert mock_email_provider.forwarded_messages == []

    def test_forward_missing_message_id_returns_404_before_provider_call(
        self, logged_in_admin, mock_email_provider,
    ):
        thread_id, _ = self._seed_message()
        resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{uuid.uuid4()}/forward",
            data={"to": "forward-to@example.com"},
        )
        assert resp.status_code == 404, resp.text
        assert mock_email_provider.forwarded_messages == []

    # ── Idempotency (double-send guard) ────────────────────────────────────
    #
    # RecordingEmailProvider.forward_message defaults to a call-count-based
    # id ("<mock-fwd-N@test.local>") that starts fresh for every test (the
    # provider fixture is function-scoped) — fine for a single successful
    # call per test, but the in-memory DB is shared across the WHOLE test
    # session (StaticPool), so two tests that each make exactly one default
    # call would both try to insert the literal id "<mock-fwd-1@test.local>"
    # and collide on the unique constraint. Tests below either give the
    # provider a unique `forward_returns`, or (when a test needs more than
    # one successful call) install a uuid-based generator via
    # _install_unique_forward so every call in the whole run is unique.

    def _install_unique_forward(self, provider) -> None:
        """Patch forward_message to always return a fresh, collision-free id
        while still recording the call the same way RecordingEmailProvider does."""
        def _unique_forward(*, internet_message_id, to, cc=None, comment=None):
            if provider.raise_on_forward:
                raise provider.raise_on_forward
            provider.forwarded_messages.append({
                "internet_message_id": internet_message_id,
                "to": to,
                "cc": cc or [],
                "comment": comment,
            })
            return f"<{uuid.uuid4()}@test.local>"

        provider.forward_message = _unique_forward

    def test_repeated_forward_with_same_key_calls_provider_once(
        self, logged_in_admin, mock_email_provider,
    ):
        mock_email_provider.forward_returns = "<repeat-key-test1@test.local>"
        thread_id, message_id = self._seed_message()
        key = "fwd-idem-test-key-1"

        resp1 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com", "idempotency_key": key},
        )
        assert resp1.status_code == 200, resp1.text

        resp2 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com", "idempotency_key": key},
        )
        assert resp2.status_code == 200, resp2.text

        assert resp1.json()["id"] == resp2.json()["id"], (
            "Repeat request with the same key must return the original "
            "outbound message, not create a new one"
        )
        assert len(mock_email_provider.forwarded_messages) == 1, (
            "Provider must be called exactly once when the idempotency key is reused"
        )

    def test_repeated_forward_with_same_key_creates_one_outbound_row(
        self, logged_in_admin, mock_email_provider, db_session,
    ):
        from sqlalchemy import select
        from app.models.email import EmailMessage, MessageDirection

        mock_email_provider.forward_returns = "<repeat-key-test2@test.local>"
        thread_id, message_id = self._seed_message()
        key = "fwd-idem-test-key-2"

        for _ in range(2):
            resp = logged_in_admin.post(
                f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
                data={"to": "forward-to@example.com", "idempotency_key": key},
            )
            assert resp.status_code == 200, resp.text

        outbound_rows = db_session.execute(
            select(EmailMessage).where(
                EmailMessage.thread_id == uuid.UUID(thread_id),
                EmailMessage.direction == MessageDirection.outbound,
            )
        ).scalars().all()
        assert len(outbound_rows) == 1

    def test_different_keys_both_forward(self, logged_in_admin, mock_email_provider):
        """Sanity check the dedup is scoped to (message, key) — a
        deliberately distinct key must still forward normally."""
        self._install_unique_forward(mock_email_provider)
        thread_id, message_id = self._seed_message()

        resp1 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com", "idempotency_key": "fwd-key-a"},
        )
        resp2 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com", "idempotency_key": "fwd-key-b"},
        )
        assert resp1.status_code == 200 and resp2.status_code == 200
        assert resp1.json()["id"] != resp2.json()["id"]
        assert len(mock_email_provider.forwarded_messages) == 2

    def test_malformed_idempotency_key_returns_422(self, logged_in_admin, mock_email_provider):
        thread_id, message_id = self._seed_message()
        resp = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com", "idempotency_key": "bad key with spaces"},
        )
        assert resp.status_code == 422, resp.text
        assert mock_email_provider.forwarded_messages == []

    def test_forward_without_key_is_not_deduped(self, logged_in_admin, mock_email_provider):
        """No idempotency_key supplied -> no dedup guard; two identical
        requests both forward (matches the pre-fix baseline behavior)."""
        self._install_unique_forward(mock_email_provider)
        thread_id, message_id = self._seed_message()

        resp1 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com"},
        )
        resp2 = logged_in_admin.post(
            f"/api/v1/emails/{thread_id}/messages/{message_id}/forward",
            data={"to": "forward-to@example.com"},
        )
        assert resp1.status_code == 200 and resp2.status_code == 200
        assert len(mock_email_provider.forwarded_messages) == 2


# ===========================================================================
# 7. Orphaned Graph draft cleanup on partial forward failure
# ===========================================================================

class TestGraphForwardOrphanCleanup:
    """
    MSGraphProvider.forward_message uses createForward (drafts a forward
    copy) then a separate /send call. If /send fails after createForward
    already succeeded, the draft would otherwise sit orphaned in the
    mailbox's Drafts folder forever (and could later be sent by mistake).
    """

    def _make_provider(self):
        from app.services.email_provider import MSGraphProvider

        provider = MSGraphProvider(get_settings())
        provider._access_token = "test-token"
        provider._token_expires_at = datetime.now(timezone.utc).replace(year=2099)
        provider._client = MagicMock()
        return provider

    def _resolve_response(self) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"value": [{"id": "graph-msg-1"}]}
        resp.raise_for_status.return_value = None
        return resp

    def _create_forward_response(self, draft_id: str = "draft-123") -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"id": draft_id, "internetMessageId": "<fwd@test.local>"}
        resp.raise_for_status.return_value = None
        return resp

    def _failing_send_response(self) -> MagicMock:
        import httpx

        mock_response = MagicMock(status_code=500, text="send failed upstream")
        http_error = httpx.HTTPStatusError(
            "send failed", request=MagicMock(), response=mock_response
        )
        resp = MagicMock()
        resp.raise_for_status.side_effect = http_error
        return resp

    def test_send_failure_deletes_orphaned_draft_and_still_raises(self):
        import httpx

        provider = self._make_provider()
        provider._client.get.return_value = self._resolve_response()
        provider._client.post.side_effect = [
            self._create_forward_response("draft-123"),
            self._failing_send_response(),
        ]
        provider._client.delete.return_value = MagicMock(raise_for_status=lambda: None)

        with pytest.raises(httpx.HTTPStatusError):
            provider.forward_message(
                internet_message_id="<orig@example.com>",
                to=["someone@example.com"],
            )

        provider._client.delete.assert_called_once()
        delete_url = provider._client.delete.call_args[0][0]
        assert "draft-123" in delete_url

    def test_delete_failure_does_not_mask_original_send_error(self):
        import httpx

        provider = self._make_provider()
        provider._client.get.return_value = self._resolve_response()
        provider._client.post.side_effect = [
            self._create_forward_response("draft-999"),
            self._failing_send_response(),
        ]
        provider._client.delete.side_effect = RuntimeError("delete also failed")

        with pytest.raises(httpx.HTTPStatusError):
            provider.forward_message(
                internet_message_id="<orig@example.com>",
                to=["someone@example.com"],
            )

        provider._client.delete.assert_called_once()

    def test_successful_send_never_calls_delete(self):
        provider = self._make_provider()
        provider._client.get.return_value = self._resolve_response()
        ok_send = MagicMock(raise_for_status=lambda: None)
        provider._client.post.side_effect = [
            self._create_forward_response("draft-ok"),
            ok_send,
        ]

        provider.forward_message(
            internet_message_id="<orig@example.com>",
            to=["someone@example.com"],
        )

        provider._client.delete.assert_not_called()
