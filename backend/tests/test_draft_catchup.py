"""
Unit tests for app.services.draft_catchup — the login-time sweep that
generates drafts for T1/T2 threads which don't have one yet.

Strategy: build a few EmailThread rows in various states, run
find_threads_needing_drafts, assert the right ones come back. For
start_sweep, mock draft_generator.get_draft_generator so we don't
actually call any LLM — just verify the worker iterates and the
in-flight flag is managed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    ThreadTier,
)
from app.services import draft_catchup


@pytest.fixture(autouse=True)
def reset_state(db_session: Session):
    """Clear in-flight flag AND pre-existing email/draft rows.

    The conftest shares a single in-memory DB across all tests and
    explicitly does NOT roll back between them. For these tests to assert
    on exact counts ("queued == 2", "nothing_to_do"), we need a clean
    slate — drafts and threads created by other tests would otherwise
    leak in. Delete order respects FKs: drafts -> messages -> threads.
    """
    draft_catchup.reset_sweep_state()
    db_session.query(DraftResponse).delete()
    db_session.query(EmailMessage).delete()
    db_session.query(EmailThread).delete()
    db_session.commit()
    yield
    draft_catchup.reset_sweep_state()


def _make_thread(
    db: Session,
    *,
    tier: ThreadTier = ThreadTier.t2_review,
    status: EmailStatus = EmailStatus.categorized,
    draft_generation_failed: bool = False,
    has_draft: bool = False,
    subject: str | None = None,
) -> EmailThread:
    """Helper: create an EmailThread (with optional DraftResponse) and commit."""
    thread = EmailThread(
        id=uuid.uuid4(),
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name="Test Client",
        subject=subject or f"Test subject {uuid.uuid4().hex[:6]}",
        category=EmailCategory.general_inquiry,
        status=status,
        tier=tier,
        ai_summary="Test summary.",
        draft_generation_failed=draft_generation_failed,
    )
    db.add(thread)
    db.flush()

    if has_draft:
        draft = DraftResponse(
            thread_id=thread.id,
            body_text="Existing draft body, plenty long enough for validation.",
            original_body_text="Existing draft body, plenty long enough for validation.",
            status=DraftStatus.pending,
            version=1,
            ai_model="test-model",
            knowledge_entry_ids=[],
        )
        db.add(draft)
        db.flush()

    db.commit()
    return thread


# ── find_threads_needing_drafts ──────────────────────────────────────────────


def test_find_threads_picks_t1_and_t2_without_drafts(db_session: Session):
    """T1 and T2 threads without drafts should be returned."""
    t1 = _make_thread(db_session, tier=ThreadTier.t1_auto)
    t2 = _make_thread(db_session, tier=ThreadTier.t2_review)

    found = draft_catchup.find_threads_needing_drafts(db_session)
    found_ids = {t.id for t in found}
    assert t1.id in found_ids
    assert t2.id in found_ids


def test_find_threads_excludes_threads_with_existing_drafts(db_session: Session):
    """Threads that already have a DraftResponse must not be returned."""
    with_draft = _make_thread(db_session, has_draft=True)
    without_draft = _make_thread(db_session, has_draft=False)

    found = draft_catchup.find_threads_needing_drafts(db_session)
    found_ids = {t.id for t in found}
    assert with_draft.id not in found_ids
    assert without_draft.id in found_ids


def test_find_threads_excludes_terminal_statuses(db_session: Session):
    """sent / closed / escalated threads are skipped (Jane handles or it's done)."""
    sent = _make_thread(db_session, status=EmailStatus.sent)
    closed = _make_thread(db_session, status=EmailStatus.closed)
    escalated = _make_thread(db_session, status=EmailStatus.escalated)
    active = _make_thread(db_session, status=EmailStatus.categorized)

    found = draft_catchup.find_threads_needing_drafts(db_session)
    found_ids = {t.id for t in found}
    assert sent.id not in found_ids
    assert closed.id not in found_ids
    assert escalated.id not in found_ids
    assert active.id in found_ids


def test_find_threads_excludes_draft_generation_failed(db_session: Session):
    """Threads flagged as previously-failed shouldn't auto-retry."""
    failed = _make_thread(db_session, draft_generation_failed=True)
    not_failed = _make_thread(db_session, draft_generation_failed=False)

    found = draft_catchup.find_threads_needing_drafts(db_session)
    found_ids = {t.id for t in found}
    assert failed.id not in found_ids
    assert not_failed.id in found_ids


def test_find_threads_respects_limit(db_session: Session):
    """The `limit` parameter caps the result set."""
    # Create 5 candidate threads
    threads = [_make_thread(db_session) for _ in range(5)]

    found = draft_catchup.find_threads_needing_drafts(db_session, limit=2)
    assert len(found) == 2

    # Sanity: the returned ones are a subset of created
    found_ids = {t.id for t in found}
    all_ids = {t.id for t in threads}
    assert found_ids.issubset(all_ids)


# ── start_sweep ──────────────────────────────────────────────────────────────


def test_start_sweep_nothing_to_do(db_session: Session):
    """When no candidates, returns nothing_to_do without spawning a worker."""
    # No threads in DB matching criteria
    result = draft_catchup.start_sweep(db_session)
    assert result["status"] == "nothing_to_do"
    assert result["queued"] == 0
    assert not draft_catchup.is_sweep_in_flight()


def test_start_sweep_spawns_worker_and_returns_queued_count(db_session: Session):
    """With candidates available, spawns a worker thread and reports count."""
    _make_thread(db_session)
    _make_thread(db_session)

    # Mock draft_generator so the worker doesn't actually call the LLM.
    fake_generator = MagicMock()
    fake_generator.generate.return_value = MagicMock()  # any non-None return

    with patch(
        "app.services.draft_generator.get_draft_generator",
        return_value=fake_generator,
    ):
        result = draft_catchup.start_sweep(db_session)
        assert result["status"] == "started"
        assert result["queued"] == 2

        # Wait briefly for the worker to drain
        import time
        for _ in range(50):
            if not draft_catchup.is_sweep_in_flight():
                break
            time.sleep(0.05)

    # Worker should have called generate for each thread
    assert fake_generator.generate.call_count == 2
    assert not draft_catchup.is_sweep_in_flight()


def test_start_sweep_already_running_returns_already(db_session: Session):
    """Concurrent start_sweep calls only spawn one worker."""
    _make_thread(db_session)

    import threading
    block = threading.Event()

    fake_generator = MagicMock()
    fake_generator.generate.side_effect = lambda *a, **kw: (
        block.wait(timeout=3.0) or MagicMock()
    )

    with patch(
        "app.services.draft_generator.get_draft_generator",
        return_value=fake_generator,
    ):
        # First call: worker spawned
        first = draft_catchup.start_sweep(db_session)
        assert first["status"] == "started"

        # Second call while worker is blocked on generate(): already_running
        second = draft_catchup.start_sweep(db_session)
        assert second["status"] == "already_running"

        # Release worker + wait for completion
        block.set()
        import time
        for _ in range(50):
            if not draft_catchup.is_sweep_in_flight():
                break
            time.sleep(0.05)

    # generate should have been called exactly once
    # (one thread, one worker, no duplicates from the "already_running" path)
    assert fake_generator.generate.call_count == 1
