"""
Admin observability — integration health probe.

GET /admin/integrations  — return status + latency + config for each external
                            dependency the system relies on.

This endpoint is admin-only (it leaks config presence). It does NOT call out
to live external APIs (no Anthropic ping, no SMTP test) to avoid burning
tokens / triggering rate limits on every dashboard refresh. Latencies for
external services come from cached "last successful call" timestamps; only
Postgres is probed in real time (cheap SELECT 1).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.config import get_settings
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/integrations", tags=["admin"])


# Status taxonomy mirrored on the frontend HealthCard component.
StatusLiteral = Literal["healthy", "degraded", "down", "not_configured"]

POLLER_HEALTHY_THRESHOLD_MIN = 10
ANTHROPIC_HEALTHY_THRESHOLD_MIN = 30


def _age_minutes(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60


def _probe_postgres(db: Session) -> dict[str, Any]:
    """Real-time probe — runs SELECT 1 and times the round trip."""
    t0 = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "id": "postgres",
            "name": "Database (PostgreSQL)",
            "status": "healthy",
            "latency_ms": round(elapsed_ms, 1),
            "last_success_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
            "config": {"host": "configured"},
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.warning("integration probe: postgres failed: %s", exc)
        return {
            "id": "postgres",
            "name": "Database (PostgreSQL)",
            "status": "down",
            "latency_ms": round(elapsed_ms, 1),
            "last_success_at": None,
            "last_error": str(exc)[:200],
            "config": {"host": "configured"},
        }


def _probe_anthropic() -> dict[str, Any]:
    """Static probe — does not call the API. Reads cached timestamps + config."""
    settings = get_settings()
    from app.services.email_intake import last_successful_anthropic_at

    api_key = settings.anthropic_api_key or ""
    is_placeholder = api_key.startswith("sk-ant-placeholder")
    is_configured = bool(api_key) and not is_placeholder

    age = _age_minutes(last_successful_anthropic_at)

    # Determine status
    status: StatusLiteral
    last_error = None
    if not is_configured:
        status = "not_configured"
        last_error = "No real Anthropic API key configured"
    elif age is None:
        # Configured but never observed a success — neutral
        status = "healthy"
    elif age < ANTHROPIC_HEALTHY_THRESHOLD_MIN:
        status = "healthy"
    else:
        status = "degraded"
        last_error = f"No successful call in the last {round(age)}m"

    # Surface today's token usage / budget
    from app.services.ai_budget import _ensure_cache, _cache_input, _cache_output  # type: ignore
    try:
        _ensure_cache()
        tokens_today = _cache_input + _cache_output
    except Exception:
        tokens_today = 0
    budget = settings.daily_token_budget

    return {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "status": status,
        "latency_ms": None,
        "last_success_at": (
            last_successful_anthropic_at.isoformat()
            if last_successful_anthropic_at else None
        ),
        "last_error": last_error,
        "config": {
            "model": settings.claude_model,
            "api_key": "set" if is_configured else (
                "placeholder" if is_placeholder else "missing"
            ),
            "tokens_today": tokens_today,
            "daily_budget": budget,
            "budget_pct_used": round(100 * tokens_today / budget, 1) if budget > 0 else None,
        },
    }


def _probe_email_provider() -> dict[str, Any]:
    """Static probe — checks config + poller health from cached timestamps."""
    settings = get_settings()
    from app.services.email_intake import last_successful_poll_at

    provider = settings.email_provider  # "imap" or "msgraph"

    # Is it configured?
    is_configured: bool
    config: dict[str, Any] = {"provider": provider}
    if provider == "msgraph":
        is_configured = all([
            settings.msgraph_client_id,
            settings.msgraph_client_secret,
            settings.msgraph_tenant_id,
            settings.msgraph_mailbox,
        ])
        config["mailbox"] = settings.msgraph_mailbox or "(not set)"
        config["tenant"] = "set" if settings.msgraph_tenant_id else "missing"
    else:  # imap
        is_configured = bool(settings.imap_host) and bool(settings.imap_username)
        config["host"] = settings.imap_host or "(not set)"
        config["username"] = settings.imap_username or "(not set)"

    age = _age_minutes(last_successful_poll_at)
    status: StatusLiteral
    last_error = None

    if not is_configured:
        status = "not_configured"
        last_error = f"{provider} provider has missing credentials"
    elif age is None:
        status = "degraded"
        last_error = "Poller has not yet completed a successful cycle"
    elif age < POLLER_HEALTHY_THRESHOLD_MIN:
        status = "healthy"
    else:
        status = "degraded"
        last_error = f"No successful poll in the last {round(age)}m"

    return {
        "id": "email_provider",
        "name": f"Email Provider ({provider.upper() if provider == 'imap' else 'Microsoft Graph'})",
        "status": status,
        "latency_ms": None,
        "last_success_at": (
            last_successful_poll_at.isoformat()
            if last_successful_poll_at else None
        ),
        "last_error": last_error,
        "config": config,
    }


def _probe_notifications() -> dict[str, Any]:
    """Static probe — Slack webhook + log file."""
    settings = get_settings()
    has_slack = bool(settings.slack_webhook_url)
    has_log = bool(settings.notify_log_file)

    if not has_slack and not has_log:
        status: StatusLiteral = "not_configured"
        last_error = "No notification channel configured (Slack or log file)"
    else:
        # We can't probe these without firing them; treat as healthy when configured.
        status = "healthy"
        last_error = None

    return {
        "id": "notifications",
        "name": "Notifications",
        "status": status,
        "latency_ms": None,
        "last_success_at": None,
        "last_error": last_error,
        "config": {
            "slack_webhook": "set" if has_slack else "missing",
            "log_file": settings.notify_log_file or "stdout",
        },
    }


@router.get("")
def list_integrations(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Return health + config status for every integration.
    Admin-only; surfaces enough config to debug but always masks secrets.
    """
    settings = get_settings()
    items = [
        _probe_postgres(db),
        _probe_anthropic(),
        _probe_email_provider(),
        _probe_notifications(),
    ]

    # Overall status — worst-of
    severity_rank = {"down": 3, "degraded": 2, "not_configured": 1, "healthy": 0}
    overall = max(items, key=lambda i: severity_rank.get(i["status"], 0))["status"]

    return {
        "overall_status": overall,
        "shadow_mode": settings.shadow_mode,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
