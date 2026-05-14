"""Create runpod_state table for the in-process pod orchestrator.

Revision ID: 009
Revises: 008
Create Date: 2026-05-14

Backing store for app.services.runpod_orchestrator. Single-row-per-pod
state (keyed by pod_id) capturing last_used_at / last_started_at and the
daily uptime accumulator that enforces the daily cap. See
app/models/runpod_state.py for field-level docs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runpod_state",
        sa.Column("pod_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_known_state", sa.String(length=32), nullable=True),
        sa.Column(
            "uptime_today_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("uptime_day_utc", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("runpod_state")
