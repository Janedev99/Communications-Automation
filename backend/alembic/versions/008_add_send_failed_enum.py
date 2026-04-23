"""add send_failed to draft_status enum

Revision ID: 008
Revises: 007
Create Date: 2026-04-23
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE draft_status ADD VALUE IF NOT EXISTS 'send_failed'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    pass
