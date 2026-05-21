"""add deleted + spam to email_status enum

Revision ID: 015
Revises: 014
Create Date: 2026-05-21

Supports the trash-management feature added after the 2026-05-21 client
meeting — staff can delete or mark-as-spam a thread, which moves all the
thread's inbound messages out of the Inbox via Microsoft Graph and parks
the local thread in one of these two terminal states.
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    # Same pattern as 008_add_send_failed_enum.py — `IF NOT EXISTS` makes
    # the migration safe to re-run if a deploy gets partially applied.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE email_status ADD VALUE IF NOT EXISTS 'deleted'")
        op.execute("ALTER TYPE email_status ADD VALUE IF NOT EXISTS 'spam'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating
    # the type. Same posture as the other enum-value migrations in this
    # tree — downgrade is a no-op.
    pass
