"""
Tests for the T1 auto-send pipeline (`app.services.auto_send`).

This is the only path that sends email without human approval — every gate,
every rollback, every audit row matters. Coverage:

  1. Gate skip when auto_send_enabled='false'
  2. Gate skip when shadow_mode=true (env)
  3. Gate skip when thread.tier != t1_auto
  4. Gate skip when thread.auto_sent_at is already set (no re-send)
  5. Provider raises → draft=send_failed + thread=draft_ready + audit row +
     ONE outbound EmailMessage (no ghost row)
  6. Provider returns alternate message_id → outbound row's header is updated
  7. Provider returns empty/None → treated as failure (NOT silent success)
  8. Success path → draft=sent, thread=sent, auto_sent_at set,
     `thread.auto_sent` audit row written
  9. Bonus — defensive: thread with zero inbound messages refuses to send
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.email import (
    CategorizationSource,
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.models.system_setting import SystemSetting
from app.models.tier_rule import TierRule
from app.services import system_settings as ss
from app.services.auto_send import is_auto_send_enabled, maybe_auto_send


# ── Test factory helpers ──────────────────────────────────────────────────────


def _make_t1_thread(
    db: Session,
    *,
    tier: ThreadTier = ThreadTier.t1_auto,
    auto_sent_at: datetime | None = None,
) -> EmailThread:
    thread = EmailThread(
        id=uuid.uuid4(),
        subject="Re: my tax return status",
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name="Test Client",
        status=EmailStatus.draft_ready,
        category=EmailCategory.status_update,
        category_confidence=0.95,
        ai_summary="Status check.",
        suggested_reply_tone="professional",
        tier=tier,
        tier_set_at=datetime.now(timezone.utc),
        tier_set_by="system",
        categorization_source=CategorizationSource.claude,
        auto_sent_at=auto_sent_at,
    )
    db.add(thread)
    db.flush()
    return thread


def _add_inbound_message(db: Session, thread: EmailThread) -> EmailMessage:
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        message_id_header=f"<inbound-{uuid.uuid4().hex[:8]}@client.example.com>",
        sender=f"Client <{thread.client_email}>",
        recipient="firm@example.com",
        body_text="Just checking in on my return.",
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.inbound,
        is_processed=True,
    )
    db.add(msg)
    db.flush()
    return msg


def _add_pending_draft(db: Session, thread: EmailThread) -> DraftResponse:
    draft = DraftResponse(
        id=uuid.uuid4(),
        thread_id=thread.id,
        body_text="Hi, your return is on track. Best, the firm.",
        status=DraftStatus.pending,
        version=1,
        send_attempts=0,
    )
    db.add(draft)
    db.flush()
    return draft


def _enable_auto_send(db: Session) -> None:
    """Insert/update the system_settings row to enable auto-send."""
    db.execute(delete(SystemSetting).where(SystemSetting.key == ss.AUTO_SEND_ENABLED))
    db.add(SystemSetting(key=ss.AUTO_SEND_ENABLED, value="true"))
    db.flush()


def _disable_auto_send(db: Session) -> None:
    db.execute(delete(SystemSetting).where(SystemSetting.key == ss.AUTO_SEND_ENABLED))
    db.add(SystemSetting(key=ss.AUTO_SEND_ENABLED, value="false"))
    db.flush()


def _outbound_count(db: Session, thread_id: uuid.UUID) -> int:
    return db.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.outbound,
        )
    ).scalars().all().__len__()


def _audit_actions(db: Session, thread_id: uuid.UUID) -> list[str]:
    rows = db.execute(
        select(AuditLog).where(AuditLog.entity_id == str(thread_id))
    ).scalars().all()
    return [r.action for r in rows]


# ── Test setup fixture: gates ON, T1 thread + draft + inbound ─────────────────


@pytest.fixture()
def t1_setup(db_session: Session, mock_email_provider):
    """Standard setup: gates open, T1 thread with one inbound message and a pending draft."""
    _enable_auto_send(db_session)
    db_session.commit()

    thread = _make_t1_thread(db_session)
    _add_inbound_message(db_session, thread)
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    yield {
        "db": db_session,
        "thread": thread,
        "draft": draft,
        "provider": mock_email_provider,
    }

    # Cleanup the system_settings row so other tests don't see auto_send_enabled
    db_session.execute(delete(SystemSetting).where(SystemSetting.key == ss.AUTO_SEND_ENABLED))
    db_session.commit()


# ── 1. Gate: auto_send_enabled='false' ────────────────────────────────────────


def test_skips_when_auto_send_disabled(db_session, mock_email_provider):
    _disable_auto_send(db_session)
    thread = _make_t1_thread(db_session)
    _add_inbound_message(db_session, thread)
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    enabled, reason = is_auto_send_enabled(db_session)
    assert enabled is False
    assert "auto_send_enabled" in (reason or "")

    sent = maybe_auto_send(db_session, thread_id=thread.id, draft_id=draft.id)
    assert sent is False
    assert mock_email_provider.sent_emails == []
    db_session.refresh(thread)
    assert thread.auto_sent_at is None
    assert thread.status == EmailStatus.draft_ready  # unchanged


# ── 2. Gate: shadow_mode env flag ─────────────────────────────────────────────


def test_skips_when_shadow_mode_on(monkeypatch, db_session, mock_email_provider):
    _enable_auto_send(db_session)
    thread = _make_t1_thread(db_session)
    _add_inbound_message(db_session, thread)
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    # Override the cached settings to enable shadow_mode
    from app.config import get_settings as _get_settings
    _get_settings.cache_clear()
    monkeypatch.setenv("SHADOW_MODE", "true")

    try:
        enabled, reason = is_auto_send_enabled(db_session)
        assert enabled is False
        assert "shadow_mode" in (reason or "")

        sent = maybe_auto_send(db_session, thread_id=thread.id, draft_id=draft.id)
        assert sent is False
        assert mock_email_provider.sent_emails == []
    finally:
        # Restore settings cache for other tests
        monkeypatch.setenv("SHADOW_MODE", "false")
        _get_settings.cache_clear()
        # Repopulate by reading once
        _get_settings()


# ── 3. Gate: tier != t1_auto ──────────────────────────────────────────────────


def test_skips_when_tier_is_not_t1(db_session, mock_email_provider):
    _enable_auto_send(db_session)
    thread = _make_t1_thread(db_session, tier=ThreadTier.t2_review)
    _add_inbound_message(db_session, thread)
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    sent = maybe_auto_send(db_session, thread_id=thread.id, draft_id=draft.id)
    assert sent is False
    assert mock_email_provider.sent_emails == []


# ── 4. Gate: thread.auto_sent_at already populated ────────────────────────────


def test_skips_when_already_auto_sent(db_session, mock_email_provider):
    _enable_auto_send(db_session)
    already = datetime.now(timezone.utc)
    thread = _make_t1_thread(db_session, auto_sent_at=already)
    _add_inbound_message(db_session, thread)
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    sent = maybe_auto_send(db_session, thread_id=thread.id, draft_id=draft.id)
    assert sent is False
    assert mock_email_provider.sent_emails == []


# ── 5. Provider raises → recorded failure, no ghost outbound row ──────────────


def test_provider_failure_records_send_failed_and_no_ghost_row(t1_setup):
    db = t1_setup["db"]
    thread = t1_setup["thread"]
    draft = t1_setup["draft"]
    provider = t1_setup["provider"]

    provider.raise_on_send = RuntimeError("SMTP connection refused")

    sent = maybe_auto_send(db, thread_id=thread.id, draft_id=draft.id)
    assert sent is True  # an attempt was made

    # Re-fetch from DB to see the post-rollback state
    db.expire_all()
    refreshed_draft = db.execute(
        select(DraftResponse).where(DraftResponse.id == draft.id)
    ).scalar_one()
    refreshed_thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread.id)
    ).scalar_one()

    assert refreshed_draft.status == DraftStatus.send_failed
    assert refreshed_thread.status == EmailStatus.draft_ready
    assert refreshed_thread.auto_sent_at is None

    # CRITICAL: no ghost outbound EmailMessage created
    assert _outbound_count(db, thread.id) == 0

    # Audit row recorded
    actions = _audit_actions(db, thread.id)
    assert "thread.auto_send_failed" in actions


# ── 6. Provider returns a different message_id → outbound row updated ─────────


def test_provider_alternate_message_id_updates_outbound(t1_setup, monkeypatch):
    db = t1_setup["db"]
    thread = t1_setup["thread"]
    draft = t1_setup["draft"]
    provider = t1_setup["provider"]

    # Make the provider return an alternate id (overrides the default echo behavior)
    alt_id = "<provider-assigned-9999@server.example.com>"
    original_send = provider.send_email

    def patched_send(**kwargs):
        original_send(**kwargs)
        return alt_id

    monkeypatch.setattr(provider, "send_email", patched_send)

    sent = maybe_auto_send(db, thread_id=thread.id, draft_id=draft.id)
    assert sent is True

    db.expire_all()
    outbound = db.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == MessageDirection.outbound,
        )
    ).scalar_one()
    assert outbound.message_id_header == alt_id


# ── 7. Provider returns None → treated as failure (no silent success) ─────────


def test_provider_returns_none_is_treated_as_failure(t1_setup, monkeypatch):
    db = t1_setup["db"]
    thread = t1_setup["thread"]
    draft = t1_setup["draft"]
    provider = t1_setup["provider"]

    # Force send_email to return None despite no exception — defensive contract check
    def returns_none(**kwargs):
        return None

    monkeypatch.setattr(provider, "send_email", returns_none)

    sent = maybe_auto_send(db, thread_id=thread.id, draft_id=draft.id)
    assert sent is True  # we attempted

    db.expire_all()
    refreshed_draft = db.execute(
        select(DraftResponse).where(DraftResponse.id == draft.id)
    ).scalar_one()
    refreshed_thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread.id)
    ).scalar_one()

    # Must NOT have flipped to sent — None is treated as failure
    assert refreshed_draft.status == DraftStatus.send_failed
    assert refreshed_thread.status == EmailStatus.draft_ready
    assert refreshed_thread.auto_sent_at is None
    assert _outbound_count(db, thread.id) == 0
    assert "thread.auto_send_failed" in _audit_actions(db, thread.id)


# ── 8. Happy path: gates open + provider succeeds → email sent ────────────────


def test_success_path_records_sent_and_audit(t1_setup):
    db = t1_setup["db"]
    thread = t1_setup["thread"]
    draft = t1_setup["draft"]
    provider = t1_setup["provider"]

    sent = maybe_auto_send(db, thread_id=thread.id, draft_id=draft.id)
    assert sent is True

    db.expire_all()
    refreshed_draft = db.execute(
        select(DraftResponse).where(DraftResponse.id == draft.id)
    ).scalar_one()
    refreshed_thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread.id)
    ).scalar_one()

    assert refreshed_draft.status == DraftStatus.sent
    assert refreshed_thread.status == EmailStatus.sent
    assert refreshed_thread.auto_sent_at is not None
    assert _outbound_count(db, thread.id) == 1

    # Provider was actually called once with the right recipient
    assert len(provider.sent_emails) == 1
    assert provider.sent_emails[0]["to"] == thread.client_email
    assert provider.sent_emails[0]["subject"].lower().startswith("re:")

    # High-visibility audit entry exists
    assert "thread.auto_sent" in _audit_actions(db, thread.id)


# ── 9. Defensive: zero inbound messages refuses to send ───────────────────────


def test_thread_with_no_inbound_refuses_to_send(db_session, mock_email_provider):
    _enable_auto_send(db_session)
    thread = _make_t1_thread(db_session)
    # Intentionally NO inbound message added
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    sent = maybe_auto_send(db_session, thread_id=thread.id, draft_id=draft.id)
    assert sent is False  # skipped, not failed
    assert mock_email_provider.sent_emails == []
    # No audit row for an attempt that didn't happen
    assert "thread.auto_sent" not in _audit_actions(db_session, thread.id)
    assert "thread.auto_send_failed" not in _audit_actions(db_session, thread.id)
