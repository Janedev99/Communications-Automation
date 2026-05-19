"""
One-off diagnostic: query vLLM's /v1/models endpoint on the running RunPod
pod to see which model(s) it actually has loaded.

This is throwaway — delete after debugging. Not committed.

Usage:
    cd backend
    python scripts/runpod_models.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

base = os.environ.get("LLM_BASE_URL", "").strip()
key = os.environ.get("LLM_API_KEY", "").strip()
expected_model = os.environ.get("LLM_MODEL", "").strip()

if not base or not key:
    print("[FATAL] LLM_BASE_URL or LLM_API_KEY missing from .env")
    sys.exit(2)

print(f"base_url:       {base}")
print(f"expected model: {expected_model!r}")
print()

try:
    r = httpx.get(
        f"{base}/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )
except Exception as exc:
    print(f"[FATAL] request raised {type(exc).__name__}: {exc}")
    sys.exit(2)

print(f"status: {r.status_code}")
print(f"body:")
print(r.text[:1500])
