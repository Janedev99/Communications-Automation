"""
RunPod idle-stop watchdog.

Background task that wakes every RUNPOD_WATCHDOG_INTERVAL_SECONDS and asks
the orchestrator whether the pod has been idle long enough to stop. Lives
in the FastAPI lifespan alongside email polling + session cleanup.

The watchdog is *only* about idle-stop. Everything else (start-on-demand,
health-probe-driven restart, daily-cap enforcement) happens inside
ensure_ready on the draft-generation path. Keeping the watchdog narrow
makes its failure mode obvious — at worst, idle-stop is delayed by a few
ticks, never anything more destructive.

Design notes:

  - The work is sync (DB ORM + httpx) so we run it in an executor thread
    to avoid blocking the event loop. Mirrors _session_cleanup_loop in
    app.main.
  - Crash isolation: any exception in stop_if_idle is logged and the loop
    continues. We never want the watchdog to crash and leave a pod
    running unattended.
  - Sleep before work, not after, so a startup-immediate-call doesn't
    pile on top of slow boot-time initialization.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def _sync_stop_if_idle() -> bool:
    """Executor-thread helper: open a DB session, call orchestrator.stop_if_idle.

    Returns True if a stop was issued this tick. The orchestrator handles
    all the "is it actually idle" logic — this is just plumbing.
    """
    from app.database import SessionLocal
    from app.services.runpod_orchestrator import get_runpod_orchestrator

    orchestrator = get_runpod_orchestrator()
    if not orchestrator.enabled:
        return False
    with SessionLocal() as db:
        try:
            acted = orchestrator.stop_if_idle(db)
            db.commit()
            return acted
        except Exception:
            db.rollback()
            raise


async def start_watchdog_loop() -> None:
    """Long-running async task: tick -> sleep -> tick.

    Started from FastAPI's lifespan. Cancelled on shutdown — pending stops
    in flight are NOT awaited; the OS-level pod stop is independent of our
    process anyway.
    """
    settings = get_settings()
    interval_s = settings.runpod_watchdog_interval_seconds

    # No-op exit when the orchestrator isn't configured. Avoids a
    # log-spamming loop in dev environments that don't manage a pod.
    from app.services.runpod_orchestrator import get_runpod_orchestrator
    if not get_runpod_orchestrator().enabled:
        logger.info(
            "runpod_watchdog: orchestration disabled (no RUNPOD_POD_ID) — "
            "watchdog will exit without ticking"
        )
        return

    logger.info(
        "runpod_watchdog: started (interval=%ds, idle_timeout=%ds)",
        interval_s, settings.runpod_idle_timeout_seconds,
    )

    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(interval_s)
        try:
            acted = await loop.run_in_executor(None, _sync_stop_if_idle)
            if acted:
                logger.info("runpod_watchdog: pod stop issued this tick")
        except Exception as exc:
            # Never crash the loop — a stop_if_idle failure is recoverable
            # next tick. Logging it is enough; the next tick will try again.
            logger.warning(
                "runpod_watchdog: tick failed (will retry next interval): %s: %s",
                type(exc).__name__, exc,
            )
