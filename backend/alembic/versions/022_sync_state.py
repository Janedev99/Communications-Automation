"""sync_state (delta cursors for Outlook->app delete sync)

Revision ID: 022
Revises: 021
Create Date: 2026-07-16

Adds the sync_state key/value table that persists MS Graph deltaLinks for the
Outlook->app email delete-sync (one row per watched folder: deleteditems,
junkemail). Additive-only; no existing tables touched.
"""
import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_state",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
