"""
RunPod orchestrator persistent state.

Single-row table (keyed by pod_id) capturing everything the orchestrator
needs to make idle-stop / daily-cap / start-on-demand decisions across
process restarts. Lives in the same Postgres as the rest of the app so a
backend redeploy doesn't lose track of "we started the pod 4 hours ago,
don't break the daily cap."

Why a table and not in-memory state:

  - Process restarts (uvicorn --reload, Railway deploys, crashes) lose
    in-memory state. A pod we started would keep running unnoticed while
    the orchestrator forgot it exists. That's the exact billing surprise
    the orchestrator is supposed to prevent.

  - The watchdog can crash-recover by reading last_started_at and
    last_used_at on boot — it doesn't need to assume anything about
    "current" state.

  - Multi-process safety: future deployments may run more than one app
    process. The DB row is the single source of truth they coordinate on.

The pod_id is the primary key so a future "manage multiple pods" extension
(e.g. one per environment) drops in without schema changes.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RunPodState(Base):
    __tablename__ = "runpod_state"

    # The RunPod pod ID this row tracks. PK = single row per pod.
    pod_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Last time the orchestrator was asked to do work against the pod
    # (i.e. a draft was generated). Used for idle-timeout calculation:
    #   if now - last_used_at > IDLE_TIMEOUT and pod is RUNNING -> stop.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Wall-clock time the most recent start_pod accept was observed.
    # Used to compute the *current* session's uptime (and roll it into
    # uptime_today_seconds on stop).
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Most recent stop_pod accept time. Mostly for observability/debugging
    # ("when was the pod last off?") — not used in any decision path.
    last_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Orchestrator's last-known view of pod state. Values match RunPod's
    # desiredStatus (RUNNING / EXITED / FAILED / TERMINATED) plus the
    # orchestrator-only synthetic "UNHEALTHY" — pod reports RUNNING but
    # the /v1/models probe returned None (vLLM dead inside container).
    last_known_state: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    # Cumulative seconds the pod has been billing today (UTC date in
    # uptime_day_utc). Incremented at every stop and at every watchdog
    # tick while RUNNING. Reset to 0 when uptime_day_utc rolls forward
    # past midnight UTC.
    uptime_today_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # UTC date the uptime_today_seconds counter applies to. When the
    # orchestrator sees today's UTC date is later than this, it resets
    # the counter before adding the current session's uptime.
    uptime_day_utc: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    # Last time this row was modified by the orchestrator. Bumped on
    # every state-changing operation; useful for debugging stale state
    # ("was the orchestrator actually running yesterday?").
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
