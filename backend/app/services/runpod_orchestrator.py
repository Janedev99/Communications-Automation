"""
RunPod pod orchestrator.

Replaces the manual `runpod_check.py --start` / `--stop` cycle with an
in-process service that:

  1. ensure_ready(db, *, wait_for_ready=True)
       Bring the pod into RUNNING + vLLM-serving state.
         - wait_for_ready=True (default): caller blocks until the pod is
           ready or a failure is determined. Used by background work
           (email_intake polling, login sweep) that can afford to wait.
         - wait_for_ready=False: fast-fail. If the pod is not RUNNING +
           healthy, schedule a background start and raise
           RunPodUnavailableError immediately. Used by user-facing API
           paths so Jane never blocks on a cold-start — her draft is
           served by Claude in ~10s, and the pod warms up in background
           for the next click.

  2. mark_used(db)
       Called after a successful LLM call. Bumps last_used_at so the
       idle-stop deadline rolls forward.

  3. stop_if_idle(db)
       Watchdog hook (every N seconds). Stops the pod when it has been
       idle longer than RUNPOD_IDLE_TIMEOUT_SECONDS.

  4. wake_async(db)
       Idempotent. Triggers a background start if pod is EXITED. Used
       by POST /api/v1/runpod/wake (fired on dashboard mount) so the
       pod is already booting while Jane reads her inbox.

  5. status_snapshot(db)
       Read-only summary for diagnostics / admin UI.

Concurrency model
-----------------
The slow path (start_pod -> wait_for_running -> probe_vllm, up to 3 min)
always runs in a *daemon thread* outside the lock. This means:

  - The watchdog can still tick during a cold start (it sees state is
    STARTING, skips, no harm done).
  - Concurrent ensure_ready calls don't block each other: the first
    schedules the bg start, subsequent ones wait on the same Event.
  - The lock only protects fast state I/O (DB row reads/writes).

Two Events coordinate the start lifecycle:

  _start_in_flight: set while a bg start thread is running.
  _start_completed: set when a bg start finishes (success OR failure).
                    Waited on by wait_for_ready=True callers.

Failure mode contract
---------------------
Every failure that should trigger fallback raises RunPodUnavailableError.
The draft generator catches it and switches to Claude (per the
project's allow_claude_fallback override). The reason field on the
exception distinguishes:

  - "runpod_capacity_error"     : RunPod 5xx on start_pod
  - "runpod_cold_start_in_progress" : fast-fail while bg start runs
  - "runpod_call_failed"        : mid-call LLM error
  - "runpod_unhealthy"          : pod RUNNING but vLLM dead
  - "daily_cap_reached"         : circuit breaker
  - "pod_missing"               : pod terminated externally
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.runpod_state import RunPodState
from app.services import runpod_client

logger = logging.getLogger(__name__)


class RunPodUnavailableError(Exception):
    """Raised when ensure_ready cannot bring the pod into a usable state.

    Catch this in draft_generator and switch to the Claude fallback when
    ALLOW_CLAUDE_FALLBACK=true; raise a clearer error to the caller when
    fallback is disabled.

    The .args[0] reason string is structured for audit log filtering:
    see module docstring for the canonical reason values.
    """


# Module-level lock — protects fast state reads/writes only. Slow ops
# (start_pod / wait_for_running / probe_vllm) run OUTSIDE the lock in
# a daemon thread, coordinated via the two Events on the orchestrator.
_lock = threading.RLock()


# ── Time helpers (kept tiny + obvious so test mocks are straightforward) ─────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_utc() -> date:
    return _now().date()


def _seconds_since(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    return (_now() - ts).total_seconds()


# ── State row helpers ────────────────────────────────────────────────────────


def _load_or_create_state(db: Session, pod_id: str) -> RunPodState:
    """Get the singleton row for this pod, creating it with defaults if absent."""
    row = db.execute(
        select(RunPodState).where(RunPodState.pod_id == pod_id)
    ).scalar_one_or_none()
    if row is None:
        row = RunPodState(
            pod_id=pod_id,
            uptime_today_seconds=0,
            uptime_day_utc=_today_utc(),
            updated_at=_now(),
        )
        db.add(row)
        db.flush()
    return row


def _maybe_reset_daily_counter(state: RunPodState) -> None:
    """Roll uptime_today_seconds back to 0 when the UTC date changes."""
    today = _today_utc()
    if state.uptime_day_utc != today:
        logger.info(
            "runpod_orchestrator: daily counter rolled %s -> %s (was %ds)",
            state.uptime_day_utc, today, state.uptime_today_seconds,
        )
        state.uptime_today_seconds = 0
        state.uptime_day_utc = today


# ── Orchestrator ─────────────────────────────────────────────────────────────


class RunPodOrchestrator:
    """In-process pod lifecycle manager. Use via get_runpod_orchestrator()."""

    def __init__(self) -> None:
        settings = get_settings()
        self._pod_id = settings.runpod_pod_id
        self._api_key = settings.llm_api_key
        self._base_url = settings.llm_base_url
        self._model = settings.llm_model
        self._idle_timeout_s = settings.runpod_idle_timeout_seconds
        self._daily_cap_s = settings.runpod_daily_cap_hours * 3600
        self._start_wait_s = settings.runpod_start_wait_timeout_seconds
        self._health_probe_timeout_s = settings.runpod_health_probe_timeout_seconds

        # Coordinate background-start lifecycle.
        # _start_in_flight: SET while a bg thread is running.
        # _start_completed: SET when the bg thread finishes (success OR failure).
        #                   wait_for_ready=True callers .wait() on this.
        # Initially: no start in flight, no pending result, so completed is "set"
        # in the sense that wait() returns immediately if called before any start
        # has been scheduled (we re-check state.last_known_state in that case).
        self._start_in_flight = threading.Event()
        self._start_completed = threading.Event()
        self._start_completed.set()

    @property
    def enabled(self) -> bool:
        """True when this orchestrator is configured to manage a pod."""
        return bool(self._pod_id and self._api_key and self._base_url)

    # ── Public API ───────────────────────────────────────────────────────────

    def ensure_ready(self, db: Session, *, wait_for_ready: bool = True) -> str:
        """Bring the pod into RUNNING + vLLM-serving state.

        Two modes via `wait_for_ready`:

          - True (default): used by background work (email polling,
            login sweep). Blocks until the pod is ready or until a
            terminal failure / timeout. Caller is happy to wait.

          - False: used by user-facing API paths. If the pod is not
            already RUNNING + healthy, schedule a background start and
            raise RunPodUnavailableError("runpod_cold_start_in_progress")
            immediately. The draft generator's existing Claude-fallback
            handler catches and serves the draft via Claude. Subsequent
            calls within the same boot cycle see the now-warm pod and
            hit the fast path.

        Idempotent fast-path: if the pod is already RUNNING + /v1/models
        responds, this is one fetch_pod + one list_models + one DB write
        and returns immediately. Same shape for both modes.

        Raises RunPodUnavailableError on any failure (capacity error,
        daily cap, vLLM permanently down, timeout, fast-fail). Caller
        catches once and routes to Claude.
        """
        if not self.enabled:
            return self._base_url

        # ── Phase 1: fast checks under the lock ─────────────────────────────
        # Quickly determine: is the pod ready right now? If not, do we need
        # to schedule a background start?
        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            _maybe_reset_daily_counter(state)

            # Hard daily cap — refuse to even check pod state. This is the
            # budget circuit breaker.
            if state.uptime_today_seconds >= self._daily_cap_s:
                hours_today = state.uptime_today_seconds / 3600
                hours_cap = self._daily_cap_s / 3600
                raise RunPodUnavailableError(
                    f"daily_cap_reached: {hours_today:.1f}h of {hours_cap:.1f}h"
                )

            # Reconcile with RunPod's view of the world.
            current = runpod_client.fetch_pod(self._api_key, self._pod_id)
            if current is None:
                state.last_known_state = "MISSING"
                state.updated_at = _now()
                db.flush()
                raise RunPodUnavailableError(
                    f"pod_missing: pod {self._pod_id} not found on RunPod"
                )
            current_status = current.get("desiredStatus")
            state.last_known_state = current_status

            # Hot path: pod RUNNING + vLLM healthy.
            if current_status == "RUNNING" and self._healthy():
                state.last_used_at = _now()
                state.updated_at = _now()
                db.flush()
                return self._base_url

            # RUNNING but vLLM dead — cycle stop+start. We do the stop here
            # synchronously (it's fast), then fall through to schedule the
            # bg start path.
            if current_status == "RUNNING":
                logger.warning(
                    "runpod_orchestrator: pod %s RUNNING but vLLM unhealthy; "
                    "cycling stop -> start",
                    self._pod_id,
                )
                self._stop_and_account(db, state)

            # Pod is EXITED, FAILED, just-cycled-by-us, or some other
            # not-ready state. Schedule a background start if one isn't
            # already in flight.
            self._maybe_schedule_background_start_locked(db, state)

        # ── Phase 2: lock released. Decide what to return. ──────────────────
        if not wait_for_ready:
            # Fast-fail path: caller will switch to Claude.
            raise RunPodUnavailableError(
                "runpod_cold_start_in_progress: pod is booting in background"
            )

        # wait_for_ready=True: block until the bg start finishes, then
        # re-check the resulting state.
        return self._wait_for_bg_start_to_complete(db)

    def wake_async(self, db: Session) -> dict:
        """Idempotent wake call — used by POST /api/v1/runpod/wake.

        Returns a status dict (no exception path; the wake endpoint is a
        hint, not a guarantee). The dashboard fires this on mount; if it
        fails for any reason, drafts will still work via the orchestrator's
        normal paths.

        Status values:
          - "disabled"            : orchestrator not configured
          - "ready"               : pod already RUNNING + healthy
          - "starting"            : we just spawned a background start
          - "already_starting"    : a bg start was already in progress
          - "capacity_exceeded"   : daily cap reached, no start scheduled
          - "missing"             : pod not found on RunPod
        """
        if not self.enabled:
            return {"status": "disabled"}

        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            _maybe_reset_daily_counter(state)

            if state.uptime_today_seconds >= self._daily_cap_s:
                state.updated_at = _now()
                db.flush()
                return {
                    "status": "capacity_exceeded",
                    "pod_id": self._pod_id,
                    "uptime_today_seconds": state.uptime_today_seconds,
                    "daily_cap_seconds": self._daily_cap_s,
                }

            current = runpod_client.fetch_pod(self._api_key, self._pod_id)
            if current is None:
                state.last_known_state = "MISSING"
                state.updated_at = _now()
                db.flush()
                return {"status": "missing", "pod_id": self._pod_id}

            status = current.get("desiredStatus")
            state.last_known_state = status

            if status == "RUNNING" and self._healthy():
                state.last_used_at = _now()
                state.updated_at = _now()
                db.flush()
                return {"status": "ready", "pod_id": self._pod_id}

            if self._start_in_flight.is_set():
                return {"status": "already_starting", "pod_id": self._pod_id}

            # Not ready, nothing in flight → schedule background start.
            self._maybe_schedule_background_start_locked(db, state)
            return {"status": "starting", "pod_id": self._pod_id}

    def mark_used(self, db: Session) -> None:
        """Push the idle-stop deadline forward by one full idle_timeout window."""
        if not self.enabled:
            return
        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            state.last_used_at = _now()
            state.updated_at = _now()
            db.flush()

    def stop_if_idle(self, db: Session) -> bool:
        """Watchdog tick. Stop the pod when idle longer than the timeout."""
        if not self.enabled:
            return False
        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            _maybe_reset_daily_counter(state)

            # Only act on pods we believe to be RUNNING. STARTING/EXITED/etc
            # are left alone — ensure_ready and the bg thread own those.
            if state.last_known_state != "RUNNING":
                return False
            idle_s = _seconds_since(state.last_used_at)
            if idle_s is None or idle_s < self._idle_timeout_s:
                return False

            logger.info(
                "runpod_orchestrator: pod %s idle %.0fs (>= %ds) — stopping",
                self._pod_id, idle_s, self._idle_timeout_s,
            )
            self._stop_and_account(db, state)
            return True

    def status_snapshot(self, db: Session) -> dict:
        """Read-only state summary."""
        if not self.enabled:
            return {"enabled": False}
        state = _load_or_create_state(db, self._pod_id)
        _maybe_reset_daily_counter(state)
        return {
            "enabled": True,
            "pod_id": self._pod_id,
            "last_known_state": state.last_known_state,
            "last_used_at": state.last_used_at.isoformat() if state.last_used_at else None,
            "last_started_at": state.last_started_at.isoformat() if state.last_started_at else None,
            "last_stopped_at": state.last_stopped_at.isoformat() if state.last_stopped_at else None,
            "uptime_today_seconds": state.uptime_today_seconds,
            "uptime_day_utc": state.uptime_day_utc.isoformat() if state.uptime_day_utc else None,
            "daily_cap_seconds": self._daily_cap_s,
            "daily_cap_remaining_seconds": max(
                0, self._daily_cap_s - state.uptime_today_seconds
            ),
            "idle_timeout_seconds": self._idle_timeout_s,
            "start_in_flight": self._start_in_flight.is_set(),
        }

    # ── Internals ────────────────────────────────────────────────────────────

    def _healthy(self) -> bool:
        """Cheap vLLM liveness check. True iff /v1/models responds + has our model."""
        models = runpod_client.list_models(
            self._base_url,
            self._api_key,
            timeout=self._health_probe_timeout_s,
        )
        if models is None:
            return False
        if not models:
            logger.warning(
                "runpod_orchestrator: pod %s /v1/models returned empty list",
                self._pod_id,
            )
            return False
        if self._model and self._model not in models:
            logger.warning(
                "runpod_orchestrator: requested model %r not in loaded set %r",
                self._model, models,
            )
            return False
        return True

    def _maybe_schedule_background_start_locked(
        self, db: Session, state: RunPodState
    ) -> bool:
        """Schedule a bg start thread if one isn't already in flight.

        Caller must hold _lock. Returns True if a new thread was spawned.

        Updates state to STARTING + last_started_at = now so concurrent
        readers see "we're working on it" even before the bg thread runs.
        """
        if self._start_in_flight.is_set():
            return False

        # Mark "starting" + spawn. Set events BEFORE the thread starts so
        # any caller polling immediately after sees the in-flight flag.
        self._start_in_flight.set()
        self._start_completed.clear()

        state.last_known_state = "STARTING"
        state.last_started_at = _now()
        state.updated_at = _now()
        db.flush()

        thread = threading.Thread(
            target=self._run_background_start,
            daemon=True,
            name=f"runpod-bg-start-{self._pod_id}",
        )
        thread.start()
        logger.info(
            "runpod_orchestrator: background start thread spawned for %s",
            self._pod_id,
        )
        return True

    def _run_background_start(self) -> None:
        """Daemon thread body: start_pod -> wait_for_running -> probe_vllm.

        Runs OUTSIDE _lock for the slow operations. Acquires the lock only
        for the final state-update step. Always clears _start_in_flight
        and sets _start_completed in the finally block so sync callers
        unblock.

        Uses its own DB session (SessionLocal) because session objects
        aren't safe across threads.
        """
        from app.database import SessionLocal
        terminal_state = "RUNNING"  # optimistic; flipped on any failure
        try:
            # Step 1: start_pod
            if not runpod_client.start_pod(self._api_key, self._pod_id):
                terminal_state = "START_FAILED"
                return

            # Step 2: wait_for_running
            url = runpod_client.wait_for_running(
                self._api_key,
                self._pod_id,
                timeout_s=self._start_wait_s,
            )
            if url is None:
                terminal_state = "FAILED_START"
                return

            # Step 3: probe_vllm
            if not runpod_client.probe_vllm(
                self._base_url,
                self._api_key,
                self._model,
            ):
                terminal_state = "UNHEALTHY"
                return

            # All three steps passed — pod is genuinely RUNNING + serving.
            logger.info(
                "runpod_orchestrator: background start complete for %s",
                self._pod_id,
            )
        except Exception:
            logger.exception(
                "runpod_orchestrator: background start crashed for %s",
                self._pod_id,
            )
            terminal_state = "CRASHED"
        finally:
            # Persist the final state and signal completion. Use a fresh
            # DB session — the original request's session is unsafe to
            # share across threads.
            try:
                with SessionLocal() as db, _lock:
                    state = _load_or_create_state(db, self._pod_id)
                    state.last_known_state = terminal_state
                    if terminal_state == "RUNNING":
                        state.last_used_at = _now()
                    state.updated_at = _now()
                    db.commit()
            except Exception:
                logger.exception(
                    "runpod_orchestrator: failed to record terminal state %s for %s",
                    terminal_state, self._pod_id,
                )
            # Order matters: clear in_flight FIRST so any caller that races
            # past completed.wait() and checks in_flight sees False.
            self._start_in_flight.clear()
            self._start_completed.set()

    def _wait_for_bg_start_to_complete(self, db: Session) -> str:
        """Block until the bg start finishes, then return URL or raise.

        Used by wait_for_ready=True callers. Returns self._base_url if the
        bg start completed successfully (state == RUNNING). Raises
        RunPodUnavailableError on any non-success terminal state.

        Timeout = start_wait_s + 60s buffer for probe_vllm's full budget.
        """
        timeout_s = self._start_wait_s + 60
        if not self._start_completed.wait(timeout=timeout_s):
            raise RunPodUnavailableError(
                f"runpod_background_start_timeout: did not complete in {timeout_s}s"
            )

        # Bg thread finished. The bg thread used a different DB session
        # to commit the terminal state; our session's identity map has the
        # pre-update row cached. Expire it so the next read hits the DB
        # and sees the fresh state.
        with _lock:
            db.expire_all()
            state = _load_or_create_state(db, self._pod_id)
            if state.last_known_state == "RUNNING":
                state.last_used_at = _now()
                state.updated_at = _now()
                db.flush()
                return self._base_url
            raise RunPodUnavailableError(
                f"runpod_background_start_failed: terminal_state={state.last_known_state}"
            )

    def _stop_and_account(self, db: Session, state: RunPodState) -> bool:
        """Stop the pod and roll the session's uptime into the daily counter.

        Caller must hold _lock. Returns True on stop accept.

        Uptime accounting only on successful stop. A failed stop leaves
        last_known_state as RUNNING so the next watchdog tick retries.
        """
        if not runpod_client.stop_pod(self._api_key, self._pod_id):
            state.updated_at = _now()
            db.flush()
            return False

        session_s = _seconds_since(state.last_started_at) or 0.0
        state.uptime_today_seconds += int(session_s)
        state.last_stopped_at = _now()
        state.last_started_at = None
        state.last_known_state = "EXITED"
        state.updated_at = _now()
        db.flush()
        return True


# ── Module singleton ─────────────────────────────────────────────────────────


_orchestrator: RunPodOrchestrator | None = None


def get_runpod_orchestrator() -> RunPodOrchestrator:
    """Module-level singleton. Reads settings on first call, then caches."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RunPodOrchestrator()
    return _orchestrator


def reset_runpod_orchestrator() -> None:
    """Test hook — drops the singleton so the next call rebuilds with fresh settings."""
    global _orchestrator
    _orchestrator = None
