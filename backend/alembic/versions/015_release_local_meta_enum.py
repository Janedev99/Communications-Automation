"""Add 'local_meta' value to the release_generated_from enum.

The release-notes feature now sources commits from a build-time generated
JSON file (backend/release-meta.json) instead of the GitHub API or admin
paste. New drafts created via that path are tagged generated_from=local_meta.

Existing values (github_api, manual_paste, manual_only) stay intact for
backward compat with already-published releases — they just aren't
emitted by the new code path.

Note on Postgres: ALTER TYPE ... ADD VALUE cannot run inside a transaction
block. We use the COMMIT-aware autocommit-block pattern that Alembic
supports via op.execute() inside a session that has been committed.

Revision ID: 015
Revises: 014
Create Date: 2026-05-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # ALTER TYPE ADD VALUE must run outside a transaction block on
        # Postgres pre-12; on 12+ it's allowed but we use IF NOT EXISTS
        # for idempotency.
        # The connection is in a transaction; commit it, do the ALTER,
        # let Alembic's normal flow continue.
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE release_generated_from ADD VALUE IF NOT EXISTS 'local_meta'"
            )
    # On SQLite, enums are just CHECK constraints over text; new string
    # values are accepted without migration. No-op.


def downgrade() -> None:
    # Postgres enum value removal is not supported without rewriting the
    # type — and dropping a value used by existing rows would break them.
    # Downgrade is intentionally a no-op; the value remains harmlessly.
    pass
