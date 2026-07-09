"""Add to_recipients / cc_recipients JSON columns to email_messages and
draft_responses (FEAT/reply-recipients).

email_messages: original To/CC for inbound messages, or what we actually
sent for outbound messages. NULL = legacy/unknown.

draft_responses: the EFFECTIVE recipients a draft will send to. Set at
draft creation to [thread.client_email] / []; NULL on pre-migration rows
falls back to the same default at send time.

Nullable ADD COLUMN only — no data rewrite, no backfill. Idempotent via the
inspector.get_columns guard pattern (copied from 012_message_save.py) so
re-running upgrade() on a partially-applied DB is a no-op for columns that
already exist.

Revision ID: 019
Revises: 018
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_messages = {c["name"] for c in inspector.get_columns("email_messages")}
    if "to_recipients" not in existing_messages:
        op.add_column(
            "email_messages",
            sa.Column("to_recipients", sa.JSON(), nullable=True),
        )
    if "cc_recipients" not in existing_messages:
        op.add_column(
            "email_messages",
            sa.Column("cc_recipients", sa.JSON(), nullable=True),
        )

    existing_drafts = {c["name"] for c in inspector.get_columns("draft_responses")}
    if "to_recipients" not in existing_drafts:
        op.add_column(
            "draft_responses",
            sa.Column("to_recipients", sa.JSON(), nullable=True),
        )
    if "cc_recipients" not in existing_drafts:
        op.add_column(
            "draft_responses",
            sa.Column("cc_recipients", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("draft_responses", "cc_recipients")
    op.drop_column("draft_responses", "to_recipients")
    op.drop_column("email_messages", "cc_recipients")
    op.drop_column("email_messages", "to_recipients")
