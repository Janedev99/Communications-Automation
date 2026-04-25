"""Phase 3b: system_settings key/value table for runtime-toggleable flags.

Seeds with `auto_send_enabled = "false"` — the global kill switch for T1
auto-send. Until an admin flips this to true (and a category is t1_eligible),
no email leaves the system without staff approval.

Revision ID: 010
Revises: 009
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        """
        INSERT INTO system_settings (key, value)
        VALUES ('auto_send_enabled', 'false')
        """
    )


def downgrade() -> None:
    op.drop_table("system_settings")
