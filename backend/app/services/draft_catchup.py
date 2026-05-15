"""
Draft catch-up sweep — find email threads that should have a draft response
but don't, and generate them in a background worker.

Triggered by:
  - POST /api/v1/runpod/login-sweep (fired on dashboard mount).
  - (Future) Backend restart hook — catch up on anything missed while down.

Mechanism:
  - Sweep query: find at most N threads where tier ∈ {t1_auto, t2_review},
    status is not terminal, no DraftResponse exists yet, and
    draft_generation_failed is False.
  - Spawn a daemon thread that processes the list serially via
    draft_generator.generate(). Each draft call goes through the
    orchestrator's wait_for_ready=True path so the pod is brought up
    once and reused for all subsequent threads in the sweep.
  - `_sweep_in_flight` Event prevents concurrent sweeps — Jane logging
    in twice in 30s shouldn't fire two parallel sweeps over the same
    work.

Naming: not `runpod_login_sweep` because the trigger is "login," not the
backing infra. If the orchestrator is disabled (no RUNPOD_POD_ID), this
still works — `draft_generator.generate()` falls through to whatever
provider is configured. The sweep is orthogonal to pod orchestration.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Sequence

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.email import (
    DraftResponse,
    EmailStatus,
    EmailThread,
    ThreadTier,
)

logger = logging.getLogger(__name__)

# Cap per sweep — protects against a backlog of hundreds of threads
# spawning a runaway uptime spike. Whatever's left after one sweep is
# picked up by the next login (or by the polling pipeline as new mail
# touches each thread).
DEFAULT_SWEEP_LIMIT = 20

# Module-level guard against concurrent sweeps. Set when a worker thread
# is running; cleared in the worker's `finally`.
_sweep_in_flight = threading.Event()


def find_threads_needing_drafts(
    db: Session, limit: int = DEFAULT_SWEEP_LIMIT
) -> list[EmailThread]:
    """Return up to `limit` threads that should have a draft but don't.

    Filter criteria (all required):
      - tier ∈ {t1_auto, t2_review}. T3 (escalated) threads are skipped
        because Jane handles those personally — draft_generator refuses
        them with `EmailStatus.escalated` anyway.
      - status NOT IN {sent, closed, escalated}. Only active workflow.
      - draft_generation_failed = False. Don't auto-retry past failures
        (some other process flagged it, intentional human review may be
        in progress).
      - No DraftResponse row exists for this thread. The whole point.

    Ordered newest-first (`updated_at DESC`) so Jane sees the most recent
    threads drafted before older ones — if the cap kicks in, she still
    gets the freshest context covered first.
    """
    return list(
        db.execute(
            select(EmailThread)
            .where(
                EmailThread.tier.in_([ThreadTier.t1_auto, ThreadTier.t2_review]),
                EmailThread.status.notin_(
                    [
                        EmailStatus.sent,
                        EmailStatus.closed,
                        EmailStatus.escalated,
                    ]
                ),
                EmailThread.draft_generation_failed.is_(False),
                ~exists().where(DraftResponse.thread_id == EmailThread.id),
            )
            .order_by(EmailThread.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def start_sweep(db: Session, limit: int = DEFAULT_SWEEP_LIMIT) -> dict:
    """Find missing drafts and spawn a background worker to generate them.

    Returns immediately (non-blocking) with a status dict:
      {"status": "started", "queued": N}     — sweep spawned with N threads
      {"status": "already_running"}          — sweep already in flight
      {"status": "nothing_to_do", "queued": 0} — no missing drafts

    The worker processes threads serially and uses its own DB session
    per thread. Errors are logged + skipped (one bad thread doesn't kill
    the sweep). `_sweep_in_flight` is cleared in the worker's `finally`.
    """
    if _sweep_in_flight.is_set():
        return {"status": "already_running"}

    threads = find_threads_needing_drafts(db, limit=limit)
    if not threads:
        return {"status": "nothing_to_do", "queued": 0}

    thread_ids = [t.id for t in threads]
    _sweep_in_flight.set()

    worker = threading.Thread(
        target=_run_sweep_worker,
        args=(thread_ids,),
        daemon=True,
        name=f"draft-catchup-{len(thread_ids)}",
    )
    worker.start()

    logger.info("draft_catchup: sweep started, %d threads queued", len(thread_ids))
    return {"status": "started", "queued": len(thread_ids)}


def _run_sweep_worker(thread_ids: Sequence[uuid.UUID]) -> None:
    """Daemon worker: process each thread serially.

    Failures per-thread are logged and skipped. The orchestrator handles
    pod start/health; this worker just calls draft_generator.generate()
    and moves on. The first call brings up the pod (via wait_for_ready=
    True default); subsequent calls reuse the warm pod.
    """
    from app.database import SessionLocal
    from app.services.draft_generator import get_draft_generator

    succeeded = 0
    failed = 0
    skipped = 0
    try:
        generator = get_draft_generator()

        for thread_id in thread_ids:
            try:
                with SessionLocal() as db:
                    thread = db.get(EmailThread, thread_id)
                    if thread is None:
                        # Thread was deleted between sweep query and worker run.
                        skipped += 1
                        continue

                    # Re-check: maybe email polling generated the draft in the
                    # interval between sweep query and now. Don't duplicate.
                    has_draft = db.execute(
                        select(
                            exists().where(DraftResponse.thread_id == thread.id)
                        )
                    ).scalar()
                    if has_draft:
                        skipped += 1
                        continue

                    generator.generate(db, thread)
                    db.commit()
                    succeeded += 1
            except Exception:
                logger.exception(
                    "draft_catchup: failed to generate draft for thread %s",
                    thread_id,
                )
                failed += 1
                # Continue to next thread.

        logger.info(
            "draft_catchup: sweep complete — succeeded=%d failed=%d skipped=%d "
            "(of %d queued)",
            succeeded, failed, skipped, len(thread_ids),
        )
    finally:
        _sweep_in_flight.clear()


def is_sweep_in_flight() -> bool:
    """Diagnostic — whether a sweep worker is currently running."""
    return _sweep_in_flight.is_set()


def reset_sweep_state() -> None:
    """Test hook — clears the in-flight flag so a stuck sweep doesn't wedge tests."""
    _sweep_in_flight.clear()
