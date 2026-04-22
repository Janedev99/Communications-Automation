"""Add send_attempts and send_idempotency_key to draft_responses.

Revision ID: 006
Revises: 005
Create Date: 2026-04-23

Changes:
  - Adds `send_attempts INT NOT NULL DEFAULT 0` to draft_responses
  - Adds `send_idempotency_key VARCHAR(64) NULL` to draft_responses

These fields prevent double-send races when the /send endpoint is retried:
  - send_attempts is incremented and committed BEFORE calling the email provider
  - send_idempotency_key (secrets.token_hex(32)) is generated on first send attempt
    and reused on retry; a second call with the same key skips the provider call
    and returns the persisted result
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "draft_responses",
        sa.Column(
            "send_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "draft_responses",
        sa.Column("send_idempotency_key", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("draft_responses", "send_idempotency_key")
    op.drop_column("draft_responses", "send_attempts")
