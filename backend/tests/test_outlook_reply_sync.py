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

import pytest

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


def _add_inbound(
    thread_id: str,
    *,
    received_at: datetime,
    sender: str = "Client <client@example.com>",
) -> None:
    """Add an ADDITIONAL inbound message to a thread already seeded by
    _seed_thread (which creates the first one) — used to build a
    multi-message timeline (e.g. a client follow-up after an app reply)."""
    db = _db_mod.SessionLocal()
    try:
        db.add(EmailMessage(
            thread_id=uuid.UUID(thread_id),
            message_id_header=_uid("inbound2"),
            sender=sender,
            recipient="firm@example.com",
            body_text="Follow-up.",
            received_at=received_at,
            direction=MessageDirection.inbound,
            is_processed=True,
            raw_headers={},
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


def _get_error_streak() -> int:
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, f"{CURSOR_KEY}:error_streak")
        return int(row.value) if row and row.value else 0
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


class _FakeDraftGenerator:
    """
    Stands in for the real DraftGenerator at the exact seam
    _generate_draft_for_thread uses (a module-level factory function,
    imported locally at call time). Records every call so the test can
    assert it's never invoked — the real generator would otherwise fail
    silently on a network call in this test environment, which would let
    a broken Phase-2 guard pass unnoticed (T1: the real generator "creates
    no draft" isn't proof the guard fired; a stub that WOULD create one is).
    """
    def __init__(self):
        self.calls: list[uuid.UUID] = []

    def generate(self, db, thread):
        self.calls.append(thread.id)
        draft = DraftResponse(
            thread_id=thread.id, body_text="fake ai draft", status=DraftStatus.pending
        )
        db.add(draft)
        db.flush()
        thread.status = EmailStatus.draft_ready
        return draft


@pytest.mark.parametrize("has_body", [True, False])
def test_poll_once_reply_sync_prevents_same_cycle_duplicate_draft_and_send(
    mock_email_provider, monkeypatch, has_body,
):
    """
    F1 regression: within a SINGLE poll_once cycle, Phase 1 ingests a new
    inbound message on a thread that reply-sync (running right after Phase
    1, before Phase 2) then matches and flips to `sent` because Jane
    answered it directly in Outlook. Phase 2 must not generate — and
    therefore never auto-send — a duplicate draft for that thread, whether
    or not reply-sync managed to store a local copy of the reply's body
    (parametrized: `applied` vs `applied_message_unstored`).

    Categorization and escalation are mocked out at the same seam
    tests/test_e2e_happy_path.py uses (`get_categorizer` / `get_escalation_engine`
    patched directly) rather than the real Anthropic-shaped `mock_anthropic`
    fixture — going through the real LLM client here would also engage the
    real `ai_budget` gate, which opens its own nested `SessionLocal()` mid
    Phase-1-transaction and is unrelated to what this test is verifying.

    Tier is forced to t1_auto with auto-send enabled (real TierRule +
    SystemSetting rows — decide_tier and maybe_auto_send are NOT mocked) so
    a broken guard would be caught end-to-end: a duplicate draft AND a
    duplicate auto-sent email, not just a draft that a stubbed generator
    happens to create.
    """
    monkeypatch.setattr(ei.settings, "outlook_reply_sync", True)
    monkeypatch.setattr(ei.settings, "draft_auto_generate", True)
    _upsert_cursor("poll-cur-0")

    conv = _conv()
    client_email = "client@example.com"
    now = datetime.now(timezone.utc)

    from tests.conftest import make_raw_email
    inbound_at = now - timedelta(minutes=5)
    raw = make_raw_email(
        message_id=_uid("poll-inbound"),
        sender=f"Client <{client_email}>",
        received_at=inbound_at,
        provider_thread_id=conv,
    )
    mock_email_provider.fetch_new_emails = lambda: [raw]

    item = _sent_item(conversation_id=conv, to=[client_email], sent_at=now)
    if has_body:
        _stub_graph_message(mock_email_provider, item.graph_id)
    mock_email_provider.sent_delta_results = ([item], "poll-cur-1")

    from unittest.mock import MagicMock, patch
    from app.schemas.email import CategorizationResult
    from app.models.system_setting import SystemSetting
    from app.models.tier_rule import TierRule
    from app.services import system_settings as ss
    from sqlalchemy import delete

    mock_cat = MagicMock()
    mock_cat.categorize.return_value = CategorizationResult(
        category=EmailCategory.general_inquiry,
        confidence=0.9,
        escalation_needed=False,
        summary="Client has a general question.",
    )
    mock_esc_engine = MagicMock()
    mock_esc_engine.process.return_value = None
    fake_gen = _FakeDraftGenerator()

    db = _db_mod.SessionLocal()
    try:
        db.add(TierRule(category=EmailCategory.general_inquiry, t1_eligible=True, t1_min_confidence=0.5))
        db.execute(delete(SystemSetting).where(SystemSetting.key == ss.AUTO_SEND_ENABLED))
        db.add(SystemSetting(key=ss.AUTO_SEND_ENABLED, value="true"))
        db.commit()
    finally:
        db.close()

    try:
        with patch("app.services.email_intake.get_categorizer", return_value=mock_cat), \
             patch("app.services.email_intake.get_escalation_engine", return_value=mock_esc_engine), \
             patch("app.services.draft_generator.get_draft_generator", return_value=fake_gen):
            processed = ei.poll_once()

        assert processed == 1  # Phase 1 still ingested the inbound message
        assert fake_gen.calls == []  # Phase 2 must never reach the generator

        db = _db_mod.SessionLocal()
        try:
            thread = db.execute(
                select(EmailThread).where(EmailThread.provider_thread_id == conv)
            ).scalar_one()
            tid = thread.id
            assert thread.status == EmailStatus.sent
            drafts = db.execute(
                select(DraftResponse).where(DraftResponse.thread_id == tid)
            ).scalars().all()
        finally:
            db.close()

        assert drafts == []  # Phase 2 must not have generated a draft
        assert mock_email_provider.sent_emails == []  # ...and never auto-sent one
    finally:
        # This test seeds global (not per-record) state — a TierRule keyed
        # on the category and the AUTO_SEND_ENABLED system setting — that
        # other tests assume is absent/false by default. Clean up so nothing
        # leaks into the rest of the shared-DB test session.
        db = _db_mod.SessionLocal()
        try:
            db.execute(
                delete(TierRule).where(TierRule.category == EmailCategory.general_inquiry)
            )
            db.execute(delete(SystemSetting).where(SystemSetting.key == ss.AUTO_SEND_ENABLED))
            db.commit()
        finally:
            db.close()


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


def test_cursor_does_not_advance_past_a_batch_with_an_error(mock_email_provider):
    """
    F4: Graph's delta cursor is a one-way pointer — it can't retry "just
    that one item." If any item in the batch errors, the cursor must stay
    put so next poll re-fetches and retries the WHOLE batch (safe because
    every step is idempotent).
    """
    _upsert_cursor("sent-link-0")
    good_item = _sent_item(conversation_id=_conv(), to=["client@example.com"])
    bad_item = object()
    mock_email_provider.sent_delta_results = ([bad_item, good_item], "sent-link-1")

    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("error") == 1
    assert _get_cursor() == "sent-link-0"  # NOT advanced to sent-link-1


def test_cursor_advances_when_the_batch_is_clean(mock_email_provider):
    """Sanity counterpart to the above: a batch with no errors still
    advances the cursor normally (no regression from the F4 fix)."""
    _upsert_cursor("sent-link-0")
    item = _sent_item(conversation_id=_conv("ghost"), to=["nobody@example.com"])
    mock_email_provider.sent_delta_results = ([item], "sent-link-1")

    counters = reconcile_outlook_replies(mock_email_provider)

    assert "error" not in counters
    assert _get_cursor() == "sent-link-1"


def test_error_streak_forces_cursor_forward_after_n_polls(mock_email_provider, caplog):
    """
    N1(a): a deterministically-failing item (e.g. a data problem that
    always raises) must not stall the cursor forever. After
    _REPLY_SYNC_MAX_ERROR_STREAK (3) consecutive polls that each had an
    error, the cursor is forced forward and an ERROR is logged with the
    failed graph_id(s).
    """
    import app.services.email_intake as _ei

    _upsert_cursor("streak-cur-0")
    bad_item = object()  # deterministic: always raises AttributeError
    mock_email_provider.sent_delta_results = ([bad_item], "streak-cur-1")

    with caplog.at_level("WARNING", logger="app.services.email_intake"):
        counters1 = reconcile_outlook_replies(mock_email_provider)
        assert counters1.get("error") == 1
        assert _get_cursor() == "streak-cur-0"  # not advanced
        assert _get_error_streak() == 1

        counters2 = reconcile_outlook_replies(mock_email_provider)
        assert counters2.get("error") == 1
        assert _get_cursor() == "streak-cur-0"  # still not advanced
        assert _get_error_streak() == 2

        counters3 = reconcile_outlook_replies(mock_email_provider)
        assert counters3.get("error") == 1

    # Streak hit the cap on the 3rd poll: cursor forced forward, streak reset.
    assert _get_cursor() == "streak-cur-1"
    assert _get_error_streak() == 0

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("forcing" in r.message.lower() for r in error_records), (
        "expected an ERROR log naming the forced cursor advance"
    )


def test_idempotent_replay_does_not_override_staff_reopen(mock_email_provider, caplog):
    """
    N1(b): a batch containing one deterministically-failing item (holding
    the cursor back below the error-streak cap) and one already-applied-
    but-unstored item must not re-process the second item on replay. If
    staff reopened the thread and wrote a fresh draft in between polls,
    that draft must survive untouched — replaying the same batch is a
    true no-op for an already-applied item, not just "safe to repeat."
    """
    _upsert_cursor("idem-cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)

    good_item = _sent_item(conversation_id=conv, to=["client@example.com"])
    # graph_messages has no entry -> outbound store fails -> applied_message_unstored
    bad_item = object()  # deterministic error, holds the cursor back
    mock_email_provider.sent_delta_results = ([bad_item, good_item], "idem-cur-1")

    with caplog.at_level("WARNING", logger="app.services.email_intake"):
        # Poll 1: escalation resolved, thread flipped to sent (first, real
        # application of the unstored item); the bad item errors.
        counters1 = reconcile_outlook_replies(mock_email_provider)
        assert counters1.get("applied_message_unstored") == 1
        assert counters1.get("error") == 1
        assert _escalation(esc_id).status == EscalationStatus.resolved
        assert _thread(tid).status == EmailStatus.sent
        assert _get_cursor() == "idem-cur-0"  # held back by the bad item

        # Staff reopens the thread and writes a fresh draft — simulating
        # exactly the QA repro.
        db = _db_mod.SessionLocal()
        try:
            thread = db.get(EmailThread, uuid.UUID(tid))
            thread.status = EmailStatus.pending_review
            db.commit()
        finally:
            db.close()
        staff_draft_id = _add_draft(tid, status=DraftStatus.pending)

        # Poll 2: SAME batch redelivered (cursor unchanged). The good item
        # must be recognized as already-applied and skipped — NOT retire
        # the staff's new draft or flip status back to sent.
        counters2 = reconcile_outlook_replies(mock_email_provider)
        assert counters2.get("error") == 1
        assert _get_cursor() == "idem-cur-0"  # still held back (streak=2)

        # Poll 3: streak hits the cap — cursor forced forward.
        reconcile_outlook_replies(mock_email_provider)

    assert _get_cursor() == "idem-cur-1"
    # The staff's draft and status survived every replay untouched.
    assert _draft(staff_draft_id).status == DraftStatus.pending
    assert _thread(tid).status == EmailStatus.pending_review


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


def test_app_send_window_does_not_dedupe_a_reply_to_a_later_followup(mock_email_provider):
    """
    F2 regression: an app-sent reply from a PRIOR round must not falsely
    dedupe a genuine new Outlook reply to a later client follow-up, purely
    because both happen to fall within ±10 minutes of EACH OTHER in
    absolute time. Only an outbound message at or after the latest inbound
    message can be that reply's own echo.

    Timeline: app reply at -8m (to the thread's original inbound), client
    follow-up at -5m, Jane's genuine Outlook reply (to the follow-up) at
    -1m. -8m and -1m are 7 minutes apart (within the window), but the -8m
    app-send predates the -5m follow-up it doesn't answer.
    """
    _upsert_cursor("cur-0")
    conv = _conv()
    now = datetime.now(timezone.utc)
    tid = _seed_thread(
        conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate,
        inbound_at=now - timedelta(minutes=20),
    )
    esc_id = _add_escalation(tid)

    _add_outbound(
        tid, received_at=now - timedelta(minutes=8),
        to=["client@example.com"], message_id=_uid("app-reply-1"),
    )
    _add_inbound(tid, received_at=now - timedelta(minutes=5))  # client follow-up

    item = _sent_item(
        conversation_id=conv, to=["client@example.com"],
        sent_at=now - timedelta(minutes=1),
    )
    _stub_graph_message(mock_email_provider, item.graph_id)
    mock_email_provider.sent_delta_results = ([item], "cur-1")

    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("applied") == 1
    assert _escalation(esc_id).status == EscalationStatus.resolved


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


def test_step9_integrity_error_does_not_undo_escalation_or_draft(mock_email_provider):
    """
    F3: a genuine IntegrityError at step 9 — the graph-fetched body's own
    message_id collides with a row that already exists (simulating a race:
    something else stored a message under that header between step 3's
    idempotency check and this flush) — must not roll back steps 6-8, and
    the batch must continue to the next item.
    """
    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc_id = _add_escalation(tid)
    draft_id = _add_draft(tid, status=DraftStatus.pending)

    # A pre-existing row whose header collides with what fetch_message_by_
    # graph_id will return for this item — NOT the same as item's own
    # internet_message_id, so step 3's idempotency check doesn't catch it
    # first; the collision only surfaces when step 9 tries to insert it.
    colliding_mid = _uid("collision")
    _add_outbound(tid, received_at=datetime.now(timezone.utc), message_id=colliding_mid)

    item = _sent_item(
        conversation_id=conv, to=["client@example.com"],
        internet_message_id=_uid("distinct-from-collision"),
    )
    _stub_graph_message(mock_email_provider, item.graph_id, message_id=colliding_mid)

    # A second, independent item in the same batch proves the batch
    # continues past this item's failure.
    conv2 = _conv("second")
    tid2 = _seed_thread(conversation_id=conv2, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    esc2_id = _add_escalation(tid2)
    item2 = _sent_item(conversation_id=conv2, to=["client@example.com"])
    _stub_graph_message(mock_email_provider, item2.graph_id)

    mock_email_provider.sent_delta_results = ([item, item2], "cur-1")
    counters = reconcile_outlook_replies(mock_email_provider)

    assert counters.get("applied_message_unstored") == 1
    assert counters.get("applied") == 1
    assert _escalation(esc_id).status == EscalationStatus.resolved
    assert _draft(draft_id).status == DraftStatus.rejected
    assert _thread(tid).status == EmailStatus.sent
    assert _escalation(esc2_id).status == EscalationStatus.resolved


def test_reconcile_never_calls_graph_write_methods(mock_email_provider, monkeypatch):
    """
    F3: reply-sync is read-only toward Outlook. Spy on every write-capable
    provider method and assert none are called across a run that resolves
    an escalation, retires a draft, and flips the thread to sent.
    """
    graph_write_calls: list[str] = []

    def _spy(name):
        def _inner(*args, **kwargs):
            graph_write_calls.append(name)
        return _inner

    for method_name in (
        "send_email", "move_message", "forward_message", "mark_as_read",
        "find_or_create_folder", "move_message_to_folder",
    ):
        monkeypatch.setattr(
            mock_email_provider, method_name, _spy(method_name), raising=False
        )

    _upsert_cursor("cur-0")
    conv = _conv()
    tid = _seed_thread(conversation_id=conv, status=EmailStatus.escalated, tier=ThreadTier.t3_escalate)
    _add_escalation(tid)
    _add_draft(tid, status=DraftStatus.pending)

    item = _sent_item(conversation_id=conv, to=["client@example.com"])
    _stub_graph_message(mock_email_provider, item.graph_id)
    mock_email_provider.sent_delta_results = ([item], "cur-1")

    reconcile_outlook_replies(mock_email_provider)

    assert graph_write_calls == []
    assert _thread(tid).status == EmailStatus.sent  # confirms real work happened


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

    def test_api_badge_matches_list_total_across_all_statuses(self, logged_in_staff):
        """
        End-to-end API-level D1 parity (F3): seed a thread for every
        EmailStatus value in both to-do tiers, then assert
        /dashboard/stats' t2/t3 badge counts equal /emails?tier=...'s
        `total` — the same predicate must produce the same number whichever
        endpoint computes it. Parity is asserted as a relative equality (not
        an absolute count), so this test is unaffected by threads other
        tests have already accumulated in the shared test DB.
        """
        for tier in (ThreadTier.t2_review, ThreadTier.t3_escalate):
            for st in EmailStatus:
                _seed_thread(conversation_id=_conv(), status=st, tier=tier)

        stats = logged_in_staff.get("/api/v1/dashboard/stats")
        assert stats.status_code == 200, stats.text
        badges = stats.json()["threads_by_tier"]

        list_t2 = logged_in_staff.get(
            "/api/v1/emails", params={"tier": "t2_review", "page_size": 100}
        )
        list_t3 = logged_in_staff.get(
            "/api/v1/emails", params={"tier": "t3_escalate", "page_size": 100}
        )
        assert list_t2.status_code == 200, list_t2.text
        assert list_t3.status_code == 200, list_t3.text

        assert badges["t2_review"] == list_t2.json()["total"]
        assert badges["t3_escalate"] == list_t3.json()["total"]

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
