"""Add per-thread save / folder / note columns.

Jane wants to "save" notable threads into named folders (mirrors how she uses
Outlook folders today) without losing the thread context. Modeling this as
columns on email_threads keeps the queries simple and matches MVP scope —
folder hierarchy, per-message saves, and Office Tools integration are
deliberately deferred.

Revision ID: 011
Revises: 010
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent guards: this migration may run mid-flight in dev environments
    # where columns were partially applied. The pattern matches migration 001.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("email_threads")}

    if "is_saved" not in existing:
        op.add_column(
            "email_threads",
            sa.Column(
                "is_saved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "saved_folder" not in existing:
        op.add_column(
            "email_threads",
            sa.Column("saved_folder", sa.String(128), nullable=True),
        )
    if "saved_note" not in existing:
        op.add_column(
            "email_threads",
            sa.Column("saved_note", sa.Text(), nullable=True),
        )
    if "saved_at" not in existing:
        op.add_column(
            "email_threads",
            sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "saved_by_id" not in existing:
        op.add_column(
            "email_threads",
            sa.Column(
                "saved_by_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    existing_indexes = {i["name"] for i in inspector.get_indexes("email_threads")}
    if "ix_email_threads_is_saved" not in existing_indexes:
        op.create_index(
            "ix_email_threads_is_saved",
            "email_threads",
            ["is_saved"],
            postgresql_where=sa.text("is_saved = true"),
        )
    if "ix_email_threads_saved_folder" not in existing_indexes:
        op.create_index(
            "ix_email_threads_saved_folder",
            "email_threads",
            ["saved_folder"],
        )


def downgrade() -> None:
    op.drop_index("ix_email_threads_saved_folder", table_name="email_threads")
    op.drop_index("ix_email_threads_is_saved", table_name="email_threads")
    op.drop_column("email_threads", "saved_by_id")
    op.drop_column("email_threads", "saved_at")
    op.drop_column("email_threads", "saved_note")
    op.drop_column("email_threads", "saved_folder")
    op.drop_column("email_threads", "is_saved")
