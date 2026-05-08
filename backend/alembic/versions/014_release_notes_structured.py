"""Add structured fields to releases: summary + highlights[].

Splits free-form `body` into a structured shape so the modal/archive can
render NEW/IMPROVED/FIXED chips like cappj. Existing published releases
keep their `body` and render via the legacy markdown fallback path —
new publishes will require `summary` + at least one highlight (enforced
in the API layer, not the schema).

- `summary` (Text, nullable): plain-language overview, 1-2 sentences
- `highlights` (JSON, NOT NULL, server_default '[]'): list of
    {category: "new" | "improved" | "fixed", text: str ≤ 140 chars}
- `body` becomes nullable so future releases can omit it

Backfill is intentional: existing rows get an empty highlights array so
the NOT NULL constraint holds without touching any release content.

Revision ID: 014
Revises: 013
Create Date: 2026-05-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "releases" not in set(inspector.get_table_names()):
        # Defensive: 013 didn't run. Skip — re-running 013 will create
        # the new shape directly via its own logic if updated to match.
        return

    release_columns = {c["name"] for c in inspector.get_columns("releases")}

    # ── summary (Text, nullable) ─────────────────────────────────────────────
    if "summary" not in release_columns:
        op.add_column(
            "releases",
            sa.Column("summary", sa.Text(), nullable=True),
        )

    # ── highlights (JSON, NOT NULL, default []) ──────────────────────────────
    # Strategy: add as nullable, backfill, then alter to NOT NULL. This is
    # the safe pattern across Postgres + SQLite without dialect branching.
    if "highlights" not in release_columns:
        op.add_column(
            "releases",
            sa.Column(
                "highlights",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            ),
        )
        # Backfill existing rows with empty array (server_default only
        # applies to INSERTs, not pre-existing rows).
        op.execute("UPDATE releases SET highlights = '[]' WHERE highlights IS NULL")
        # Now safe to enforce NOT NULL.
        with op.batch_alter_table("releases") as batch:
            batch.alter_column("highlights", nullable=False)

    # ── body becomes nullable ────────────────────────────────────────────────
    # Existing values are preserved. New releases may now skip body entirely
    # and rely on summary + highlights instead.
    with op.batch_alter_table("releases") as batch:
        batch.alter_column("body", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "releases" not in set(inspector.get_table_names()):
        return

    release_columns = {c["name"] for c in inspector.get_columns("releases")}

    # body must be NOT NULL again before dropping summary/highlights — but
    # that requires every row to have a body. If any row has body=NULL we
    # cannot safely re-tighten without losing data. Best-effort: refuse to
    # tighten if any NULLs exist; admin must repair manually.
    null_body_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM releases WHERE body IS NULL")
    ).scalar()
    if null_body_count == 0:
        with op.batch_alter_table("releases") as batch:
            batch.alter_column("body", existing_type=sa.Text(), nullable=False)

    if "highlights" in release_columns:
        op.drop_column("releases", "highlights")
    if "summary" in release_columns:
        op.drop_column("releases", "summary")
