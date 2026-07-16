"""
Outlook → app delete-sync (email delete-sync iteration, 2026-07-16).

Covers the reconcile logic that reflects mail Jane deletes/junks in Outlook
back into the app: delta-query Deleted Items + Junk, match by internetMessageId,
flip the local thread to deleted/spam. Provider I/O is faked via
RecordingEmailProvider.delta_folder_messages (see conftest); these tests exercise
the matching, baseline, cursor-persistence, guarding, and flag-gating logic.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.database as _db_mod
import app.services.email_intake as ei
from app.models.audit import AuditLog
from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    SyncState,
)
from app.services.email_intake import reconcile_outlook_deletions
from sqlalchemy import select

DELETED_KEY = "delta:deleteditems"
JUNK_KEY = "delta:junkemail"


# ── helpers ───────────────────────────────────────────────────────────────────

def _uid(prefix: str) -> str:
    return f"<{prefix}-{uuid.uuid4().hex[:12]}@example.com>"


def _seed_thread(*, mid: str, status: EmailStatus = EmailStatus.categorized) -> str:
    """Create a thread with one inbound message keyed by `mid`. Returns thread id."""
    db = _db_mod.SessionLocal()
    try:
        thread = EmailThread(
            subject="Delete-sync subject",
            client_email="client@example.com",
            status=status,
            category=EmailCategory.general_inquiry,
        )
        db.add(thread)
        db.flush()
        db.add(
            EmailMessage(
                thread_id=thread.id,
                message_id_header=mid,
                sender="client@example.com",
                recipient="firm@example.com",
                body_text="Client question.",
                received_at=datetime.now(timezone.utc),
                direction=MessageDirection.inbound,
                is_processed=True,
                raw_headers={},
            )
        )
        db.commit()
        return str(thread.id)
    finally:
        db.close()


def _thread_status(thread_id: str) -> EmailStatus:
    db = _db_mod.SessionLocal()
    try:
        return db.get(EmailThread, uuid.UUID(thread_id)).status
    finally:
        db.close()


def _reset_cursor(key: str) -> None:
    """Delete a sync_state row so the folder starts with no cursor (baseline)."""
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, key)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def _upsert_cursor(key: str, value: str) -> None:
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, key)
        if row is None:
            db.add(SyncState(key=key, value=value))
        else:
            row.value = value
        db.commit()
    finally:
        db.close()


def _get_cursor(key: str) -> str | None:
    db = _db_mod.SessionLocal()
    try:
        row = db.get(SyncState, key)
        return row.value if row else None
    finally:
        db.close()


def _audit_count(thread_id: str, action_suffix: str) -> int:
    db = _db_mod.SessionLocal()
    try:
        rows = (
            db.execute(
                select(AuditLog).where(AuditLog.entity_id == thread_id)
            )
            .scalars()
            .all()
        )
        return sum(1 for r in rows if r.action.endswith(action_suffix))
    finally:
        db.close()


# ── tests ───────────────────────────────────────────────────────────────────

def test_first_run_is_baseline_only(mock_email_provider):
    """No stored cursor → capture the deltaLink but act on nothing."""
    _reset_cursor(DELETED_KEY)
    mid = _uid("baseline")
    tid = _seed_thread(mid=mid)

    mock_email_provider.delta_results = {"deleted_items": ([mid], "deleted-link-1")}
    changed = reconcile_outlook_deletions(mock_email_provider)

    assert changed == 0
    assert _thread_status(tid) == EmailStatus.categorized  # untouched
    assert _get_cursor(DELETED_KEY) == "deleted-link-1"  # cursor captured


def test_subsequent_delta_flips_to_deleted(mock_email_provider):
    """With a prior cursor, a matching id flips the thread to deleted + audits."""
    _upsert_cursor(DELETED_KEY, "deleted-link-0")
    mid = _uid("del")
    tid = _seed_thread(mid=mid)

    mock_email_provider.delta_results = {"deleted_items": ([mid], "deleted-link-2")}
    changed = reconcile_outlook_deletions(mock_email_provider)

    assert changed == 1
    assert _thread_status(tid) == EmailStatus.deleted
    assert _get_cursor(DELETED_KEY) == "deleted-link-2"
    assert _audit_count(tid, "deleted_via_outlook_sync") == 1


def test_junk_delta_flips_to_spam(mock_email_provider):
    """A match surfaced by the Junk delta flips the thread to spam."""
    _upsert_cursor(JUNK_KEY, "junk-link-0")
    mid = _uid("junk")
    tid = _seed_thread(mid=mid)

    mock_email_provider.delta_results = {"junk_email": ([mid], "junk-link-2")}
    changed = reconcile_outlook_deletions(mock_email_provider)

    assert changed == 1
    assert _thread_status(tid) == EmailStatus.spam
    assert _get_cursor(JUNK_KEY) == "junk-link-2"


def test_unmatched_id_is_skipped(mock_email_provider):
    """An id with no local message is ignored; cursor still advances, no error."""
    _upsert_cursor(DELETED_KEY, "deleted-link-0")
    unknown = _uid("ghost")

    mock_email_provider.delta_results = {"deleted_items": ([unknown], "deleted-link-3")}
    changed = reconcile_outlook_deletions(mock_email_provider)

    assert changed == 0
    assert _get_cursor(DELETED_KEY) == "deleted-link-3"


def test_already_terminal_thread_unchanged(mock_email_provider):
    """A thread already deleted/closed is not rewritten by delete-sync."""
    _upsert_cursor(DELETED_KEY, "deleted-link-0")
    mid_closed = _uid("closed")
    tid_closed = _seed_thread(mid=mid_closed, status=EmailStatus.closed)

    mock_email_provider.delta_results = {"deleted_items": ([mid_closed], "deleted-link-4")}
    changed = reconcile_outlook_deletions(mock_email_provider)

    assert changed == 0
    assert _thread_status(tid_closed) == EmailStatus.closed  # resolved thread preserved


def test_delta_failure_is_isolated(mock_email_provider):
    """A delta fetch that raises is guarded — reconcile returns 0, no crash."""
    _upsert_cursor(DELETED_KEY, "deleted-link-0")
    mock_email_provider.raise_on_delta = RuntimeError("graph 503")

    changed = reconcile_outlook_deletions(mock_email_provider)  # must not raise
    assert changed == 0


def test_cursor_is_passed_back_on_next_run(mock_email_provider):
    """The stored deltaLink is handed to the provider as delta_link next run."""
    _upsert_cursor(DELETED_KEY, "deleted-link-A")
    mid = _uid("resume")
    _seed_thread(mid=mid)

    mock_email_provider.delta_results = {"deleted_items": ([], "deleted-link-B")}
    mock_email_provider.delta_calls.clear()
    reconcile_outlook_deletions(mock_email_provider)

    deleted_call = next(
        c for c in mock_email_provider.delta_calls if c["folder"] == "deleted_items"
    )
    assert deleted_call["delta_link"] == "deleted-link-A"


def test_poll_respects_the_flag(mock_email_provider, monkeypatch):
    """poll_once only runs delete-sync when EMAIL_DELETE_SYNC is on."""
    # Flag OFF → no delta calls.
    monkeypatch.setattr(ei.settings, "email_delete_sync", False)
    mock_email_provider.delta_calls.clear()
    ei.poll_once()
    assert mock_email_provider.delta_calls == []

    # Flag ON → both watched folders are delta-queried each cycle.
    monkeypatch.setattr(ei.settings, "email_delete_sync", True)
    mock_email_provider.delta_calls.clear()
    ei.poll_once()
    folders = {c["folder"] for c in mock_email_provider.delta_calls}
    assert folders == {"deleted_items", "junk_email"}


# ── MSGraph delta paging (regression: large-folder baseline) ──────────────────

class _FakeResp:
    def __init__(self, payload: dict):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _make_msgraph_provider():
    """MSGraphProvider with auth + client stubbed so we can drive delta paging."""
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


def test_msgraph_delta_follows_pages_and_captures_deltalink():
    """Baseline must follow @odata.nextLink to the terminal deltaLink, skipping
    @removed entries and requesting large pages — the large-folder bug."""
    provider = _make_msgraph_provider()
    pages = [
        {"value": [{"internetMessageId": "<a@x>"}], "@odata.nextLink": "PAGE-2"},
        {
            "value": [
                {"internetMessageId": "<b@x>"},
                {"@removed": {"reason": "deleted"}, "id": "gone"},
            ],
            "@odata.deltaLink": "DELTA-FINAL",
        },
    ]
    calls: list[dict] = []

    def fake_get(url, headers=None):
        calls.append({"url": url, "headers": headers})
        return _FakeResp(pages[len(calls) - 1])

    provider._client = type("C", (), {"get": staticmethod(fake_get)})()

    ids, next_delta = provider.delta_folder_messages(
        folder="deleted_items", delta_link=None
    )

    assert ids == ["<a@x>", "<b@x>"]  # @removed entry skipped
    assert next_delta == "DELTA-FINAL"  # terminal deltaLink captured
    assert len(calls) == 2  # followed nextLink exactly once
    assert calls[0]["headers"].get("Prefer") == "odata.maxpagesize=500"
    assert calls[1]["url"] == "PAGE-2"  # resumed from the nextLink URL


def test_msgraph_delta_never_advances_cursor_when_cap_hit():
    """If pages never terminate in a deltaLink (cap reached), the cursor is NOT
    advanced — so a failed baseline retries next poll rather than silently
    marking itself done. Regression for the 100-page abort."""
    provider = _make_msgraph_provider()
    calls = {"n": 0}

    def fake_get(url, headers=None):
        calls["n"] += 1
        # Always a nextLink, never a deltaLink → the cap must stop it.
        return _FakeResp({"value": [], "@odata.nextLink": "MORE"})

    provider._client = type("C", (), {"get": staticmethod(fake_get)})()

    ids, next_delta = provider.delta_folder_messages(
        folder="junk_email", delta_link="PRIOR-CURSOR"
    )

    assert next_delta == "PRIOR-CURSOR"  # unchanged — no false advance
    assert calls["n"] == 1000  # stopped at the page cap
