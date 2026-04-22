"""Add token_hash to sessions table and clear all existing sessions.

Revision ID: 005
Revises: 004
Create Date: 2026-04-23

Changes:
  - Adds `token_hash VARCHAR(64) NULL` to `sessions` (nullable initially)
  - Deletes all existing sessions (forces re-login — old UUID cookies are now invalid)
  - Makes `token_hash` NOT NULL
  - Adds index on `token_hash` for fast lookup

Migration strategy:
  The old auth material was the raw session UUID in the cookie.  The new scheme
  stores a SHA-256 hash of an opaque token and never puts the raw token in the DB.
  These are incompatible, so we simply delete all active sessions rather than try
  to backfill (backfilling would require the raw tokens, which we never stored).
  All users must log in again after this migration runs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add column as nullable (required before DELETE so no NOT NULL violation
    # on any sessions written between deploy and migration run — belt-and-suspenders).
    op.add_column(
        "sessions",
        sa.Column("token_hash", sa.String(64), nullable=True),
    )

    # Step 2: Delete all existing sessions.  Old cookies (raw UUID) are no longer valid
    # because validate_session now looks up by token_hash, not session id.
    op.execute("DELETE FROM sessions")

    # Step 3: Now that the table is empty, make the column NOT NULL.
    op.alter_column("sessions", "token_hash", nullable=False)

    # Step 4: Add index for O(1) lookup during validation.
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_column("sessions", "token_hash")
    # Note: sessions cleared during upgrade are NOT restored on downgrade.
    # Users will still need to log in again.
