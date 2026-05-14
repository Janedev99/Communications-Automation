"""
RunPod pod orchestrator.

Replaces the manual `runpod_check.py --start` / `--stop` cycle with an
in-process service that:

  1. ensure_ready(db)
       Called by draft_generator before every LLM call. Starts the pod if
       it's EXITED, waits for RUNNING, probes vLLM is actually serving the
       requested model. Returns the inference base URL. Raises
       RunPodUnavailableError if the pod cannot be brought to a usable
       state (capacity error, daily cap reached, vLLM permanently down).

  2. mark_used(db)
       Called by draft_generator after a successful LLM call. Bumps
       last_used_at so the idle-stop deadline rolls forward.

  3. stop_if_idle(db)
       Called by the watchdog every N seconds. Stops the pod when it has
       been idle longer than RUNPOD_IDLE_TIMEOUT_SECONDS and accumulates
       the elapsed session into uptime_today_seconds.

  4. status_snapshot(db)
       Read-only summary for diagnostics / future admin UI.

State persists in the `runpod_state` table (single row keyed by
RUNPOD_POD_ID). Restarts and crashes don't lose track of a running pod
because the watchdog reconciles on every tick from the DB.

Concurrency: a module-level RLock serializes ensure_ready / stop_if_idle.
Only one caller can be starting (or stopping) the pod at a time —
subsequent draft requests wait briefly, then see the pod is already
RUNNING and return fast. The watchdog can't stop the pod mid-startup
because the start path holds the lock.

Failure mode contract: every failure that should trigger fallback raises
RunPodUnavailableError. The draft generator catches *that one exception*
and switches to Claude (per the project's `allow_claude_fallback`
override). All other exception classes propagate as "real" errors.
"""
from __future__ import annotations

