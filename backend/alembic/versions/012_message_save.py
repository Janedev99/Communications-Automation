"""Add per-message save / folder / note columns to email_messages.

Mirrors migration 011 (which added the same columns to email_threads). Per
Jane's 05/02 product call: "so often it's just the singular email, you know,
because the threads get to be ridiculous." Per-thread save was the MVP; this
adds the per-message granularity she actually wanted.

Revision ID: 012
Revises: 011
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("email_messages")}

    if "is_saved" not in existing:
        op.add_column(
            "email_messages",
            sa.Column(
                "is_saved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "saved_folder" not in existing:
        op.add_column(
            "email_messages",
            sa.Column("saved_folder", sa.String(128), nullable=True),
        )
    if "saved_note" not in existing:
        op.add_column(
            "email_messages",
            sa.Column("saved_note", sa.Text(), nullable=True),
        )
    if "saved_at" not in existing:
        op.add_column(
            "email_messages",
            sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "saved_by_id" not in existing:
        op.add_column(
            "email_messages",
            sa.Column(
                "saved_by_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    existing_indexes = {i["name"] for i in inspector.get_indexes("email_messages")}
    if "ix_email_messages_is_saved" not in existing_indexes:
        op.create_index(
            "ix_email_messages_is_saved",
            "email_messages",
            ["is_saved"],
            postgresql_where=sa.text("is_saved = true"),
        )
    if "ix_email_messages_saved_folder" not in existing_indexes:
        op.create_index(
            "ix_email_messages_saved_folder",
            "email_messages",
            ["saved_folder"],
        )


def downgrade() -> None:
    op.drop_index("ix_email_messages_saved_folder", table_name="email_messages")
    op.drop_index("ix_email_messages_is_saved", table_name="email_messages")
    op.drop_column("email_messages", "saved_by_id")
    op.drop_column("email_messages", "saved_at")
    op.drop_column("email_messages", "saved_note")
    op.drop_column("email_messages", "saved_folder")
    op.drop_column("email_messages", "is_saved")
