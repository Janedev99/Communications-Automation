"""
Low-level RunPod REST API client.

Single source of truth for talking to RunPod's REST API. Imported by:

    - backend/app/services/runpod_orchestrator.py — in-process orchestration
      (ensure-running-before-draft, idle-stop, daily cap, health-probe).
    - backend/scripts/runpod_check.py — operational CLI tool kept for
      break-glass / manual ops. Used to be self-contained; now a thin shell
      around these primitives.

Design choices:

    - **Functional API, stateless.** Every call takes api_key explicitly.
      Lets callers run multiple keys side-by-side (tests, multi-tenant) and
      avoids module-level state that's painful to mock.
    - **Each call opens a fresh httpx.Client.** Connection pooling matters
      below ~100ms call frequency; we're at ~1 call per cold-start or per
      idle tick, so the simplicity beats the perf.
    - **No print().** This module logs via the app logger but never prints —
      that stays in the CLI script. Service callers (the orchestrator) want
      structured logs and bubbled return values, not stdout chatter.
    - **Optional callbacks for polling loops.** `wait_for_running` and
      `probe_vllm` take optional `on_status` / `on_attempt` callbacks so the
      CLI can render live progress while the service path stays silent.
    - **Sync, not async.** The draft generation path is sync end-to-end
      (FastAPI runs sync route handlers in a threadpool), so matching that
      avoids accidental event-loop blocking. If we ever go fully async, add
      a sibling `runpod_client_async.py` rather than retrofitting.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

RUNPOD_API_BASE = "https://rest.runpod.io/v1"

# Defaults — every public function exposes these as keyword args so callers
# (orchestrator vs. CLI) can tune without forking the implementation.
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_WAIT_TIMEOUT_S = 300       # 5 min for pod -> RUNNING
DEFAULT_POLL_INTERVAL_S = 10
DEFAULT_PROBE_ATTEMPTS = 30        # 5 min ceiling for vLLM model load
DEFAULT_PROBE_DELAY_S = 10


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def pod_inference_url(pod_id: str) -> str:
    """The OpenAI-compatible base URL for a pod's exposed port 8000."""
    return f"https://{pod_id}-8000.proxy.runpod.net/v1"


# ── Pod state queries ────────────────────────────────────────────────────────