import logging
import threading
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
    """


# Serializes ensure_ready / stop_if_idle. We use RLock (not plain Lock)
# because some future composition (e.g. an ensure_ready that itself calls
# stop_if_idle on an unhealthy pod) would deadlock with a non-reentrant
# lock. The current code doesn't re-enter, but the safety margin is cheap.
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
    """Get the singleton row for this pod, creating it with defaults if absent.

    First-run case: backend is starting against a freshly-created pod and
    runpod_state is empty. We insert a baseline row so every subsequent
    update is a simple UPDATE.
    """
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
    """Roll uptime_today_seconds back to 0 when the UTC date changes.

    Called before any cap-related read so the cap is always evaluated
    against today's accumulator, not yesterday's.
    """
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

    @property
    def enabled(self) -> bool:
        """True when this orchestrator is configured to manage a pod.

        Disabled (returns False) when RUNPOD_POD_ID is empty — typical for
        dev with anthropic-only, or for staging environments that hit a
        different inference backend. In disabled mode ensure_ready just
        returns the configured base_url without managing anything.
        """
        return bool(self._pod_id and self._api_key and self._base_url)

    # ── Public API ───────────────────────────────────────────────────────────

    def ensure_ready(self, db: Session) -> str:
        """Bring the pod into RUNNING + vLLM-serving state. Return inference URL.

        Idempotent fast path: if the pod is already RUNNING and /v1/models
        responds, this is one GET + one DB write and returns immediately.

        Slow path (pod EXITED): start_pod -> wait_for_running -> probe_vllm,
        which takes 30-90s for a warm start and up to ~3 min for a cold start.
        Other concurrent callers wait on the lock and then see the fast path.

        Raises RunPodUnavailableError on any failure that should trigger
        fallback (capacity error, daily cap reached, vLLM permanently down,
        timeout). Caller catches once and routes to Claude.
        """
        if not self.enabled:
            return self._base_url

        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            _maybe_reset_daily_counter(state)

            # Hard daily cap — refuse to start even if idle for hours.
            # This is the budget circuit breaker; ALL other paths still
            # return RunPodUnavailableError so fallback applies.
            if state.uptime_today_seconds >= self._daily_cap_s:
                hours_today = state.uptime_today_seconds / 3600
                hours_cap = self._daily_cap_s / 3600
                raise RunPodUnavailableError(
                    f"daily cap reached ({hours_today:.1f}h of "
                    f"{hours_cap:.1f}h) — refusing to start"
                )

            # Reconcile what RunPod actually thinks the pod is doing.
            # The orchestrator's last_known_state is a hint, but RunPod is
            # the source of truth (external changes happen — Gar restarts
            # the account, the pod gets terminated, etc).
            current = runpod_client.fetch_pod(self._api_key, self._pod_id)
            if current is None:
                state.last_known_state = "MISSING"
                state.updated_at = _now()
                db.flush()
                raise RunPodUnavailableError(
                    f"pod {self._pod_id} not found on RunPod (terminated externally?)"
                )
            current_status = current.get("desiredStatus")
            state.last_known_state = current_status

            # Fast path: pod is running + vLLM healthy. Bump + return.
            if current_status == "RUNNING":
                if self._healthy():
                    state.last_used_at = _now()
                    state.updated_at = _now()
                    db.flush()
                    return self._base_url
                # Container says RUNNING but vLLM is dead. This is the
                # exact failure mode we hit during testing. Cycle: stop +
                # start to force a fresh container.
                logger.warning(
                    "runpod_orchestrator: pod %s RUNNING but vLLM unhealthy; "
                    "cycling stop -> start",
                    self._pod_id,
                )
                self._stop_and_account(db, state)
                # Fall through to start path below.

            # Pod is EXITED, FAILED, STOP_FAILED, or just-cycled-by-us.
            # Try to bring it up; any failure surfaces as RunPodUnavailableError.
            return self._start_and_verify(db, state)

    def mark_used(self, db: Session) -> None:
        """Push the idle-stop deadline forward by one full idle_timeout window.

        Called by draft_generator AFTER a successful LLM call. Cheap (one
        DB row update). Concurrent calls don't conflict — last-write-wins
        on last_used_at is exactly what we want.
        """
        if not self.enabled:
            return
        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            state.last_used_at = _now()
            state.updated_at = _now()
            db.flush()

    def stop_if_idle(self, db: Session) -> bool:
        """Watchdog tick. Stop the pod when idle longer than the timeout.

        Returns True if a stop was issued (whether or not it succeeded);
        False if the pod was already stopped, not idle, or orchestration
        is disabled.
        """
        if not self.enabled:
            return False
        with _lock:
            state = _load_or_create_state(db, self._pod_id)
            _maybe_reset_daily_counter(state)

            # Only act on pods *we* believe to be running. If the state
            # is EXITED/STARTING/etc, leave it alone — ensure_ready owns
            # those transitions.
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
        """Read-only state summary. Safe to call from any request handler."""
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
        }

    # ── Internals (lock must be held by callers) ─────────────────────────────

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
        # Soft check: requested model must be among loaded ones. vLLM is
        # strict about exact-match model ids, so this catches the "pod
        # was created with model X, .env now says model Y" case at the
        # orchestrator level instead of letting drafts fail one-by-one.
        if self._model and self._model not in models:
            logger.warning(
                "runpod_orchestrator: requested model %r not in loaded set %r",
                self._model, models,
            )
            return False
        return True

    def _start_and_verify(self, db: Session, state: RunPodState) -> str:
        """Start the pod, wait for RUNNING, probe vLLM, update state. Returns URL.

        Caller must hold _lock. Raises RunPodUnavailableError on any failure.
        Mutates and flushes `state` at every observable transition so that
        a watchdog crash (or backend restart) mid-startup leaves the DB
        with the latest known status.
        """
        if not runpod_client.start_pod(self._api_key, self._pod_id):
            state.last_known_state = "START_FAILED"
            state.updated_at = _now()
            db.flush()
            raise RunPodUnavailableError(
                f"start_pod accept failed for {self._pod_id}"
            )

        state.last_started_at = _now()
        state.last_known_state = "STARTING"
        state.updated_at = _now()
        db.flush()

        url = runpod_client.wait_for_running(
            self._api_key,
            self._pod_id,
            timeout_s=self._start_wait_s,
        )
        if url is None:
            # Pod didn't reach RUNNING in budget. We deliberately don't
            # stop here — the pod may still come up after we give up,
            # and the next watchdog tick will reconcile. The cap counter
            # will catch any runaway.
            state.last_known_state = "FAILED_START"
            state.updated_at = _now()
            db.flush()
            raise RunPodUnavailableError(
                f"pod {self._pod_id} did not reach RUNNING within {self._start_wait_s}s"
            )

        # Pod is RUNNING per RunPod. Probe vLLM. probe_vllm retries inside
        # so a single failure doesn't kill the path — but if all attempts
        # exhaust, vLLM is genuinely down inside the container.
        if not runpod_client.probe_vllm(
            self._base_url,
            self._api_key,
            self._model,
        ):
            state.last_known_state = "UNHEALTHY"
            state.updated_at = _now()
            db.flush()
            raise RunPodUnavailableError(
                f"vLLM did not respond after start of {self._pod_id}"
            )

        state.last_known_state = "RUNNING"
        state.last_used_at = _now()
        state.updated_at = _now()
        db.flush()
        return self._base_url

    def _stop_and_account(self, db: Session, state: RunPodState) -> bool:
        """Stop the pod and roll the session's uptime into the daily counter.

        Caller must hold _lock. Returns True on stop accept, False otherwise.

        Uptime accounting only happens on successful stop. A failed stop
        leaves last_known_state as RUNNING so the next watchdog tick retries;
        a successful stop sets EXITED and clears last_started_at so the
        next start_pod begins a clean session.
        """
        if not runpod_client.stop_pod(self._api_key, self._pod_id):
            # Stop refused — leave state as RUNNING, watchdog retries next tick.
            state.updated_at = _now()
            db.flush()
            return False

        # Account for the just-finished session. Worst case last_started_at
        # is None (we adopted a pod we didn't start) — then session_s is 0
        # and we under-count, which is the safe direction (cap kicks in
        # later, not earlier — and an adopted pod's uptime isn't ours to
        # charge against the daily cap anyway).
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
    """Module-level singleton. Reads settings on first call, then caches.

    Mirrors the get_llm_client / get_draft_generator pattern elsewhere in
    the service layer.
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RunPodOrchestrator()
    return _orchestrator


def reset_runpod_orchestrator() -> None:
    """Test hook — drops the singleton so the next call rebuilds with fresh settings."""
    global _orchestrator
    _orchestrator = None
