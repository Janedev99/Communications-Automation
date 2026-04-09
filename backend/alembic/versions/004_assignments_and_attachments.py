"""Add assigned_to_id to email_threads and attachments to email_messages.

Revision ID: 004
Revises: 003
Create Date: 2026-04-09

Changes:
  - Adds assigned_to_id (UUID FK → users.id, nullable, indexed) to email_threads
  - Adds attachments (JSON, nullable) to email_messages
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── email_threads: add assigned_to_id ────────────────────────────────────
    op.add_column(
        "email_threads",
        sa.Column(
            "assigned_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_email_threads_assigned_to_id",
        "email_threads",
        ["assigned_to_id"],
    )

    # ── email_messages: add attachments ──────────────────────────────────────
    op.add_column(
        "email_messages",
        sa.Column("attachments", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    # ── email_messages: remove attachments ───────────────────────────────────
    op.drop_column("email_messages", "attachments")

    # ── email_threads: remove assigned_to_id ─────────────────────────────────
    op.drop_index("ix_email_threads_assigned_to_id", table_name="email_threads")
    op.drop_column("email_threads", "assigned_to_id")
