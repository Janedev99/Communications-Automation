"""Create runpod_daily_usage history table + last_cost_per_hour on runpod_state.

Revision ID: 014
Revises: 013
Create Date: 2026-05-15

Persists per-day uptime + cost so the admin UI can show a 30-day history
without losing data at the UTC date rollover (which previously zeroed
uptime_today_seconds without saving the prior day's total anywhere).

The added last_cost_per_hour_usd column on runpod_state caches the most
recent rate observed from RunPod, so the rollover write can compute
cost without an extra API call at the exact midnight tick (when one
might fail or be slow). See app/services/runpod_orchestrator.py for the
write path.

Composite PK (pod_id, day_utc) makes the rollover idempotent: a second
attempt to capture the same day's data is a no-op rather than a dupe.
Index on day_utc DESC supports the common "last N days" query without
a full scan.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runpod_daily_usage",
        sa.Column("pod_id", sa.String(length=64), nullable=False),
        sa.Column("day_utc", sa.Date(), nullable=False),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_per_hour_usd", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("pod_id", "day_utc", name="pk_runpod_daily_usage"),
    )
    op.create_index(
        "ix_runpod_daily_usage_day_utc_desc",
        "runpod_daily_usage",
        [sa.text("day_utc DESC")],
    )

    # Cached most-recent cost-per-hour so the rollover can compute cost
    # without an extra fetch_pod call right at midnight UTC.
    op.add_column(
        "runpod_state",
        sa.Column("last_cost_per_hour_usd", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runpod_state", "last_cost_per_hour_usd")
    op.drop_index(
        "ix_runpod_daily_usage_day_utc_desc",
        table_name="runpod_daily_usage",
    )
    op.drop_table("runpod_daily_usage")
