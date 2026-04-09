"""
In-memory per-user rate limiting for AI endpoints.

Uses the same sliding-window pattern as the login rate limiter in auth.py,
but keyed on user_id (UUID) rather than IP address, and with a longer
window (1 hour) suited to AI call quotas.

Usage
-----
    from app.utils.rate_limit import check_ai_rate_limit, record_ai_call

    # In a FastAPI endpoint (before the AI call):
    check_ai_rate_limit(current_user.id)
    record_ai_call(current_user.id)
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import DefaultDict

from fastapi import HTTPException, status

# ── Configuration ──────────────────────────────────────────────────────────────
_AI_RATE_LIMIT_MAX = 30          # maximum AI calls per user per window
_AI_RATE_LIMIT_WINDOW = 3600     # sliding window in seconds (1 hour)

# ── State ──────────────────────────────────────────────────────────────────────
# Maps user_id → list of monotonic timestamps for recent AI calls.
# Entries outside the window are pruned on each check to bound memory usage.
_ai_call_timestamps: DefaultDict[uuid.UUID, list[float]] = defaultdict(list)


def _prune_window(user_id: uuid.UUID) -> list[float]:
    """
    Remove timestamps older than the window and return the remaining ones.
    Cleans up the dict entry entirely when it becomes empty.
    """
    now = time.monotonic()
    cutoff = now - _AI_RATE_LIMIT_WINDOW
    recent = [t for t in _ai_call_timestamps[user_id] if t > cutoff]
    if recent:
        _ai_call_timestamps[user_id] = recent
    else:
        _ai_call_timestamps.pop(user_id, None)
    return recent


def check_ai_rate_limit(user_id: uuid.UUID) -> None:
    """
    Raise HTTP 429 if the user has exceeded the AI call limit for the current window.
    Does NOT record a new call — call record_ai_call() after the guard passes.
    """
    recent = _prune_window(user_id)
    if len(recent) >= _AI_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"AI call limit reached ({_AI_RATE_LIMIT_MAX} requests per hour). "
                "Please try again later."
            ),
        )


def record_ai_call(user_id: uuid.UUID) -> None:
    """Record that the user has made one AI call right now."""
    _ai_call_timestamps[user_id].append(time.monotonic())
