"""Add draft_generation_failed tracking to email_threads and create ai_budget_usage table.

Revision ID: 007
Revises: 006
Create Date: 2026-04-23

Changes:
  - Adds `draft_generation_failed BOOLEAN NOT NULL DEFAULT FALSE` to email_threads
  - Adds `draft_generation_failed_at TIMESTAMP WITH TIME ZONE NULL` to email_threads
  - Creates `ai_budget_usage` table for daily token budget tracking (T2.3)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── email_threads: draft generation failure tracking (T2.5) ──────────────
    op.add_column(
        "email_threads",
        sa.Column(
            "draft_generation_failed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "email_threads",
        sa.Column(
            "draft_generation_failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ── ai_budget_usage table (T2.3) ──────────────────────────────────────────
    op.create_table(
        "ai_budget_usage",
        sa.Column("date", sa.Date(), primary_key=True, nullable=False),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_budget_usage")
    op.drop_column("email_threads", "draft_generation_failed_at")
    op.drop_column("email_threads", "draft_generation_failed")