def fetch_pods(api_key: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> list[dict]:
    """List all pods on the account. Returns [] if none.

    Normalises the two response shapes RunPod has returned over time:
    older API returned ``{"pods": [...]}`` while newer returns a bare list.
    Raises httpx.HTTPStatusError on non-2xx.
    """
    with httpx.Client() as client:
        r = client.get(
            f"{RUNPOD_API_BASE}/pods",
            headers=_auth_headers(api_key),
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
    if isinstance(body, list):
        return body
    return body.get("pods", []) or []


def fetch_pod(api_key: str, pod_id: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> dict | None:
    """Fetch one pod by id. Returns None on 404 (pod not found / already terminated).

    The None-on-404 contract is important for the orchestrator: a missing
    pod is a stable state (zero billing, the goal state for terminate), not
    an error condition. Callers shouldn't have to catch an exception to
    handle "pod was already deleted."
    """
    with httpx.Client() as client:
        r = client.get(
            f"{RUNPOD_API_BASE}/pods/{pod_id}",
            headers=_auth_headers(api_key),
            timeout=timeout,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


# ── Pod lifecycle transitions ────────────────────────────────────────────────


def start_pod(api_key: str, pod_id: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """POST /pods/{id}/start. Returns True on accept, False on any failure.

    Failure cases are logged at WARNING with the status code + truncated
    body — that's typically enough to diagnose (e.g. capacity errors, auth
    failures). Callers decide what to do on False (retry, fall back, etc).
    """
    with httpx.Client() as client:
        r = client.post(
            f"{RUNPOD_API_BASE}/pods/{pod_id}/start",
            headers=_auth_headers(api_key),
            timeout=timeout,
        )
        if r.status_code < 400:
            logger.info("start_pod accepted for %s (HTTP %d)", pod_id, r.status_code)
            return True
        logger.warning(
            "start_pod failed for %s: HTTP %d %s",
            pod_id, r.status_code, r.text[:300],
        )
        return False


def stop_pod(api_key: str, pod_id: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """POST /pods/{id}/stop. Returns True on accept, False on any failure.

    Stopping a pod is *reversible* — pod ends in EXITED state with disk
    preserved (so a subsequent start_pod is a fast warm-start, not a full
    re-deploy). Use terminate_pod for permanent deletion.
    """
    with httpx.Client() as client:
        r = client.post(
            f"{RUNPOD_API_BASE}/pods/{pod_id}/stop",
            headers=_auth_headers(api_key),
            timeout=timeout,
        )
        if r.status_code < 400:
            logger.info("stop_pod accepted for %s (HTTP %d)", pod_id, r.status_code)
            return True
        logger.warning(
            "stop_pod failed for %s: HTTP %d %s",
            pod_id, r.status_code, r.text[:300],
        )
        return False


def terminate_pod(api_key: str, pod_id: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """DELETE /pods/{id}. Returns True on accept OR on 404 (idempotent).

    404 is treated as success: terminating an already-terminated pod is
    a no-op (the goal state — pod gone, no billing — is reached). Real
    failures (5xx, auth, network) return False with a logged warning.
    """
    with httpx.Client() as client:
        r = client.delete(
            f"{RUNPOD_API_BASE}/pods/{pod_id}",
            headers=_auth_headers(api_key),
            timeout=timeout,
        )
        if r.status_code < 400 or r.status_code == 404:
            logger.info("terminate_pod accepted for %s (HTTP %d)", pod_id, r.status_code)
            return True
        logger.warning(
            "terminate_pod failed for %s: HTTP %d %s",
            pod_id, r.status_code, r.text[:300],
        )
        return False


# ── Polling helpers ──────────────────────────────────────────────────────────


StatusCallback = Callable[[str | None, float], None]


def wait_for_running(
    api_key: str,
    pod_id: str,
    *,
    timeout_s: int = DEFAULT_WAIT_TIMEOUT_S,
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    on_status: StatusCallback | None = None,
) -> str | None:
    """Poll fetch_pod until desiredStatus == RUNNING. Returns inference URL on success.

    Returns None on timeout, on terminal pod states (FAILED/TERMINATED),
    or if the pod disappears mid-poll.

    `on_status(status, elapsed)` is called once per *change* in status —
    not on every poll — so the CLI gets concise progress updates and the
    service-path orchestrator can pass None for silent operation.
    """
    start = time.monotonic()
    last_status: str | None = None
    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout_s:
            logger.warning("wait_for_running timeout %ds for %s", timeout_s, pod_id)
            return None
        info = fetch_pod(api_key, pod_id)
        if info is None:
            logger.warning("wait_for_running: pod %s disappeared", pod_id)
            return None
        status = info.get("desiredStatus")
        if status != last_status:
            if on_status is not None:
                on_status(status, elapsed)
            last_status = status
        if status == "RUNNING":
            return pod_inference_url(pod_id)
        if status in ("FAILED", "TERMINATED"):
            logger.warning("wait_for_running: pod %s entered terminal state %r", pod_id, status)
            return None
        time.sleep(poll_interval_s)


# ── vLLM endpoint health + probe ─────────────────────────────────────────────


def list_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> list[str] | None:
    """GET <base_url>/models. Returns the list of model ids, or None if unhealthy.

    This is the orchestrator's *health probe*: cheap (one GET, ~50ms when
    healthy), unambiguous (200 + model list = vLLM serving; anything else
    = unhealthy or container-down). The orchestrator uses this to detect
    the "pod RUNNING but vLLM dead" case we hit during testing — when this
    returns None for a pod whose desiredStatus is RUNNING, vLLM has crashed
    inside the container and a stop+start cycle is the recovery action.
    """
    try:
        with httpx.Client() as client:
            r = client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
    except Exception as exc:
        logger.warning("list_models request raised %s: %s", type(exc).__name__, exc)
        return None

    if r.status_code != 200:
        logger.warning("list_models HTTP %d: %s", r.status_code, r.text[:300])
        return None
    try:
        body = r.json()
        return [item["id"] for item in body.get("data", []) if "id" in item]
    except Exception as exc:
        logger.warning("list_models parse error: %s", exc)
        return None


AttemptCallback = Callable[[int, int, str], None]


def probe_vllm(
    base_url: str,
    api_key: str,
    model: str,
    *,
    attempts: int = DEFAULT_PROBE_ATTEMPTS,
    delay_s: int = DEFAULT_PROBE_DELAY_S,
    on_attempt: AttemptCallback | None = None,
) -> bool:
    """Retry POST /chat/completions until vLLM responds 200, or attempts exhaust.

    A successful probe means: HTTP server is bound + vLLM is loaded + the
    model name we're sending exactly matches what vLLM has loaded. So this
    is a stronger guarantee than wait_for_running (which only confirms the
    pod is in RUNNING state).

    `on_attempt(attempt, total, detail)` is called once per failed try so
    the CLI can render progress. The service path passes None.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Respond with exactly one word."},
            {"role": "user", "content": "Say: pong"},
        ],
        "max_tokens": 10,
        "temperature": 0,
    }
    with httpx.Client() as client:
        for attempt in range(1, attempts + 1):
            try:
                r = client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=60.0,
                )
                if r.status_code == 200:
                    return True
                if on_attempt is not None:
                    on_attempt(attempt, attempts, f"HTTP {r.status_code}")
            except Exception as exc:
                if on_attempt is not None:
                    on_attempt(attempt, attempts, f"{type(exc).__name__}: {exc}")
            if attempt < attempts:
                time.sleep(delay_s)
    logger.warning("probe_vllm gave up after %d attempts (model=%s)", attempts, model)
    return False
