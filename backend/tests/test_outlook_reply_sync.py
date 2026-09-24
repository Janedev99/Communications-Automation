"""
Outlook → app reply-sync (FEAT/outlook-reply-sync, Feature A, 2026-09-24).

Covers the reconcile logic that reflects a reply Jane sends directly from
Outlook back into the app: delta-query Sent Items, match by conversationId,
resolve open escalations, retire sendable drafts, flip the thread to `sent`,
and store a local copy of the reply. Provider I/O is faked via
RecordingEmailProvider.delta_sent_messages / fetch_message_by_graph_id (see
conftest); these tests exercise matching, guards, idempotency, the D1 lane
predicate, and flag-gating.

Also covers the D1 lane-predicate/badge parity (services/todo_queue) since
it ships in the same iteration and the reply-sync tests already build the
tier/status fixtures this predicate needs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.database as _db_mod
import app.services.email_intake as ei
from app.models.audit import AuditLog
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    SyncState,
    ThreadTier,
)
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.services.email_intake import reconcile_outlook_replies
from app.services.email_provider import IMAPProvider, SentItem
from app.services.todo_queue import badge_clause, lane_clause
from sqlalchemy import select

CURSOR_KEY = "delta:sentitems"


# ── helpers ───────────────────────────────────────────────────────────────────

def _uid(prefix: str) -> str:
    return f"<{prefix}-{uuid.uuid4().hex[:12]}@example.com>"


def _conv(prefix: str = "conv") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _seed_thread(
    *,
    conversation_id: str,
    client_email: str = "client@example.com",
    status: EmailStatus = EmailStatus.escalated,
    tier: ThreadTier = ThreadTier.t3_escalate,
    inbound_at: datetime | None = None,
) -> str:
    """Create a thread with one inbound message. Returns thread id (str)."""
    db = _db_mod.SessionLocal()
    try:
        thread = EmailThread(
            subject="Reply-sync subject",
            client_email=client_email,
            status=status,
            category=EmailCategory.general_inquiry,
            tier=tier,
            provider_thread_id=conversation_id,
        )
        db.add(thread)
        db.flush()
        db.add(EmailMessage(
            thread_id=thread.id,
            message_id_header=_uid("inbound"),
            sender=f"Client <{client_email}>",
            recipient="firm@example.com",
            body_text="Client question.",
            received_at=inbound_at or datetime.now(timezone.utc),
            direction=MessageDirection.inbound,
            is_processed=True,
            raw_headers={},
        ))
        db.commit()
        return str(thread.id)
    finally:
        db.close()


def _add_escalation(thread_id: str, *, status: EscalationStatus = EscalationStatus.pending) -> str:
    db = _db_mod.SessionLocal()
    try:
        esc = Escalation(
            thread_id=uuid.UUID(thread_id),
            reason="test escalation",
            severity=EscalationSeverity.medium,
            status=status,
        )
        db.add(esc)
        db.commit()
        return str(esc.id)
    finally:
        db.close()


def _add_draft(thread_id: str, *, status: DraftStatus = DraftStatus.pending) -> str:
    db = _db_mod.SessionLocal()
    try:
        draft = DraftResponse(
            thread_id=uuid.UUID(thread_id),
            body_text="Draft body.",
            status=status,
        )
        db.add(draft)
        db.commit()
        return str(draft.id)
    finally:
        db.close()


def _add_outbound(
    thread_id: str,
    *,
    received_at: datetime,
    to: list[str] | None = None,
    recipient: str | None = None,
    message_id: str | None = None,
) -> None:
    db = _db_mod.SessionLocal()
    try:
        db.add(EmailMessage(
            thread_id=uuid.UUID(thread_id),
            message_id_header=message_id or _uid("outbound"),
            sender="firm@example.com",
            recipient=recipient,
            to_recipients=to,
            body_text="Firm reply.",
            received_at=received_at,
            direction=MessageDirection.outbound,
            is_processed=True,
        ))
        db.commit()
    finally:
        db.close()


def _thread(thread_id: str) -> EmailThread:
    db = _db_mod.SessionLocal()
    try:
        return db.get(EmailThread, uuid.UUID(thread_id))
    finally:
        db.close()


def _escalation(escalation_id: str) -> Escalation:
    db = _db_mod.SessionLocal()
    try:
        return db.get(Escalation, uuid.UUID(escalation_id))
    finally:
        db.close()


def _draft(draft_id: str) -> DraftResponse:
    db = _db_mod.SessionLocal()
    try:
        return db.get(DraftResponse, uuid.UUID(draft_id))
    finally:
        db.close()


def _outbound_messages(thread_id: str) -> list[EmailMessage]:
    db = _db_mod.SessionLocal()
    try:
        return (
            db.execute(
                select(EmailMessage).where(
                    EmailMessage.thread_id == uuid.UUID(thread_id),
                    EmailMessage.direction == MessageDirection.outbound,
                )
            )
            .scalars()
            .all()
        )
    finally:
        db.close()


def _reset_cursor() -> None:
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, CURSOR_KEY)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def _upsert_cursor(value: str) -> None:
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, CURSOR_KEY)
        if row is None:
            db.add(SyncState(key=CURSOR_KEY, value=value))
        else:
            row.value = value
        db.commit()
    finally:
        db.close()


def _get_cursor() -> str | None:
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, CURSOR_KEY)
        return row.value if row else None
    finally:
        db.close()


def _audit_count(entity_id: str, action: str) -> int:
    db = _db_mod.SessionLocal()
    try:
        rows = db.execute(
            select(AuditLog).where(AuditLog.entity_id == entity_id)
        ).scalars().all()
        return sum(1 for r in rows if r.action == action)
    finally:
        db.close()


def _sent_item(
    *,
    conversation_id: str,
    to: list[str],
    cc: list[str] | None = None,
    sent_at: datetime | None = None,
    internet_message_id: str | None = None,
    graph_id: str | None = None,
) -> SentItem:
    return SentItem(
        graph_id=graph_id or f"graph-{uuid.uuid4().hex[:12]}",
        internet_message_id=internet_message_id,
        conversation_id=conversation_id,
        sent_at=sent_at or datetime.now(timezone.utc),
        to=to,
        cc=cc or [],
        subject="Re: test",
    )


def _stub_graph_message(provider, graph_id: str, **overrides) -> None:
    """Register a fetchable body for `graph_id` on the fake provider so step 9
    (outbound-message storage) succeeds instead of degrading to
    'applied_message_unstored'."""
    from tests.conftest import make_raw_email
    provider.graph_messages[graph_id] = make_raw_email(
        message_id=overrides.pop("message_id", _uid("real")),
        sender=overrides.pop("sender", "Client <client@example.com>"),
        **overrides,
    )


# ── flag / baseline / cursor ──────────────────────────────────────────────────

def test_poll_respects_the_flag(mock_email_provider, monkeypatch):
    """poll_once only runs reply-sync when OUTLOOK_REPLY_SYNC is on."""
    monkeypatch.setattr(ei.settings, "outlook_reply_sync", False)
    mock_email_provider.sent_delta_calls.clear()
    ei.poll_once()
    assert mock_email_provider.sent_delta_calls == []

    monkeypatch.setattr(ei.settings, "outlook_reply_sync", True)
    mock_email_provider.sent_delta_calls.clear()
    ei.poll_once()
    assert len(mock_email_provider.sent_delta_calls) == 1


def test_first_run_is_baseline_only(mock_email_provider):
    """No stored cursor -> capture the deltaLink but act on nothing."""
    _reset_cursor()
    conv = _conv()
    tid = _seed_thread(conversation_id=conv)
    esc_id = _add_escalation(tid)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    mock_email_provider.sent_delta_results = ([item], "sent-link-1")

    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters == {}
    assert _thread(tid).status == EmailStatus.escalated  # untouched
    assert _escalation(esc_id).status == EscalationStatus.pending  # untouched
    assert _get_cursor() == "sent-link-1"


def test_cursor_is_passed_back_on_next_run(mock_email_provider):
    _upsert_cursor("sent-link-A")
    mock_email_provider.sent_delta_results = ([], "sent-link-B")
    mock_email_provider.sent_delta_calls.clear()

    reconcile_outlook_replies(mock_email_provider)

    assert mock_email_provider.sent_delta_calls[0]["delta_link"] == "sent-link-A"
    assert _get_cursor() == "sent-link-B"


def test_delta_failure_is_isolated(mock_email_provider):
    _upsert_cursor("sent-link-0")
    mock_email_provider.raise_on_sent_delta = RuntimeError("graph 503")

    counters = reconcile_outlook_replies(mock_email_provider)  # must not raise

    assert counters == {}
    assert _get_cursor() == "sent-link-0"  # cursor untouched


# ── core reconcile behaviour ───────────────────────────────────────────────────

def test_escalation_resolved_and_thread_marked_sent(mock_email_provider):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(
        conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate
    )
    esc_id = _add_escalation(tid)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    _stub_graph_message(mock_email_provider, item.graph_id)
    mock_email_provider.sent_delta_results = ([item], "cur-1")

    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("applied") == 1
    esc = _escalation(esc_id)
    assert esc.status == EscalationStatus.resolved
    assert esc.resolved_by_id is None
    assert esc.resolution_notes == "Replied in Outlook"

    thread = _thread(tid)
    assert thread.status == EmailStatus.sent
    assert thread.tier == ThreadTier.t3_escalate  # tier untouched (D1 clears the lane, not tier)

    assert _audit_count(esc_id, "escalation.resolved_via_outlook_reply") == 1
    assert _audit_count(tid, "email.sent_via_outlook_reply") == 1


def test_draft_retirement_for_all_four_statuses(mock_email_provider):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.categorized, tier=ThreadTier.t2_review)
    draft_ids = {
        s: _add_draft(tid, status=s)
        for s in (DraftStatus.pending, DraftStatus.edited, DraftStatus.approved, DraftStatus.send_failed)
    }

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    reconcile_outlook_replies(mock_email_provider)

    for status, did in draft_ids.items():
        draft = _draft(did)
        assert draft.status == DraftStatus.rejected, f"{status} draft was not retired"
        assert draft.rejection_reason is None
        assert draft.reviewed_by_id is None
        assert _audit_count(did, "draft.retired_via_outlook_reply") == 1


def test_retired_drafts_excluded_from_negative_patterns(mock_email_provider, db_session):
    """
    A retired draft's rejection_reason is NULL — get_negative_patterns'
    query filters on ``rejection_reason.isnot(None)``, so this row must never
    surface as a "negative example" the AI learns from.

    Scoped to exactly this draft (rather than asserting the service's full
    return list is empty) because the shared test DB accumulates real
    rejected-with-reason drafts from other test modules (e.g.
    test_draft_feedback.py) — asserting global emptiness would be flaky.
    """
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.categorized, tier=ThreadTier.t2_review)
    draft_id = _add_draft(tid, status=DraftStatus.pending)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    reconcile_outlook_replies(mock_email_provider)

    retired = _draft(draft_id)
    assert retired.status == DraftStatus.rejected
    assert retired.rejection_reason is None

    matched = db_session.execute(
        select(DraftResponse).where(
            DraftResponse.id == uuid.UUID(draft_id),
            DraftResponse.status == DraftStatus.rejected,
            DraftResponse.rejection_reason.isnot(None),
        )
    ).scalar_one_or_none()
    assert matched is None, (
        "retired draft has a NULL reason and must not match the "
        "get_negative_patterns predicate"
    )


def test_409_on_send_of_retired_draft(mock_email_provider, logged_in_staff):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.categorized, tier=ThreadTier.t2_review)
    draft_id = _add_draft(tid, status=DraftStatus.approved)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    reconcile_outlook_replies(mock_email_provider)
    assert _draft(draft_id).status == DraftStatus.rejected

    resp = logged_in_staff.post(f"/api/v1/emails/{tid}/drafts/{draft_id}/send")
    assert resp.status_code == 409

    resp2 = logged_in_staff.post(f"/api/v1/emails/{tid}/drafts/{draft_id}/approve")
    assert resp2.status_code == 409


def test_outbound_storage(mock_email_provider):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.categorized, tier=ThreadTier.t2_review)

    graph_id = "graph-real-1"
    real_mid = _uid("real")
    from tests.conftest import make_raw_email
    mock_email_provider.graph_messages[graph_id] = make_raw_email(
        message_id=real_mid,
        sender="Client <client@example.com>",
        body_text="Thanks, all set.",
    )

    item = _sent_item(
        conversation_id=conv, to=["client@example.com"], graph_id=graph_id,
        internet_message_id=real_mid,
    )
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("applied") == 1
    outbound = _outbound_messages(tid)
    assert len(outbound) == 1
    assert outbound[0].message_id_header == real_mid
    assert outbound[0].raw_headers.get("X-AutoComms-Source") == "outlook-reply-sync"
    assert outbound[0].body_text == "Thanks, all set."


def test_idempotency_skips_already_stored_message(mock_email_provider):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)
    dup_mid = _uid("dup")
    _add_outbound(tid, received_at=datetime.now(timezone.utc), message_id=dup_mid, to=["client@example.com"])

    item = _sent_item(conversation_id=conv, to=["client@example.com"], internet_message_id=dup_mid)
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("skipped_idempotent") == 1
    # Nothing beyond the pre-existing message was applied.
    assert _escalation(esc_id).status == EscalationStatus.pending
    assert len(_outbound_messages(tid)) == 1


def test_app_send_window_skips(mock_email_provider):
    """An app-generated outbound within ±10 minutes sharing a recipient is
    treated as our own send echoing back, not a separate Outlook reply."""
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)
    now = datetime.now(timezone.utc)
    # App sends often carry a local correlation id, not the real internetMessageId
    # (see design doc §0.2) — this app-send's id deliberately does NOT match
    # the SentItem's internet_message_id, so only the time+recipient window
    # can catch it.
    _add_outbound(tid, received_at=now, to=["client@example.com"], message_id=_uid("local-correlation"))

    item = _sent_item(
        conversation_id=conv, to=["client@example.com"],
        sent_at=now + timedelta(minutes=3),
        internet_message_id=_uid("real-exchange-id"),
    )
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("skipped_app_send") == 1
    assert _escalation(esc_id).status == EscalationStatus.pending


def test_forward_is_skipped(mock_email_provider):
    """A reply addressed to a third party (forward) shares the conversationId
    but not a recipient with the client — must not resolve the escalation."""
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(
        conversation_id=conv, client_email="client@example.com",
        status=EmailStatus.escalated, tier=ThreadTier.t3_escalate,
    )
    esc_id = _add_escalation(tid)

    item = _sent_item(conversation_id=conv, to=["colleague@otherfirm.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("skipped_not_to_client") == 1
    assert _escalation(esc_id).status == EscalationStatus.pending
    assert _thread(tid).status == EmailStatus.escalated


def test_superseded_by_newer_inbound_message(mock_email_provider):
    """D3: a client message that arrived after this reply was sent means the
    work is still open — key on message time, not escalation.created_at."""
    _upsert_cursor("cur-0")
    conv = _conv()
    now = datetime.now(timezone.utc)
    tid = _seed_thread(conversation_id=conv, inbound_at=now, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)

    item = _sent_item(
        conversation_id=conv, to=["client@example.com"], sent_at=now - timedelta(hours=1)
    )
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("skipped_superseded") == 1
    assert _escalation(esc_id).status == EscalationStatus.pending
    assert _thread(tid).status == EmailStatus.escalated


def test_unmatched_conversation_is_skipped(mock_email_provider):
    _upsert_cursor("cur-0")
    item = _sent_item(conversation_id=_conv("ghost"), to=["nobody@example.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")

    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("skipped_no_thread") == 1
    assert _get_cursor() == "cur-1"  # cursor still advances


def test_closed_thread_keeps_status_but_drafts_retired(mock_email_provider):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.closed, tier=ThreadTier.t2_review)
    draft_id = _add_draft(tid, status=DraftStatus.pending)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    reconcile_outlook_replies(mock_email_provider)

    assert _thread(tid).status == EmailStatus.closed  # unchanged
    assert _draft(draft_id).status == DraftStatus.rejected  # still retired


def test_deleted_thread_keeps_status_but_escalation_resolved(mock_email_provider):
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.deleted, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    reconcile_outlook_replies(mock_email_provider)

    assert _thread(tid).status == EmailStatus.deleted  # unchanged
    assert _escalation(esc_id).status == EscalationStatus.resolved  # still resolved


def test_body_fetch_failure_does_not_undo_escalation_or_draft(mock_email_provider):
    """fetch_message_by_graph_id returning None (Graph error / message gone)
    must not roll back the escalation-resolve / draft-retire steps."""
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)
    draft_id = _add_draft(tid, status=DraftStatus.pending)

    # graph_messages has no entry for this graph_id -> fetch returns None
    item = _sent_item(conversation_id=conv, to=["client@example.com"], graph_id="graph-missing")
    mock_email_provider.sent_delta_results = ([item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("applied_message_unstored") == 1
    assert _escalation(esc_id).status == EscalationStatus.resolved
    assert _draft(draft_id).status == DraftStatus.rejected
    assert _thread(tid).status == EmailStatus.sent
    assert _outbound_messages(tid) == []


def test_a_bad_item_does_not_derail_the_rest_of_the_batch(mock_email_provider, monkeypatch):
    """One item raising unexpectedly is isolated (its own savepoint) so a
    second, well-formed item in the same batch still gets applied."""
    _upsert_cursor("cur-0")
    conv_good = _conv("good")
    tid_good = _seed_thread(conversation_id=conv_good, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc_good = _add_escalation(tid_good)

    good_item = _sent_item(conversation_id=conv_good, to=["client@example.com"])
    _stub_graph_message(mock_email_provider, good_item.graph_id)
    bad_item = object()  # malformed "item" — has no .conversation_id etc.

    mock_email_provider.sent_delta_results = ([bad_item, good_item], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("error") == 1
    assert counters.get("applied") == 1
    assert _escalation(esc_good).status == EscalationStatus.resolved


# ── IMAP no-op ─────────────────────────────────────────────────────────────────

def test_imap_provider_is_noop():
    from app.config import get_settings
    provider = IMAPProvider(get_settings())
    assert provider.delta_sent_messages(delta_link="X") == ([], "X")
    assert provider.fetch_message_by_graph_id("anything") is None


# ── D1: lane predicate / badge parity ─────────────────────────────────────────

class TestD1LanePredicate:
    def test_t2_lane_excludes_sent_and_closed(self, db_session):
        tid_active = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.categorized, tier=ThreadTier.t2_review
        )
        tid_sent = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.sent, tier=ThreadTier.t2_review
        )
        tid_closed = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.closed, tier=ThreadTier.t2_review
        )

        visible = {
            str(row)
            for row in db_session.execute(
                select(EmailThread.id).where(lane_clause(ThreadTier.t2_review))
            ).scalars().all()
        }
        assert tid_active in visible
        assert tid_sent not in visible
        assert tid_closed not in visible

    def test_t3_lane_matches_status_only_escalation(self, db_session):
        """A thread whose status is `escalated` but whose tier drifted away
        from t3 must still show up (status-only escalation)."""
        tid = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.escalated, tier=ThreadTier.t2_review
        )
        visible = {
            str(row)
            for row in db_session.execute(
                select(EmailThread.id).where(lane_clause(ThreadTier.t3_escalate))
            ).scalars().all()
        }
        assert tid in visible

    def test_t3_lane_excludes_sent_even_with_tier_t3(self, db_session):
        """A t3 thread that got answered (Feature A flips it to `sent`) must
        leave the lane even though tier is still t3_escalate."""
        tid = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.sent, tier=ThreadTier.t3_escalate
        )
        visible = {
            str(row)
            for row in db_session.execute(
                select(EmailThread.id).where(lane_clause(ThreadTier.t3_escalate))
            ).scalars().all()
        }
        assert tid not in visible

    def test_badge_clause_also_excludes_deleted_and_spam(self, db_session):
        tid_spam = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.spam, tier=ThreadTier.t2_review
        )
        tid_deleted = _seed_thread(
            conversation_id=_conv(), status=EmailStatus.deleted, tier=ThreadTier.t2_review
        )
        visible = {
            str(row)
            for row in db_session.execute(
                select(EmailThread.id).where(badge_clause(ThreadTier.t2_review))
            ).scalars().all()
        }
        assert tid_spam not in visible
        assert tid_deleted not in visible

    def test_reply_sync_and_lane_clause_agree(self, mock_email_provider, db_session):
        """End-to-end: after reply-sync resolves+flips a t3 thread, it must no
        longer satisfy lane_clause(t3_escalate) — the badge/list actually clear."""
        _upsert_cursor("cur-0")
        conv = _conv()
        tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
        _add_escalation(tid)

        item = _sent_item(conversation_id=conv, to=["client@example.com"])
        mock_email_provider.sent_delta_results = ([item], "cur-1")
        reconcile_outlook_replies(mock_email_provider)

        visible = {
            str(row)
            for row in db_session.execute(
                select(EmailThread.id).where(lane_clause(ThreadTier.t3_escalate))
            ).scalars().all()
        }
        assert tid not in visible


# ── MSGraph sentitems delta paging + field mapping ────────────────────────────

class _FakeResp:
    def __init__(self, payload: dict):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _make_msgraph_provider():
    """MSGraphProvider with auth + client stubbed so we can drive delta paging
    (mirrors tests/test_email_delete_sync.py's helper of the same name)."""
    from types import SimpleNamespace
    from app.services.email_provider import MSGraphProvider

    settings = SimpleNamespace(
        msgraph_mailbox="jane@example.com",
        msgraph_tenant_id="t",
        msgraph_client_id="c",
        msgraph_client_secret="s",
    )
    provider = MSGraphProvider(settings)
    provider._headers = lambda: {"Authorization": "Bearer test"}
    return provider


def test_msgraph_sent_delta_maps_fields_and_follows_pages():
    """Regression guard for the pure _walk_delta extraction (R-A8): sentitems
    delta must still page via @odata.nextLink to a terminal deltaLink, and
    delta_sent_messages must map each item into a SentItem correctly."""
    provider = _make_msgraph_provider()
    pages = [
        {
            "value": [{
                "id": "graph-1",
                "internetMessageId": "<real-1@x>",
                "conversationId": "conv-1",
                "sentDateTime": "2026-09-20T10:00:00Z",
                "toRecipients": [{"emailAddress": {"address": "client@example.com"}}],
                "ccRecipients": [],
                "subject": "Re: hello",
            }],
            "@odata.nextLink": "PAGE-2",
        },
        {
            "value": [{
                "id": "graph-2",
                "internetMessageId": "<real-2@x>",
                "conversationId": "conv-2",
                "sentDateTime": "2026-09-20T11:00:00Z",
                "toRecipients": [],
                "ccRecipients": [{"emailAddress": {"address": "cc@example.com"}}],
                "subject": "Re: hello 2",
            }],
            "@odata.deltaLink": "DELTA-FINAL",
        },
    ]
    calls: list[dict] = []

    def fake_get(url, headers=None):
        calls.append({"url": url, "headers": headers})
        return _FakeResp(pages[len(calls) - 1])

    provider._client = type("C", (), {"get": staticmethod(fake_get)})()

    items, next_delta = provider.delta_sent_messages(delta_link=None)

    assert next_delta == "DELTA-FINAL"
    assert len(calls) == 2
    assert calls[0]["headers"].get("Prefer") == "odata.maxpagesize=500"
    assert calls[1]["url"] == "PAGE-2"

    assert len(items) == 2
    first, second = items
    assert first.graph_id == "graph-1"
    assert first.internet_message_id == "<real-1@x>"
    assert first.conversation_id == "conv-1"
    assert first.sent_at == datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    assert first.to == ["client@example.com"]
    assert first.cc == []
    assert second.cc == ["cc@example.com"]


def test_msgraph_sent_delta_never_advances_cursor_when_cap_hit():
    """Mirrors the folder-delta cap regression: if pages never terminate in a
    deltaLink, the cursor must not advance."""
    provider = _make_msgraph_provider()
    calls = {"n": 0}

    def fake_get(url, headers=None):
        calls["n"] += 1
        return _FakeResp({"value": [], "@odata.nextLink": "MORE"})

    provider._client = type("C", (), {"get": staticmethod(fake_get)})()

    items, next_delta = provider.delta_sent_messages(delta_link="PRIOR-CURSOR")

    assert next_delta == "PRIOR-CURSOR"
    assert items == []
    assert calls["n"] == 1000
