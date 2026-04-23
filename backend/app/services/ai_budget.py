"""
AI token budget tracker (T2.3).

Tracks cumulative input + output tokens per calendar day across all Anthropic API
calls.  State is persisted to the `ai_budget_usage` table so it survives restarts.

Usage
-----
  from app.services.ai_budget import check_budget, record_usage

  check_budget()          # Raises BudgetExceededError if today's budget is exhausted
  record_usage(in_tok, out_tok)  # Accumulate token counts for the current day

Configuration
-------------
  DAILY_TOKEN_BUDGET env var (int, default 1_000_000).  Set to 0 to disable.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models.ai_budget import AIBudgetUsage  # noqa: F401 — model import for type checking

logger = logging.getLogger(__name__)


# ── Exception ─────────────────────────────────────────────────────────────────

class BudgetExceededError(Exception):
    """Raised when the daily token budget is exhausted."""


# ── Thread-safe in-memory cache (avoid a DB hit per email) ────────────────────
# We use a lock so concurrent workers in the thread pool don't create races.
_lock = threading.Lock()
_cache_date: date | None = None
_cache_input: int = 0
_cache_output: int = 0


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _load_today() -> tuple[int, int]:
    """Load today's token counts from the DB. Returns (input_tokens, output_tokens)."""
    today = _today()
    with SessionLocal() as db:
        try:
            row = db.execute(
                select(AIBudgetUsage).where(AIBudgetUsage.date == today)
            ).scalar_one_or_none()
            if row is None:
                return 0, 0
            return row.input_tokens, row.output_tokens
        except Exception as exc:
            # If the table doesn't exist yet (before migration), treat as 0
            logger.warning("ai_budget: could not load daily usage: %s", exc)
            return 0, 0


def _ensure_cache() -> None:
    """Populate the in-memory cache if it's stale (new day or first call)."""
    global _cache_date, _cache_input, _cache_output
    today = _today()
    if _cache_date != today:
        input_tok, output_tok = _load_today()
        _cache_date = today
        _cache_input = input_tok
        _cache_output = output_tok


def check_budget() -> None:
    """
    Raise BudgetExceededError if today's total tokens >= DAILY_TOKEN_BUDGET.

    If DAILY_TOKEN_BUDGET is 0 or unset, the check is skipped.
    """
    from app.config import get_settings
    settings = get_settings()
    limit = settings.daily_token_budget
    if limit <= 0:
        return  # Budget checking disabled

    with _lock:
        _ensure_cache()
        total = _cache_input + _cache_output

    if total >= limit:
        raise BudgetExceededError(
            f"Daily AI token budget exhausted: {total:,} / {limit:,} tokens used today."
        )


def record_usage(*, input_tokens: int, output_tokens: int) -> None:
    """
    Accumulate token usage for the current day.

    Updates both the in-memory cache and the DB (upsert).
    Non-fatal: logs a warning on DB errors rather than crashing.
    """
    global _cache_input, _cache_output, _cache_date
    today = _today()

    with _lock:
        if _cache_date != today:
            in_db, out_db = _load_today()
            _cache_date = today
            _cache_input = in_db
            _cache_output = out_db

        _cache_input += input_tokens
        _cache_output += output_tokens
        snap_in = _cache_input
        snap_out = _cache_output

    # Persist to DB outside the lock to avoid holding it during I/O
    with SessionLocal() as db:
        try:
            # Upsert: insert or increment
            db.execute(
                text(
                    """
                    INSERT INTO ai_budget_usage (date, input_tokens, output_tokens)
                    VALUES (:date, :inp, :out)
                    ON CONFLICT (date) DO UPDATE
                      SET input_tokens  = ai_budget_usage.input_tokens  + EXCLUDED.input_tokens,
                          output_tokens = ai_budget_usage.output_tokens + EXCLUDED.output_tokens
                    """
                ),
                {"date": today, "inp": input_tokens, "out": output_tokens},
            )
            db.commit()
        except Exception as exc:
            logger.warning("ai_budget: failed to persist token usage: %s", exc)
