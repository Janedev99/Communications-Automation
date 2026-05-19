"""
RunPod verification: read-only check of pod state.

Companion to runpod_bootstrap.py. Use this any time to verify that no
jane-autocomms pods are RUNNING (and therefore not billing). Read-only by
default — the only RunPod API call it makes is GET /pods.

Safety guarantees:

    1. Read-only by default. No POST, no DELETE, no state-changing call
       unless --start, --stop, or --terminate is passed AND the operator
       confirms with 'yes'.
    2. Output is whitelist-sanitized via SAFE_FIELDS. We never print pod
       env vars — Gar's other pods on this shared account contain plaintext
       credentials in env (see [[project-runpod-shutdown-rule]]).
    3. State-changing actions are always scoped to jane-autocomms-* pods,
       even when --all is used for listing. Gar's pods are visible but
       untouchable from this script.
    4. Exit code reflects safety state, so this can be cron'd:
            0 — no jane-autocomms pods in RUNNING state (safe, no billing)
            1 — at least one jane-autocomms pod is RUNNING (needs attention)
            2 — API error or config error (couldn't determine state)

Usage:

    cd backend
    python scripts/runpod_check.py              # check our pods only
    python scripts/runpod_check.py --all        # include all pods on account
    python scripts/runpod_check.py --pod-id <id>  # check one specific pod
    python scripts/runpod_check.py --start      # wake EXITED jane-* pod (warm start)
    python scripts/runpod_check.py --stop       # stop RUNNING jane-* pods (reversible)
    python scripts/runpod_check.py --terminate  # DELETE all jane-* pods (permanent)

Lifecycle reminder: --start brings an EXITED pod back to RUNNING (warm start,
~30-60s since model is cached on disk). --stop puts a pod in EXITED state —
container disk is preserved and accrues minor storage cost (~$0.005/hr for
50GB). --terminate removes the pod entirely (zero billing). Use --terminate
to clean up after bootstrap failures; --stop to pause but resume later;
--start to wake an EXITED pod for app testing.

Note: --start does NOT auto-stop on failure (unlike runpod_bootstrap.py).
The intent of --start is to leave the pod RUNNING for the operator to use,
so partial failures leave the pod in whatever state RunPod left it. Run
--stop explicitly when done.

Architectural note: REST primitives (start_pod / stop_pod / fetch_pod /
wait_for_running / probe_vllm) live in app.services.runpod_client and are
shared with the in-process orchestrator (app.services.runpod_orchestrator).
This script is the CLI shell on top: arg parsing, ownership gating,
confirmation prompts, exit codes, and print()-based progress output.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `app` importable when run as `python scripts/runpod_check.py` from backend/.
# Same trick used by scripts/seed_demo.py.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app.services.runpod_client import (  # noqa: E402
    fetch_pod,
    fetch_pods,
    pod_inference_url,
    probe_vllm,
    start_pod,
    stop_pod,
    terminate_pod,
    wait_for_running,
)

# ── Constants ────────────────────────────────────────────────────────────────

POD_NAME_PREFIX = "jane-autocomms"

# Whitelist of pod fields we'll render. Anything else is dropped before print.
# Crucial: 'env' is NOT in this list. Gar's pods have plaintext credentials
# there (HF_TOKEN, etc.) and we don't want them in our terminal scrollback.
SAFE_FIELDS = (
    "id",
    "name",
    "desiredStatus",
    "costPerHr",
    "gpuTypeIds",
    "imageName",
    "createdAt",
)


def _project_root() -> Path:
    # backend/scripts/runpod_check.py → project root is .parent.parent.parent
    return Path(__file__).resolve().parent.parent.parent


# ── Config ───────────────────────────────────────────────────────────────────


def load_api_key() -> str:
    env_path = _project_root() / ".env"
    if not env_path.exists():
        print(f"[FATAL] .env not found at {env_path}")
        sys.exit(2)
    load_dotenv(env_path, override=False)
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        print("[FATAL] LLM_API_KEY is empty in .env")
        sys.exit(2)
    return key


# ── CLI wrappers — add print() over the stateless REST primitives ────────────
# The functions in runpod_client log via logger but never print. These CLI
# wrappers add a one-line user-visible result; the maybe_* flows below stack
# additional context around them (banners, confirmations, exit codes).


def cli_stop(api_key: str, pod_id: str) -> bool:
    if stop_pod(api_key, pod_id):
        print(f"[STOP] pod {pod_id} stopped")
        return True
    print(f"[STOP] FAILED for {pod_id} — see logs above")
    return False


def cli_terminate(api_key: str, pod_id: str) -> bool:
    if terminate_pod(api_key, pod_id):
        print(f"[TERMINATE] pod {pod_id} deleted")
        return True
    print(f"[TERMINATE] FAILED for {pod_id} — see logs above")
    return False


def cli_start(api_key: str, pod_id: str) -> bool:
    if start_pod(api_key, pod_id):
        print(f"[START] pod {pod_id} start accepted")
        return True
    print(f"[START] FAILED for {pod_id} — see logs above")
    return False


def cli_wait_for_running(api_key: str, pod_id: str) -> str | None:
    print(f"[WAIT] polling pod {pod_id} for RUNNING (every 10s)...")

    def _on_status(status: str | None, elapsed: float) -> None:
        print(f"[WAIT] status={status} (elapsed {elapsed:.0f}s)")

    return wait_for_running(api_key, pod_id, on_status=_on_status)


def cli_probe_vllm(api_key: str, base_url: str, model: str) -> bool:
    print(f"[PROBE] confirming vLLM is serving (model={model})...")

    def _on_attempt(attempt: int, total: int, detail: str) -> None:
        print(f"[PROBE] attempt {attempt}/{total} {detail}")

    if probe_vllm(base_url, api_key, model, on_attempt=_on_attempt):
        print("[PROBE] OK")
        return True
    print("[PROBE] gave up — see logs above")
    return False


# ── Rendering ────────────────────────────────────────────────────────────────


def sanitize(pod: dict) -> dict:
    """Drop everything not in SAFE_FIELDS. Single chokepoint for credential safety."""
    return {k: pod.get(k) for k in SAFE_FIELDS if k in pod}


def print_pod_row(pod: dict) -> None:
    s = sanitize(pod)
    status = s.get("desiredStatus") or "?"
    marker = f"[{status}]"
    name = s.get("name") or "?"
    pid = s.get("id") or "?"
    cost = s.get("costPerHr")
    cost_str = f"${cost}/hr" if cost is not None else "?/hr"
    print(f"  {marker:14} {name:40} id={pid}  {cost_str}")


# ── Main ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only check of RunPod pod state. Exits 0 if safe, 1 if jane-autocomms pod is RUNNING."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include pods that don't match jane-autocomms-* prefix (e.g. Gar's other pods).",
    )
    parser.add_argument(
        "--pod-id",
        help="Check one specific pod by id instead of listing.",
    )
    # --start / --stop / --terminate target different lifecycle transitions
    # and combining any two would be ambiguous. argparse rejects at parse time.
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--start",
        action="store_true",
        help="Wake an EXITED jane-autocomms pod and wait until vLLM is serving. Billing resumes. Prompts for 'yes'.",
    )
    action.add_argument(
        "--stop",
        action="store_true",
        help="Stop RUNNING jane-autocomms pods (reversible — pod ends in EXITED state, disk preserved). Prompts for 'yes'.",
    )
    action.add_argument(
        "--terminate",
        action="store_true",
        help="PERMANENTLY DELETE all jane-autocomms pods (any state, including EXITED orphans). Disk wiped. Prompts for 'yes'.",
    )
    return parser.parse_args()


def maybe_stop_running(api_key: str, running: list[dict], stop_flag: bool) -> int:
    """Decide what to do about the running pods we found. Returns exit code."""
    if not stop_flag:
        print()
        print(f"[WARN] {len(running)} jane-autocomms pod(s) RUNNING — still billing.")
        print("       Re-run with --stop to halt them, or use the dashboard:")
        print("         https://www.runpod.io/console/pods")
        return 1

    print()
    print(f"[STOP] {len(running)} jane-autocomms pod(s) RUNNING. Listing:")
    for p in running:
        print_pod_row(p)
    print()
    try:
        confirm = input("Type 'yes' to stop ALL of the above: ")
    except EOFError:
        print("[ABORT] no TTY — refusing to stop without explicit confirmation.")
        return 1
    if confirm.strip().lower() != "yes":
        print("[ABORT] user did not type 'yes' — leaving pods running.")
        return 1

    all_ok = True
    for p in running:
        pid = p.get("id")
        if not pid:
            print("[STOP] skipping pod with missing id")
            all_ok = False
            continue
        if not cli_stop(api_key, pid):
            all_ok = False
    return 0 if all_ok else 1


def maybe_start(api_key: str, pod: dict) -> int:
    """Confirm + start + wait + probe vLLM for one EXITED pod."""
    pid = pod.get("id") or ""
    name = pod.get("name") or "?"
    status = pod.get("desiredStatus") or "?"
    cost = pod.get("costPerHr")

    if status == "RUNNING":
        url = pod_inference_url(pid)
        print()
        print(f"[OK] pod {pid} is already RUNNING.")
        print(f"     URL: {url}")
        return 0
    if status != "EXITED":
        print()
        print(f"[ABORT] pod {pid} is in {status!r} state — only EXITED pods can be started.")
        return 1

    print()
    cost_str = f"${cost}/hr" if cost is not None else "rate unknown"
    print(f"[START] Pod {name} ({pid}) will resume billing at {cost_str}.")
    print("        Warm start expected (~30-90s). Stop it with: python scripts/runpod_check.py --stop")
    try:
        confirm = input("Type 'yes' to start: ")
    except EOFError:
        print("[ABORT] no TTY — refusing to start without explicit confirmation.")
        return 1
    if confirm.strip().lower() != "yes":
        print("[ABORT] user did not type 'yes' — pod left in EXITED state.")
        return 1

    if not cli_start(api_key, pid):
        return 1

    url = cli_wait_for_running(api_key, pid)
    if not url:
        print()
        print("[WARN] start was accepted but pod did not reach RUNNING. Check dashboard.")
        return 1

    # Probe needs the model name. We try LLM_MODEL from env first (the .env
    # is the source of truth for "what model does the app expect"). If
    # unset, skip the probe and tell the user the pod is up but unverified.
    model = os.environ.get("LLM_MODEL", "").strip()
    if not model:
        print()
        print("[NOTE] LLM_MODEL not set in environment — skipping vLLM readiness probe.")
        print(f"       Pod is RUNNING at: {url}")
        print("       Test in the app, or set LLM_MODEL=... and re-run to probe.")
        return 0

    if not cli_probe_vllm(api_key, url, model):
        print()
        print("[WARN] pod is RUNNING but vLLM did not respond within the probe budget.")
        print(f"       URL: {url}")
        print("       It may still come up — check the app, or stop with: python scripts/runpod_check.py --stop")
        return 1

    print()
    print("=" * 72)
    print("READY — pod is RUNNING and vLLM is serving")
    print("=" * 72)
    print(f"URL:    {url}")
    print(f"Model:  {model}")
    print()
    print("When you're done testing: python scripts/runpod_check.py --stop")
    return 0


def maybe_terminate(api_key: str, candidates: list[dict]) -> int:
    """Permanently delete jane-autocomms pods regardless of their state."""
    if not candidates:
        print()
        print("[OK] No jane-autocomms pods to terminate.")
        return 0

    print()
    print(f"[TERMINATE] {len(candidates)} jane-autocomms pod(s) will be PERMANENTLY DELETED:")
    for p in candidates:
        print_pod_row(p)
    print()
    print("        This destroys the container disk. Cannot be undone.")
    try:
        confirm = input("Type 'yes' to terminate ALL of the above: ")
    except EOFError:
        print("[ABORT] no TTY — refusing to terminate without explicit confirmation.")
        return 1
    if confirm.strip().lower() != "yes":
        print("[ABORT] user did not type 'yes' — pods left untouched.")
        return 1

    all_ok = True
    for p in candidates:
        pid = p.get("id")
        if not pid:
            print("[TERMINATE] skipping pod with missing id")
            all_ok = False
            continue
        if not cli_terminate(api_key, pid):
            all_ok = False
    return 0 if all_ok else 1


def main() -> int:
    args = parse_args()
    api_key = load_api_key()

    # Branch 1: single pod by id
    if args.pod_id:
        pod = fetch_pod(api_key, args.pod_id)
        if pod is None:
            print(f"[OK] pod {args.pod_id} not found (already terminated or never existed). No billing.")
            return 0
        print(f"Pod {args.pod_id}:")
        print_pod_row(pod)

        is_ours = (pod.get("name") or "").startswith(POD_NAME_PREFIX)

        # --terminate works regardless of RUNNING state (the whole point is
        # cleaning up EXITED orphans). Still gated on ownership prefix.
        if args.terminate:
            if not is_ours:
                print()
                print(f"[NOTE] pod does not match {POD_NAME_PREFIX}-* prefix — refusing to terminate.")
                print("       Use RunPod dashboard if you really mean to delete this.")
                return 1
            return maybe_terminate(api_key, [pod])

        # --start: maybe_start handles its own state validation
        # (RUNNING → noop with [OK]; non-EXITED → refusal). We just enforce
        # the ownership prefix here so a stray --pod-id can't wake Gar's pods.
        if args.start:
            if not is_ours:
                print()
                print(f"[NOTE] pod does not match {POD_NAME_PREFIX}-* prefix — refusing to start.")
                print("       Use RunPod dashboard if you really mean to start this.")
                return 1
            return maybe_start(api_key, pod)

        # Default / --stop path: only relevant when pod is RUNNING.
        if pod.get("desiredStatus") == "RUNNING":
            if not is_ours:
                print()
                print(f"[NOTE] pod is RUNNING but does not match {POD_NAME_PREFIX}-* prefix.")
                print("       Not stopping — this is likely Gar's pod. Use dashboard if unsure.")
                return 1
            return maybe_stop_running(api_key, [pod], args.stop)
        print()
        print("[OK] pod is not RUNNING. No compute billing.")
        return 0

    # Branch 2: list all + filter
    pods = fetch_pods(api_key)
    if not args.all:
        pods = [p for p in pods if (p.get("name") or "").startswith(POD_NAME_PREFIX)]

    scope = "all pods on account" if args.all else f"pods matching '{POD_NAME_PREFIX}-*'"
    print(f"Found {len(pods)} {scope}:")
    if not pods:
        print("  (none — no jane-autocomms pods on this account, nothing billing)")
        return 0

    for p in pods:
        print_pod_row(p)

    # --terminate path: act on ALL jane-* pods regardless of state. Even
    # if the user passed --all to also show Gar's pods, action stays
    # prefix-locked to our own.
    if args.terminate:
        our_pods = [p for p in pods if (p.get("name") or "").startswith(POD_NAME_PREFIX)]
        return maybe_terminate(api_key, our_pods)

    # --start path (list mode, no --pod-id): auto-pick when exactly one
    # EXITED jane-* pod exists; otherwise require --pod-id. The "exactly
    # one" rule keeps us from silently waking the wrong pod if there's
    # ever more than one orphan EXITED instance lying around.
    if args.start:
        exited_ours = [
            p for p in pods
            if p.get("desiredStatus") == "EXITED"
            and (p.get("name") or "").startswith(POD_NAME_PREFIX)
        ]
        if not exited_ours:
            print()
            print("[OK] no jane-autocomms pods in EXITED state. Nothing to start.")
            print("     (use `python scripts/runpod_bootstrap.py` to create a fresh pod)")
            return 0
        if len(exited_ours) > 1:
            print()
            print(f"[ABORT] {len(exited_ours)} EXITED jane-autocomms pods. Pass --pod-id <id> to pick one:")
            for p in exited_ours:
                print_pod_row(p)
            return 1
        return maybe_start(api_key, exited_ours[0])

    # Default / --stop path: detection scoped to OUR pods that are RUNNING.
    running = [
        p for p in pods
        if p.get("desiredStatus") == "RUNNING"
        and (p.get("name") or "").startswith(POD_NAME_PREFIX)
    ]
    if not running:
        print()
        print("[OK] No jane-autocomms pods in RUNNING state. No compute billing.")
        return 0

    return maybe_stop_running(api_key, running, args.stop)


if __name__ == "__main__":
    sys.exit(main())
