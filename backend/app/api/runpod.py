"""
RunPod orchestration endpoints.

POST /api/v1/runpod/wake          — idempotent pre-warm trigger (any user)
POST /api/v1/runpod/login-sweep   — login-time catch-up on missing drafts (any user)
POST /api/v1/runpod/stop          — operator-initiated manual stop (Admin only)
GET  /api/v1/runpod/status        — read-only status (any logged-in user)

The wake/sweep endpoints are fired by the frontend on dashboard mount as
part of the cold-start UX strategy: pre-warm starts the pod in background
while Jane reads her inbox, and the sweep auto-generates any drafts the
background polling pipeline missed. See the FEAT/runpod-prewarm-fastfail
iteration brief for the design rationale.

Stop is admin-gated because it interrupts billable work and could affect
in-flight draft generation. The orchestrator's stop_now() reconciles with
RunPod's view of the pod before acting so a manual stop on an already-
stopped pod doesn't double-count uptime.

Auth: all endpoints require a logged-in user. All POSTs additionally
require CSRF; /stop additionally requires admin role.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_csrf
from app.database import get_db
from app.models.user import User
from app.services import draft_catchup
from app.services.runpod_orchestrator import get_runpod_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runpod", tags=["runpod"])


@router.post("/wake", status_code=status.HTTP_202_ACCEPTED)
def wake_pod(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 — auth gate
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Idempotent pre-warm: trigger a background pod start if EXITED.

    Returns 202 immediately with a status payload. The actual pod start
    happens in a daemon thread spawned by `orchestrator.wake_async()`;
    this endpoint never blocks the caller. Frontend fires this on
    dashboard mount so the pod warms up while Jane reads her inbox.

    Response shape:
      { "status": "ready" | "starting" | "already_starting"
                | "capacity_exceeded" | "missing" | "disabled",
        "pod_id": "...",
        ...optional extra fields ...
      }

    Idempotent: calling this multiple times in quick succession only
    spawns one background thread. Subsequent calls return
    "already_starting" until the bg thread completes.
    """
    orchestrator = get_runpod_orchestrator()
    return orchestrator.wake_async(db)


@router.post("/login-sweep", status_code=status.HTTP_202_ACCEPTED)
def login_sweep(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 — auth gate
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Login-time catch-up sweep — generate drafts for threads missing them.

    Spawns a daemon worker that processes up to DEFAULT_SWEEP_LIMIT
    threads serially. The first generation in the sweep brings the pod
    up; subsequent generations reuse the warm pod.

    Response shape:
      { "status": "started" | "already_running" | "nothing_to_do",
        "queued": N
      }

    Idempotent: a second call while a sweep is in progress returns
    "already_running" with no new work scheduled.
    """
    return draft_catchup.start_sweep(db)


@router.post("/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_pod(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Operator-initiated manual stop. Admin-only.

    Stops the RunPod pod immediately and rolls the current session's
    uptime into uptime_today_seconds (same accounting path the idle
    watchdog uses — manual stops still count toward the daily cap).

    Response shape mirrors wake_async for symmetry:
      { "status": "stopped" | "already_stopped" | "stop_failed"
                | "missing" | "disabled",
        "pod_id": "...",
        ...optional extra fields (uptime_today_seconds, reason, etc) ...
      }

    Idempotent: stopping a pod that's already EXITED returns
    "already_stopped" with no state change beyond syncing the cache.
    """
    orchestrator = get_runpod_orchestrator()
    return orchestrator.stop_now(db)


@router.get("/status")
def runpod_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 — auth gate
) -> dict:
    """Read-only diagnostic snapshot of orchestrator state.

    Returns the orchestrator's view of the pod (last_known_state,
    timestamps, daily uptime, cap remaining, etc) plus whether a
    background start or sweep is currently in flight. Useful for the
    future admin UI's RunPod page, and for debugging during this
    iteration.
    """
    orchestrator = get_runpod_orchestrator()
    snap = orchestrator.status_snapshot(db)
    snap["sweep_in_flight"] = draft_catchup.is_sweep_in_flight()
    return snap
