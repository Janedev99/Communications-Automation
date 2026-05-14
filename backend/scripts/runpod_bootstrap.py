"""
RunPod bootstrap: one-shot deploy → verify → stop.

This is the FIRST-TIME setup script for the jane-autocomms RunPod integration.
It creates a single pod, runs one inference probe to confirm it works, prints
the URL we should pin into .env, and then ALWAYS stops the pod — even on
failure, KeyboardInterrupt, or unexpected exceptions.

This is NOT the production orchestrator. The orchestrator (idle-timeout
watchdog, admin UI, draft_generator integration) is a separate iteration on
its own branch. This script only exists to:

    1. Prove the RunPod API key has the perms we expect for create + stop
    2. Confirm vLLM + the chosen model actually serves correctly
    3. Pin a known-good LLM_BASE_URL into .env so subsequent work has a target

Safety guarantees (ordered by how badly we depend on them):

    1. try/finally — stop_pod runs no matter how main() exits, including
       KeyboardInterrupt. If the pod was ever created, it WILL get a stop call.
    2. Stop retries 3x with backoff. If all 3 fail, the script prints a
       LOUD warning with the pod ID and dashboard URL so a human can finish
       the job manually.
    3. Wall-clock deadline check inside every loop (HARD_TIMEOUT_SECONDS).
       If anything hangs beyond the budget, we abort and fall into finally.
    4. Explicit 'yes' confirmation before the create call. This is the only
       billable action — every other call is read-only or pod-stopping.
    5. Pod ID is printed PROMINENTLY right after creation so even if the
       process gets killed externally (SIGKILL), the human knows what to
       stop manually.

What this script does NOT protect against:

    - kill -9 / forced process termination → finally won't run. Mitigation:
      pod ID is printed; the next iteration (orchestrator) will own this.
    - Network partition during stop → all 3 retries may fail. Mitigation:
      loud warning, manual fallback.
    - Pod state corruption on RunPod's side → out of scope.

Usage:

    cd backend
    python scripts/runpod_bootstrap.py

Environment variables (read from project .env via dotenv):

    LLM_API_KEY     — required. The RunPod API key Gar shared. Also used as
                       the bearer token for the pod's inference endpoint.
    RUNPOD_GPU_TYPE — optional. Defaults to 'NVIDIA RTX A40'.
    RUNPOD_MODEL    — optional. Defaults to 'google/gemma-2-9b-it'.
    RUNPOD_POD_NAME — optional. Defaults to 'jane-autocomms-drafting-v0'.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ── Constants ────────────────────────────────────────────────────────────────

RUNPOD_API_BASE = "https://rest.runpod.io/v1"

# Wall-clock budget. If any single phase blows this, we abort + fall into stop.
# 15 min is enough for: pod create (~5s) + image pull (~30s) + model download
# (~2-3 min for 9B) + boot (~30s) + inference probe (~10s) with buffer.
HARD_TIMEOUT_SECONDS = 900

# Status-poll cadence while waiting for pod to reach RUNNING.
POLL_INTERVAL_SECONDS = 10

# How many times to retry an inference call once the pod is RUNNING (the HTTP
# server inside the pod may take a few seconds longer to come up than the
# pod's status flip — vLLM still loading the model into VRAM).
INFERENCE_RETRY_ATTEMPTS = 30  # 30 * 10s = 5 min ceiling — Gemma 9B cold start
INFERENCE_RETRY_DELAY_SECONDS = 10                # was tight at 3 min; 5 leaves buffer

# How many times to retry stop_pod before giving up + loud-warning.
STOP_RETRY_ATTEMPTS = 3
STOP_RETRY_DELAY_SECONDS = 3


def _project_root() -> Path:
    # backend/scripts/runpod_bootstrap.py  →  project root is .parent.parent.parent
    return Path(__file__).resolve().parent.parent.parent


# ── Config helpers ───────────────────────────────────────────────────────────


def load_env() -> dict[str, str]:
    """Load the project .env and return the values we care about. Does NOT echo the API key."""
    env_path = _project_root() / ".env"
    if not env_path.exists():
        print(f"[FATAL] .env not found at {env_path}")
        sys.exit(1)
    load_dotenv(env_path, override=False)

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        print("[FATAL] LLM_API_KEY is empty in .env")
        sys.exit(1)

    return {
        "api_key": api_key,
        # NB: RunPod's enum is opaque — "NVIDIA A40" not "NVIDIA RTX A40".
        # Other valid values: "NVIDIA GeForce RTX 4090", "NVIDIA RTX A5000",
        # "NVIDIA GeForce RTX 5090", "NVIDIA H100", "NVIDIA L40",
        # "NVIDIA A100 80GB PCIe" (full list returned in 400 response on bad
        # value). A100 has been the only consistently-available option for our
        # config — consumer/prosumer cards fail host-placement with 50GB disk.
        "gpu_type": os.environ.get("RUNPOD_GPU_TYPE", "NVIDIA A100 80GB PCIe"),
        # Default is ungated so the bootstrap runs without HuggingFace auth.
        # To use Gemma 2 9B (gated), set RUNPOD_MODEL=google/gemma-2-9b-it
        # AND add HF_TOKEN=hf_xxxxxxxx to .env.
        "model": os.environ.get("RUNPOD_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
        "pod_name": os.environ.get("RUNPOD_POD_NAME", "jane-autocomms-drafting-v0"),
        # Optional. Empty string means we won't set HF auth on the pod —
        # fine for open models, required for gated ones (Gemma, Llama, etc).
        "hf_token": os.environ.get("HF_TOKEN", "").strip(),
    }


def pod_config(cfg: dict[str, str]) -> dict:
    """Build the POST /pods payload from loaded config."""
    # The vllm/vllm-openai image expects --model as a docker CMD arg, NOT as
    # an env var. Setting MODEL=... in env makes vLLM silently load its
    # hardcoded default — the server comes up but serves the wrong model,
    # so our probe gets a 404 'model does not exist' from a healthy server.
    #
    # Field naming gotcha: RunPod's REST API calls this `dockerStartCmd`
    # (NOT `dockerArgs` — that's the GraphQL API's name) and it expects an
    # array of strings, not a single string. Each arg is a separate element
    # so model names with spaces stay intact.
    docker_start_cmd = ["--model", cfg["model"], "--host", "0.0.0.0", "--port", "8000"]

    # vLLM checks both HF_TOKEN and HUGGING_FACE_HUB_TOKEN depending on
    # version. Set both when we have a token so the image works regardless.
    env: dict[str, str] = {}
    if cfg.get("hf_token"):
        env["HF_TOKEN"] = cfg["hf_token"]
        env["HUGGING_FACE_HUB_TOKEN"] = cfg["hf_token"]

    return {
        "name": cfg["pod_name"],
        "imageName": "vllm/vllm-openai:latest",
        "gpuTypeIds": [cfg["gpu_type"]],
        "gpuCount": 1,
        "containerDiskInGb": 50,
        "volumeInGb": 0,  # no persistent volume — clean isolation from Gar's zu99kdxve8
        "ports": ["8000/http"],  # must be array, not string (RunPod schema)
        "dockerStartCmd": docker_start_cmd,
        "env": env,
    }


# ── Deadline helper ──────────────────────────────────────────────────────────


def check_deadline(start: float, label: str) -> None:
    """Raise TimeoutError if the wall-clock budget is exhausted."""
    elapsed = time.monotonic() - start
    if elapsed > HARD_TIMEOUT_SECONDS:
        raise TimeoutError(
            f"Hard timeout {HARD_TIMEOUT_SECONDS}s exceeded at step '{label}' "
            f"(elapsed {elapsed:.0f}s). Aborting — finally block will stop the pod."
        )


# ── RunPod API calls ─────────────────────────────────────────────────────────


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def create_pod(client: httpx.Client, api_key: str, payload: dict) -> dict:
    print("[CREATE] requesting new pod...")
    r = client.post(
        f"{RUNPOD_API_BASE}/pods",
        headers=_headers(api_key),
        json=payload,
        timeout=30.0,
    )
    if r.status_code >= 400:
        # 2000 chars not 500 — RunPod's schema errors list every valid enum
        # value in the response, which on first failure is exactly what you
        # need to fix the payload without a second round-trip.
        print(f"[CREATE] HTTP {r.status_code}: {r.text[:2000]}")
        r.raise_for_status()
    body = r.json()
    pod_id = body.get("id") or body.get("podId")
    if not pod_id:
        print(f"[CREATE] could not extract pod id from response: {json.dumps(body)[:500]}")
        raise RuntimeError("Pod creation response missing 'id'")
    return body


def get_pod_status(client: httpx.Client, api_key: str, pod_id: str) -> dict:
    r = client.get(
        f"{RUNPOD_API_BASE}/pods/{pod_id}",
        headers=_headers(api_key),
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


def stop_pod(client: httpx.Client, api_key: str, pod_id: str) -> bool:
    """Try hard to stop the pod. Returns True on success, False on total failure."""
    for attempt in range(1, STOP_RETRY_ATTEMPTS + 1):
        try:
            print(f"[STOP] attempt {attempt}/{STOP_RETRY_ATTEMPTS} — stopping pod {pod_id}...")
            r = client.post(
                f"{RUNPOD_API_BASE}/pods/{pod_id}/stop",
                headers=_headers(api_key),
                timeout=30.0,
            )
            if r.status_code < 400:
                print(f"[STOP] pod {pod_id} stop accepted (HTTP {r.status_code})")
                return True
            print(f"[STOP] HTTP {r.status_code}: {r.text[:300]}")
        except Exception as exc:
            print(f"[STOP] attempt {attempt} raised {type(exc).__name__}: {exc}")
        if attempt < STOP_RETRY_ATTEMPTS:
            time.sleep(STOP_RETRY_DELAY_SECONDS)
    return False


def loud_stop_failure(pod_id: str) -> None:
    """Print a hard-to-miss warning that a human needs to act."""
    border = "!" * 72
    print()
    print(border)
    print("!!  CRITICAL: POD STOP FAILED AFTER ALL RETRIES")
    print(f"!!  POD ID: {pod_id}")
    print("!!  This pod may STILL BE BILLING. Manual action required:")
    print("!!    1. Open https://www.runpod.io/console/pods")
    print(f"!!    2. Find pod {pod_id}")
    print("!!    3. Click 'Stop' or 'Terminate'")
    print("!!  Re-running this script will NOT clean it up — the script only")
    print("!!  stops pods it created in the same process. Stop it now.")
    print(border)
    print()


# ── Wait + probe ─────────────────────────────────────────────────────────────


def wait_for_running(client: httpx.Client, api_key: str, pod_id: str, start: float) -> str:
    """Poll until pod reports RUNNING. Returns the inference URL."""
    print(f"[WAIT] polling pod {pod_id} for RUNNING status (every {POLL_INTERVAL_SECONDS}s)...")
    last_status = None
    while True:
        check_deadline(start, "wait_for_running")
        info = get_pod_status(client, api_key, pod_id)
        status = info.get("desiredStatus", "?")
        if status != last_status:
            elapsed = time.monotonic() - start
            print(f"[WAIT] status={status} (elapsed {elapsed:.0f}s)")
            last_status = status
        if status == "RUNNING":
            url = f"https://{pod_id}-8000.proxy.runpod.net/v1"
            print(f"[WAIT] pod RUNNING. Inference URL: {url}")
            return url
        if status in ("FAILED", "TERMINATED", "EXITED"):
            raise RuntimeError(f"Pod entered unexpected status {status!r} before reaching RUNNING")
        time.sleep(POLL_INTERVAL_SECONDS)


def probe_inference(client: httpx.Client, base_url: str, api_key: str, model: str, start: float) -> None:
    """Send one chat completion to confirm the pod's HTTP server + model are live."""
    print(f"[PROBE] sending inference probe to {base_url} (model={model})...")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Respond with exactly one word."},
            {"role": "user", "content": "Say: pong"},
        ],
        "max_tokens": 10,
        "temperature": 0,
    }
    last_err: Exception | None = None
    for attempt in range(1, INFERENCE_RETRY_ATTEMPTS + 1):
        check_deadline(start, "probe_inference")
        try:
            r = client.post(
                f"{base_url}/chat/completions",
                headers=_headers(api_key),
                json=payload,
                timeout=60.0,
            )
            if r.status_code < 400:
                body = r.json()
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {})
                print(f"[PROBE] OK — response: {content!r}")
                print(f"[PROBE] tokens: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
                return
            print(f"[PROBE] attempt {attempt}/{INFERENCE_RETRY_ATTEMPTS} HTTP {r.status_code}: {r.text[:200]}")
            last_err = RuntimeError(f"HTTP {r.status_code}")
        except Exception as exc:
            last_err = exc
            print(f"[PROBE] attempt {attempt}/{INFERENCE_RETRY_ATTEMPTS} raised {type(exc).__name__}: {exc}")
        if attempt < INFERENCE_RETRY_ATTEMPTS:
            time.sleep(INFERENCE_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Inference probe failed after {INFERENCE_RETRY_ATTEMPTS} attempts: {last_err}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 72)
    print("RunPod bootstrap — deploy, probe, stop")
    print("=" * 72)

    cfg = load_env()
    payload = pod_config(cfg)
    print("Pod config:")
    print(json.dumps(payload, indent=2))
    print()
    print("Estimated cost: ~$0.10 (15 min @ ~$0.40/hr on A40).")
    print("Estimated worst case if shutdown fails and not noticed for an hour: ~$0.40.")
    print()

    try:
        confirm = input("This WILL create a pod and start billing. Type 'yes' to proceed: ")
    except EOFError:
        print("[ABORT] no TTY — refusing to deploy without explicit confirmation.")
        return 1
    if confirm.strip().lower() != "yes":
        print("[ABORT] user did not type 'yes' — exiting without creating a pod.")
        return 1

    start = time.monotonic()
    pod_id: str | None = None

    # Single httpx client reused for all API calls — better connection reuse.
    with httpx.Client() as client:
        try:
            pod = create_pod(client, cfg["api_key"], payload)
            pod_id = pod.get("id") or pod.get("podId")

            # PROMINENT: print pod id immediately so a SIGKILL-survival operator
            # still has the info they need to stop the pod manually.
            print()
            print("*" * 72)
            print(f"*  POD CREATED — id: {pod_id}")
            print(f"*  Save this in case the script crashes. To stop manually:")
            print(f"*  curl -X POST {RUNPOD_API_BASE}/pods/{pod_id}/stop \\")
            print(f"*    -H 'Authorization: Bearer <LLM_API_KEY>'")
            print("*" * 72)
            print()

            url = wait_for_running(client, cfg["api_key"], pod_id, start)
            probe_inference(client, url, cfg["api_key"], cfg["model"], start)

            print()
            print("=" * 72)
            print("SUCCESS — pod verified working")
            print("=" * 72)
            print(f"Elapsed:  {time.monotonic() - start:.0f}s")
            print(f"Pod ID:   {pod_id}")
            print(f"URL:      {url}")
            print(f"Model:    {cfg['model']}")
            print()
            print("Next step: add these to .env (keep DRAFT_AUTO_GENERATE=false")
            print("until the orchestrator iteration ships):")
            print(f"  LLM_BASE_URL={url}")
            print(f"  LLM_MODEL={cfg['model']}")
            print(f"  RUNPOD_POD_ID={pod_id}")
            print()
            return 0

        except KeyboardInterrupt:
            print("\n[INTERRUPT] Ctrl+C — entering shutdown via finally")
            return 130
        except Exception as exc:
            print(f"\n[ERROR] {type(exc).__name__}: {exc}")
            return 1
        finally:
            if pod_id:
                print()
                print("[CLEANUP] always-run stop_pod ...")
                ok = stop_pod(client, cfg["api_key"], pod_id)
                if not ok:
                    loud_stop_failure(pod_id)
                else:
                    print("[CLEANUP] pod stopped cleanly. No further billing.")


if __name__ == "__main__":
    sys.exit(main())