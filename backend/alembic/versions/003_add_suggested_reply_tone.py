"""Add suggested_reply_tone column to email_threads.

Revision ID: 003
Revises: 002
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_threads",
        sa.Column("suggested_reply_tone", sa.String(32), nullable=True, server_default="professional"),
    )


def downgrade() -> None:
    op.drop_column("email_threads", "suggested_reply_tone")
