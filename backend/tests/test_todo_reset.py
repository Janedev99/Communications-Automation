"""
"Start clean" to-do reset (FEAT/start-clean-reset, Feature B, 2026-09-30).

The reset is a cutoff timestamp stored in `system_settings` — no row is
mutated. The to-do surfaces (t2/t3 lanes, their badges, the sidebar
escalation dot, the drafts card, the Escalations page's active view and the
draft catch-up sweep) hide anything with no activity at or after the cutoff.
Analytics, All, search, draft_feedback and the audit log ignore it.

The test DB is shared and accumulates data across tests, so assertions are
either relative (badge == list total) or scoped to rows this test created.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.database as _db_mod
from app.models.audit import AuditLog
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.services import draft_catchup
from app.services import system_settings as ss
from app.services import todo_queue
from app.services.draft_feedback import FeedbackRetrievalService

BASE = "/api/v1/system-settings/todo-reset"

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
OLD = lambda: NOW() - timedelta(days=30)  # noqa: E731


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_cutoff():
    """The cutoff is global state in a shared DB — never leak it across tests."""
    def _wipe():
        db = _db_mod.SessionLocal()
        try:
            for key in (todo_queue.CUTOFF_KEY, todo_queue.CUTOFF_PREVIOUS_KEY):
                row = db.get(ss.SystemSetting, key)
                if row is not None:
                    db.delete(row)
            db.commit()
        finally:
            db.close()
    _wipe()
    yield
    _wipe()


def _set_cutoff(when: datetime, previous: str | None = None) -> None:
    db = _db_mod.SessionLocal()
    try:
        ss.set_setting(db, todo_queue.CUTOFF_KEY, when.isoformat())
        if previous is not None:
            ss.set_setting(db, todo_queue.CUTOFF_PREVIOUS_KEY, previous)
        db.commit()
    finally:
        db.close()


def _mk_thread(
    *,
    status: EmailStatus = EmailStatus.categorized,
    tier: ThreadTier = ThreadTier.t2_review,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    inbound_at: datetime | None = None,
    client_email: str | None = None,
    category: EmailCategory = EmailCategory.general_inquiry,
) -> str:
    """Thread + one inbound message. Defaults to a fully OLD thread."""
    created = created_at or OLD()
    db = _db_mod.SessionLocal()
    try:
        thread = EmailThread(
            subject="Reset test subject",
            client_email=client_email or f"c-{uuid.uuid4().hex[:8]}@example.com",
            status=status,
            category=category,
            tier=tier,
            created_at=created,
            updated_at=updated_at or created,
        )
        db.add(thread)
        db.flush()
        db.add(EmailMessage(
            thread_id=thread.id,
            message_id_header=f"<in-{uuid.uuid4().hex}@example.com>",
            sender=f"Client <{thread.client_email}>",
            recipient="firm@example.com",
            body_text="Question about my return.",
            received_at=inbound_at or created,
            direction=MessageDirection.inbound,
            is_processed=True,
            raw_headers={},
        ))
        db.commit()
        return str(thread.id)
    finally:
        db.close()


def _add_inbound(thread_id: str, *, received_at: datetime) -> None:
    db = _db_mod.SessionLocal()
    try:
        db.add(EmailMessage(
            thread_id=uuid.UUID(thread_id),
            message_id_header=f"<in2-{uuid.uuid4().hex}@example.com>",
            sender="Client <c@example.com>",
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


def _add_outbound(thread_id: str, *, received_at: datetime) -> None:
    db = _db_mod.SessionLocal()
    try:
        db.add(EmailMessage(
            thread_id=uuid.UUID(thread_id),
            message_id_header=f"<out-{uuid.uuid4().hex}@example.com>",
            sender="firm@example.com",
            recipient="c@example.com",
            body_text="Firm reply.",
            received_at=received_at,
            direction=MessageDirection.outbound,
            is_processed=True,
        ))
        db.commit()
    finally:
        db.close()


def _add_escalation(
    thread_id: str,
    *,
    created_at: datetime | None = None,
    status: EscalationStatus = EscalationStatus.pending,
    severity: EscalationSeverity = EscalationSeverity.medium,
) -> str:
    db = _db_mod.SessionLocal()
    try:
        esc = Escalation(
            thread_id=uuid.UUID(thread_id),
            reason="test escalation",
            severity=severity,
            status=status,
            created_at=created_at or OLD(),
        )
        db.add(esc)
        db.commit()
        return str(esc.id)
    finally:
        db.close()


def _add_draft(
    thread_id: str,
    *,
    status: DraftStatus = DraftStatus.pending,
    created_at: datetime | None = None,
    rejection_reason: str | None = None,
) -> str:
    db = _db_mod.SessionLocal()
    try:
        draft = DraftResponse(
            thread_id=uuid.UUID(thread_id),
            body_text="Draft body.",
            status=status,
            created_at=created_at or OLD(),
            rejection_reason=rejection_reason,
        )
        db.add(draft)
        db.commit()
        return str(draft.id)
    finally:
        db.close()


def _bump_updated_at(thread_id: str) -> None:
    db = _db_mod.SessionLocal()
    try:
        t = db.get(EmailThread, uuid.UUID(thread_id))
        t.updated_at = NOW()
        db.commit()
    finally:
        db.close()


def _lane_ids(client, tier: str) -> set[str]:
    resp = client.get("/api/v1/emails", params={"tier": tier, "page_size": 100})
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


def _stats(client) -> dict:
    resp = client.get("/api/v1/dashboard/stats")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit_rows(action: str) -> list[AuditLog]:
    db = _db_mod.SessionLocal()
    try:
        return list(
            db.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
        )
    finally:
        db.close()


# ── 1. no cutoff = today's behavior ───────────────────────────────────────────

def test_no_cutoff_leaves_everything_visible(logged_in_staff):
    old = _mk_thread()
    assert old in _lane_ids(logged_in_staff, "t2_review")
    assert _stats(logged_in_staff)["todo_cutoff_at"] is None


def test_blank_cutoff_value_means_no_cutoff(db_session):
    ss.set_setting(db_session, todo_queue.CUTOFF_KEY, "")
    db_session.commit()
    assert todo_queue.get_cutoff(db_session) is None


def test_get_cutoff_is_timezone_aware_utc(db_session):
    ss.set_setting(db_session, todo_queue.CUTOFF_KEY, "2026-09-30T12:00:00")  # naive
    db_session.commit()
    cutoff = todo_queue.get_cutoff(db_session)
    assert cutoff is not None and cutoff.tzinfo is not None
    assert cutoff.utcoffset() == timedelta(0)


# ── 2. old threads hidden, All / search unaffected ────────────────────────────

def test_old_threads_hidden_from_lanes_but_new_ones_shown(logged_in_staff):
    old2 = _mk_thread(tier=ThreadTier.t2_review)
    old3 = _mk_thread(tier=ThreadTier.t3_escalate, status=EmailStatus.escalated)
    new2 = _mk_thread(tier=ThreadTier.t2_review, created_at=NOW(), inbound_at=NOW())
    _set_cutoff(NOW() - timedelta(hours=1))

    lane2 = _lane_ids(logged_in_staff, "t2_review")
    lane3 = _lane_ids(logged_in_staff, "t3_escalate")
    assert old2 not in lane2 and old3 not in lane3
    assert new2 in lane2


def test_all_and_search_ignore_the_cutoff(logged_in_staff):
    client_email = f"findme-{uuid.uuid4().hex[:8]}@example.com"
    old = _mk_thread(client_email=client_email)
    _set_cutoff(NOW() - timedelta(hours=1))

    # "All" = no tier filter
    resp = logged_in_staff.get("/api/v1/emails", params={"client_email": client_email})
    assert {i["id"] for i in resp.json()["items"]} == {old}
    # Search
    resp = logged_in_staff.get("/api/v1/emails/search", params={"q": client_email})
    assert {i["id"] for i in resp.json()["items"]} == {old}
    # Status dropdown
    resp = logged_in_staff.get(
        "/api/v1/emails", params={"status": "categorized", "client_email": client_email}
    )
    assert {i["id"] for i in resp.json()["items"]} == {old}


# ── 3. resurfacing rules ──────────────────────────────────────────────────────

def test_new_inbound_message_resurfaces_a_hidden_thread(logged_in_staff):
    tid = _mk_thread()
    _set_cutoff(NOW() - timedelta(hours=1))
    assert tid not in _lane_ids(logged_in_staff, "t2_review")

    _add_inbound(tid, received_at=NOW())
    assert tid in _lane_ids(logged_in_staff, "t2_review")


def test_new_outbound_message_does_not_resurface(logged_in_staff):
    tid = _mk_thread()
    _set_cutoff(NOW() - timedelta(hours=1))
    _add_outbound(tid, received_at=NOW())
    assert tid not in _lane_ids(logged_in_staff, "t2_review")


def test_new_escalation_makes_its_thread_visible(logged_in_staff):
    tid = _mk_thread(tier=ThreadTier.t3_escalate, status=EmailStatus.escalated)
    _set_cutoff(NOW() - timedelta(hours=1))
    assert tid not in _lane_ids(logged_in_staff, "t3_escalate")

    _add_escalation(tid, created_at=NOW())
    assert tid in _lane_ids(logged_in_staff, "t3_escalate")


def test_updated_at_bump_does_not_resurface(logged_in_staff):
    tid = _mk_thread()
    _set_cutoff(NOW() - timedelta(hours=1))
    _bump_updated_at(tid)
    assert tid not in _lane_ids(logged_in_staff, "t2_review")


def test_activity_exactly_at_cutoff_is_visible(logged_in_staff):
    cutoff = NOW() - timedelta(hours=1)
    tid = _mk_thread(created_at=cutoff, inbound_at=cutoff)
    _set_cutoff(cutoff)
    assert tid in _lane_ids(logged_in_staff, "t2_review")


# ── 4. badge / list parity (R-B2) ─────────────────────────────────────────────

def test_badge_matches_list_total_with_a_cutoff(logged_in_staff):
    fresh = NOW()
    for tier in (ThreadTier.t2_review, ThreadTier.t3_escalate):
        for st in EmailStatus:
            _mk_thread(tier=tier, status=st)  # old
            _mk_thread(tier=tier, status=st, created_at=fresh, inbound_at=fresh)  # new
    _set_cutoff(NOW() - timedelta(hours=1))

    badges = _stats(logged_in_staff)["threads_by_tier"]
    for tier in ("t2_review", "t3_escalate"):
        listed = logged_in_staff.get(
            "/api/v1/emails", params={"tier": tier, "page_size": 100}
        )
        assert badges[tier] == listed.json()["total"], tier


def test_todo_counts_and_lane_clause_share_one_predicate(db_session):
    _mk_thread()
    _mk_thread(created_at=NOW(), inbound_at=NOW())
    cutoff = NOW() - timedelta(hours=1)
    counts = todo_queue.todo_counts(db_session, cutoff)
    listed = db_session.execute(
        select(EmailThread.id).where(
            todo_queue.badge_clause(ThreadTier.t2_review, cutoff)
        )
    ).scalars().all()
    assert counts.t2_review == len(listed)


# ── 5. escalation, severity, drafts counts ────────────────────────────────────

def test_escalation_severity_and_pending_counts_honour_the_cutoff(logged_in_staff):
    before = _stats(logged_in_staff)
    old_t = _mk_thread(tier=ThreadTier.t3_escalate, status=EmailStatus.escalated)
    old_esc = _add_escalation(old_t, severity=EscalationSeverity.critical)
    new_t = _mk_thread(
        tier=ThreadTier.t3_escalate, status=EmailStatus.escalated,
        created_at=NOW(), inbound_at=NOW(),
    )
    new_esc = _add_escalation(new_t, created_at=NOW(), severity=EscalationSeverity.critical)

    unfiltered = _stats(logged_in_staff)
    assert unfiltered["totals"]["pending_escalations"] == before["totals"]["pending_escalations"] + 2
    assert (
        unfiltered["escalations_by_severity"].get("critical", 0)
        == before["escalations_by_severity"].get("critical", 0) + 2
    )

    _set_cutoff(NOW() - timedelta(hours=1))
    filtered = _stats(logged_in_staff)
    # The sidebar dot / dashboard card must equal the Escalations page's
    # pending list under the same cutoff (R-B2), and only the new one survives.
    listed = logged_in_staff.get(
        "/api/v1/escalations",
        params={"active": "true", "status": "pending", "page_size": 100},
    ).json()
    ids = {e["id"] for e in listed["items"]}
    assert new_esc in ids and old_esc not in ids
    assert filtered["totals"]["pending_escalations"] == listed["total"]

    crit = logged_in_staff.get(
        "/api/v1/escalations",
        params={"active": "true", "severity": "critical", "page_size": 100},
    ).json()
    assert filtered["escalations_by_severity"].get("critical", 0) == crit["total"]


def test_escalation_on_a_visible_thread_is_visible_even_if_old(logged_in_staff):
    """Escalation rows are visible if created >= cutoff OR their thread is."""
    tid = _mk_thread(tier=ThreadTier.t3_escalate, status=EmailStatus.escalated)
    esc_id = _add_escalation(tid)  # old escalation
    _set_cutoff(NOW() - timedelta(hours=1))
    resp = logged_in_staff.get("/api/v1/escalations", params={"active": "true", "page_size": 100})
    assert esc_id not in {e["id"] for e in resp.json()["items"]}

    _add_inbound(tid, received_at=NOW())  # thread resurfaces -> its escalation too
    resp = logged_in_staff.get("/api/v1/escalations", params={"active": "true", "page_size": 100})
    assert esc_id in {e["id"] for e in resp.json()["items"]}


def test_drafts_pending_review_honours_the_cutoff(logged_in_staff):
    old_t = _mk_thread()
    _add_draft(old_t)
    new_t = _mk_thread(created_at=NOW(), inbound_at=NOW())
    _add_draft(new_t, created_at=NOW())
    _add_draft(new_t, created_at=NOW(), status=DraftStatus.sent)  # not pending: never counted

    before = _stats(logged_in_staff)["drafts"]["pending_review"]
    _set_cutoff(NOW() - timedelta(hours=1))
    after = _stats(logged_in_staff)["drafts"]["pending_review"]
    assert after < before
    db = _db_mod.SessionLocal()
    try:
        cutoff = todo_queue.get_cutoff(db)
        visible = db.execute(
            select(DraftResponse.id).where(
                DraftResponse.status.in_([DraftStatus.pending, DraftStatus.edited]),
                todo_queue.draft_visible_clause(cutoff),
            )
        ).scalars().all()
        assert after == len(visible)
    finally:
        db.close()


# ── 6. server-side active view on the Escalations page ────────────────────────

def test_escalations_active_filter_is_server_side(logged_in_staff):
    t = _mk_thread(created_at=NOW(), inbound_at=NOW())
    pending = _add_escalation(t, created_at=NOW())
    ack = _add_escalation(t, created_at=NOW(), status=EscalationStatus.acknowledged)
    resolved = _add_escalation(t, created_at=NOW(), status=EscalationStatus.resolved)

    resp = logged_in_staff.get("/api/v1/escalations", params={"active": "true", "page_size": 100})
    assert resp.status_code == 200
    body = resp.json()
    ids = {e["id"] for e in body["items"]}
    assert {pending, ack} <= ids and resolved not in ids
    # total is the server's own filtered total, not the page length of a wider query
    assert body["total"] == len(body["items"])


def test_escalations_active_pagination_total_is_correct(logged_in_staff):
    t = _mk_thread(created_at=NOW(), inbound_at=NOW())
    for _ in range(3):
        _add_escalation(t, created_at=NOW())
    for _ in range(3):
        _add_escalation(t, created_at=NOW(), status=EscalationStatus.resolved)
    full = logged_in_staff.get("/api/v1/escalations", params={"active": "true", "page_size": 100}).json()
    paged = logged_in_staff.get("/api/v1/escalations", params={"active": "true", "page_size": 2}).json()
    assert len(paged["items"]) == 2
    assert paged["total"] == full["total"] >= 3


def test_escalations_active_hides_reset_items_unless_include_hidden(logged_in_staff):
    t = _mk_thread()
    old_esc = _add_escalation(t)
    _set_cutoff(NOW() - timedelta(hours=1))

    hidden = logged_in_staff.get("/api/v1/escalations", params={"active": "true", "page_size": 100}).json()
    assert old_esc not in {e["id"] for e in hidden["items"]}

    shown = logged_in_staff.get(
        "/api/v1/escalations",
        params={"active": "true", "include_hidden": "true", "page_size": 100},
    ).json()
    assert old_esc in {e["id"] for e in shown["items"]}
    assert shown["total"] > hidden["total"]


def test_escalations_without_active_ignore_the_cutoff(logged_in_staff):
    """Resolved/history views and get-by-id must still show reset items."""
    t = _mk_thread()
    old_esc = _add_escalation(t, status=EscalationStatus.resolved)
    _set_cutoff(NOW() - timedelta(hours=1))

    resp = logged_in_staff.get("/api/v1/escalations", params={"status": "resolved", "page_size": 100})
    assert old_esc in {e["id"] for e in resp.json()["items"]}
    assert logged_in_staff.get(f"/api/v1/escalations/{old_esc}").status_code == 200
    # ...and the per-thread escalation lookup is unchanged too.


# ── 7. things that must NOT change ────────────────────────────────────────────

def test_analytics_ignores_the_cutoff(logged_in_staff):
    t = _mk_thread(tier=ThreadTier.t3_escalate, status=EmailStatus.escalated)
    _add_escalation(t, severity=EscalationSeverity.high)

    def snap() -> dict:
        body = logged_in_staff.get("/api/v1/analytics?days=30").json()
        return {
            "open": body["escalations"]["open_count"],
            "by_sev": body["escalations"]["by_severity"],
        }

    before = snap()
    _set_cutoff(NOW() + timedelta(hours=1))  # hides everything from the to-do
    assert snap() == before


def test_draft_feedback_ignores_the_cutoff(db_session):
    reason = f"Too casual {uuid.uuid4().hex[:6]}"
    t = _mk_thread(category=EmailCategory.document_request)
    _add_draft(t, status=DraftStatus.rejected, rejection_reason=reason)
    _set_cutoff(NOW() + timedelta(hours=1))

    negatives = FeedbackRetrievalService().get_negative_patterns(
        db_session, EmailCategory.document_request.value, limit=100
    )
    assert reason in {n.reason for n in negatives}


def test_dashboard_status_and_category_breakdowns_ignore_the_cutoff(logged_in_staff):
    before = _stats(logged_in_staff)
    _set_cutoff(NOW() + timedelta(hours=1))
    after = _stats(logged_in_staff)
    assert after["threads_by_status"] == before["threads_by_status"]
    assert after["threads_by_category"] == before["threads_by_category"]
    assert after["totals"]["threads"] == before["totals"]["threads"]


# ── 8. draft catch-up ─────────────────────────────────────────────────────────

def test_catchup_skips_hidden_threads(db_session):
    hidden = _mk_thread(tier=ThreadTier.t2_review)
    shown = _mk_thread(tier=ThreadTier.t2_review, created_at=NOW(), inbound_at=NOW())
    _set_cutoff(NOW() - timedelta(hours=1))

    found = {str(t.id) for t in draft_catchup.find_threads_needing_drafts(db_session, limit=1000)}
    assert shown in found
    assert hidden not in found


def test_catchup_unchanged_without_a_cutoff(db_session):
    old = _mk_thread(tier=ThreadTier.t2_review)
    found = {str(t.id) for t in draft_catchup.find_threads_needing_drafts(db_session, limit=1000)}
    assert old in found


# ── 9. endpoints: auth, CSRF, server time, audit, undo ────────────────────────

def test_staff_cannot_read_or_write_the_reset(logged_in_staff):
    assert logged_in_staff.get(BASE).status_code == 403
    assert logged_in_staff.post(BASE).status_code == 403
    assert logged_in_staff.delete(BASE).status_code == 403


def test_unauthenticated_is_rejected(client):
    assert client.get(BASE).status_code == 401


def test_writes_require_csrf(logged_in_admin):
    headers = {"X-CSRF-Token": ""}
    bad_post = logged_in_admin.post(BASE, headers=headers)
    bad_delete = logged_in_admin.delete(BASE, headers=headers)
    assert bad_post.status_code == 403
    assert bad_delete.status_code == 403
    assert todo_queue.CUTOFF_KEY not in _setting_keys()


def _setting_keys() -> set[str]:
    db = _db_mod.SessionLocal()
    try:
        return {r.key for r in db.execute(select(ss.SystemSetting)).scalars().all()}
    finally:
        db.close()


def test_get_with_no_cutoff(logged_in_admin):
    body = logged_in_admin.get(BASE).json()
    assert body["cutoff_at"] is None
    assert body["can_undo"] is False
    assert set(body["would_hide"]) == {"escalations", "reviews"}


def test_apply_uses_server_time_and_ignores_client_body(logged_in_admin):
    t0 = NOW()
    resp = logged_in_admin.post(BASE, json={"cutoff_at": "1999-01-01T00:00:00Z"})
    t1 = NOW()
    assert resp.status_code == 200, resp.text
    cutoff = datetime.fromisoformat(resp.json()["cutoff_at"])
    assert cutoff.tzinfo is not None and cutoff.utcoffset() == timedelta(0)
    assert t0 <= cutoff <= t1
    assert resp.json()["can_undo"] is True
    assert resp.json()["set_by_name"] == "Jane Admin"


def test_apply_audits_actual_counts(logged_in_admin):
    t = _mk_thread(tier=ThreadTier.t3_escalate, status=EmailStatus.escalated)
    _add_escalation(t)
    _mk_thread(tier=ThreadTier.t2_review)
    preview = logged_in_admin.get(BASE).json()["would_hide"]
    assert preview["escalations"] >= 1 and preview["reviews"] >= 1

    n_before = len(_audit_rows("todo_reset.applied"))
    resp = logged_in_admin.post(BASE)
    assert resp.status_code == 200
    rows = _audit_rows("todo_reset.applied")
    assert len(rows) == n_before + 1
    details = rows[-1].details
    assert details["hidden_escalations"] >= preview["escalations"]
    assert details["hidden_reviews"] >= preview["reviews"]
    assert details["cutoff_at"] == resp.json()["cutoff_at"]
    assert rows[-1].user_id is not None


def test_apply_hides_the_lanes_and_leaves_rows_untouched(logged_in_admin):
    tid = _mk_thread(tier=ThreadTier.t2_review)
    assert tid in _lane_ids(logged_in_admin, "t2_review")
    assert logged_in_admin.post(BASE).status_code == 200
    assert tid not in _lane_ids(logged_in_admin, "t2_review")

    db = _db_mod.SessionLocal()
    try:
        t = db.get(EmailThread, uuid.UUID(tid))
        assert t.status == EmailStatus.categorized and t.tier == ThreadTier.t2_review
    finally:
        db.close()
    # still in All
    resp = logged_in_admin.get("/api/v1/emails", params={"page_size": 100, "sort": "updated_desc"})
    assert resp.status_code == 200


def test_undo_restores_previous_state_and_second_undo_is_409(logged_in_admin):
    tid = _mk_thread()
    assert logged_in_admin.post(BASE).status_code == 200
    assert tid not in _lane_ids(logged_in_admin, "t2_review")

    undo = logged_in_admin.delete(BASE)
    assert undo.status_code == 200, undo.text
    assert undo.json()["cutoff_at"] is None
    assert undo.json()["can_undo"] is False
    assert tid in _lane_ids(logged_in_admin, "t2_review")

    assert logged_in_admin.delete(BASE).status_code == 409


def test_undo_restores_who_set_the_cutoff_and_when(logged_in_admin):
    """QA P3-1: after Undo, "set by" / "set at" describe the RESTORED cutoff,
    not the admin who pressed Undo."""
    from app.models.user import UserRole
    from app.services.auth import create_user

    first_at = NOW() - timedelta(days=3)
    db = _db_mod.SessionLocal()
    try:
        sara = create_user(
            db, email=f"sara-{uuid.uuid4().hex[:8]}@example.com",
            name="Sara Original", password="SaraPass123!", role=UserRole.admin,
        )
        ss.set_setting(db, todo_queue.CUTOFF_KEY, first_at.isoformat(), updated_by_id=sara.id)
        row = db.get(ss.SystemSetting, todo_queue.CUTOFF_KEY)
        row.updated_at = first_at
        db.commit()
    finally:
        db.close()

    assert logged_in_admin.post(BASE).status_code == 200  # second reset, by the logged-in admin
    undo = logged_in_admin.delete(BASE)
    assert undo.status_code == 200, undo.text
    state = undo.json()
    assert datetime.fromisoformat(state["cutoff_at"]) == first_at
    assert state["set_by_name"] == "Sara Original"
    assert datetime.fromisoformat(state["set_at"]).replace(tzinfo=timezone.utc) == first_at


def test_undo_with_nothing_to_undo_is_409(logged_in_admin):
    assert logged_in_admin.delete(BASE).status_code == 409


def test_undo_audits_counts(logged_in_admin):
    _mk_thread()
    logged_in_admin.post(BASE)
    n_before = len(_audit_rows("todo_reset.undone"))
    resp = logged_in_admin.delete(BASE)
    assert resp.status_code == 200
    rows = _audit_rows("todo_reset.undone")
    assert len(rows) == n_before + 1
    assert rows[-1].details["restored_cutoff_at"] is None
    assert rows[-1].details["restored_escalations"] >= 0
    assert rows[-1].details["restored_reviews"] >= 1


def test_reset_twice_then_undo_restores_the_first_cutoff(logged_in_admin):
    first = logged_in_admin.post(BASE).json()["cutoff_at"]
    second = logged_in_admin.post(BASE).json()["cutoff_at"]
    assert datetime.fromisoformat(second) >= datetime.fromisoformat(first)

    undo = logged_in_admin.delete(BASE)
    assert undo.status_code == 200
    assert undo.json()["cutoff_at"] == first
    assert logged_in_admin.get(BASE).json()["cutoff_at"] == first


def test_dashboard_stats_exposes_the_cutoff(logged_in_admin, logged_in_staff):
    cutoff = logged_in_admin.post(BASE).json()["cutoff_at"]
    assert _stats(logged_in_staff)["todo_cutoff_at"] == cutoff


# ── 10. the keys are not patchable ────────────────────────────────────────────

@pytest.mark.parametrize("key", ["todo_cutoff_at", "todo_cutoff_previous"])
def test_cutoff_keys_are_not_patchable(logged_in_admin, key):
    resp = logged_in_admin.patch(f"/api/v1/system-settings/{key}", json={"value": "2020-01-01T00:00:00+00:00"})
    assert resp.status_code == 404
    assert key not in _setting_keys()
