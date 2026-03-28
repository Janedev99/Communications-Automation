"""Phase 2: Response Assistance — draft workflow enhancements and knowledge base extensions.

Revision ID: 002
Revises: 001
Create Date: 2026-03-24

Changes:
  - Adds 'edited' to the draft_status enum
  - Adds 7 new columns to draft_responses (version, original_body_text, ai_model,
    ai_prompt_tokens, ai_completion_tokens, knowledge_entry_ids, rejection_reason)
  - Adds 3 new columns to knowledge_entries (tags, entry_type, usage_count)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Add 'edited' to draft_status enum ────────────────────────────────────
    # PostgreSQL requires ALTER TYPE … ADD VALUE; cannot be done inside a transaction
    # that modifies data at the same time, but adding a value to an enum is safe.
    op.execute("ALTER TYPE draft_status ADD VALUE IF NOT EXISTS 'edited'")

    # ── draft_responses: new columns ─────────────────────────────────────────
    op.add_column(
        "draft_responses",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "draft_responses",
        sa.Column("original_body_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "draft_responses",
        sa.Column("ai_model", sa.String(64), nullable=True),
    )
    op.add_column(
        "draft_responses",
        sa.Column("ai_prompt_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "draft_responses",
        sa.Column("ai_completion_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "draft_responses",
        sa.Column("knowledge_entry_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "draft_responses",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )

    # ── knowledge_entries: new columns ────────────────────────────────────────
    op.add_column(
        "knowledge_entries",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=True,
        ),
    )
    op.add_column(
        "knowledge_entries",
        sa.Column("entry_type", sa.String(32), nullable=False, server_default="snippet"),
    )
    op.add_column(
        "knowledge_entries",
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    # ── knowledge_entries: remove columns ─────────────────────────────────────
    op.drop_column("knowledge_entries", "usage_count")
    op.drop_column("knowledge_entries", "entry_type")
    op.drop_column("knowledge_entries", "tags")

    # ── draft_responses: remove columns ───────────────────────────────────────
    op.drop_column("draft_responses", "rejection_reason")
    op.drop_column("draft_responses", "knowledge_entry_ids")
    op.drop_column("draft_responses", "ai_completion_tokens")
    op.drop_column("draft_responses", "ai_prompt_tokens")
    op.drop_column("draft_responses", "ai_model")
    op.drop_column("draft_responses", "original_body_text")
    op.drop_column("draft_responses", "version")

    # Note: PostgreSQL does not support removing enum values (ALTER TYPE … DROP VALUE).
    # The 'edited' value is left in the draft_status enum on downgrade.
    # To fully revert, drop and recreate the enum type manually if needed.
