"""RunPod per-day usage history.

Captures one row per (pod_id, UTC date) when the orchestrator's daily
counter rolls over at midnight UTC. Lets the admin UI render a "last 30
days" history without losing data on the rollover.

Why a separate table (vs. a JSON blob on runpod_state):

  - Composite PK (pod_id, day_utc) makes the rollover write idempotent.
    If _maybe_reset_daily_counter runs twice for the same day across
    process restarts, the second insert collides cleanly rather than
    creating a duplicate row.

  - Index on day_utc DESC means the common "last N days" query is a
    cheap range scan, not a full table scan. Rows accumulate at ~1/day
    so this stays small for a long time, but indexing now avoids
    surprise slowdowns later.

  - Easy to extend: a future "monthly summary" view can aggregate over
    these rows without re-deriving from session-level data we don't
    even store.

cost_per_hour_usd is the rate observed at capture time. cost_usd is
uptime_seconds * cost_per_hour_usd / 3600 computed at rollover. Both
are nullable — if RunPod's API was unreachable when the rollover fired,
we still persist uptime_seconds so the row isn't lost; cost just goes
null. Historic costs are immutable even if RunPod's pricing changes
later or we swap GPU types, which is the point of capturing the rate.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RunPodDailyUsage(Base):
    __tablename__ = "runpod_daily_usage"

    pod_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day_utc: Mapped[date] = mapped_column(Date, primary_key=True)
    uptime_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    cost_per_hour_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    cost_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
