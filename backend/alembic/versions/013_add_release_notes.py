"""Add releases, user_release_dismissals tables and users.hide_releases_forever.

Supports the "What's New" modal feature: admin-curated, AI-drafted release
notes are surfaced to staff users on login. Releases can be drafted or
published; dismissals are tracked per-user with an optional "don't show again"
flag for users who prefer to suppress the modal entirely.

Revision ID: 013
Revises: 012
Create Date: 2026-05-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── Enum types (idempotent via DO $$ ... EXCEPTION block) ────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE release_status AS ENUM ('draft', 'published');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE release_generated_from AS ENUM (
                'github_api', 'manual_paste', 'manual_only'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ── releases ─────────────────────────────────────────────────────────────
    if "releases" not in existing_tables:
        op.create_table(
            "releases",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
            ),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "draft", "published",
                    name="release_status",
                    create_type=False,
                ),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "generated_from",
                postgresql.ENUM(
                    "github_api", "manual_paste", "manual_only",
                    name="release_generated_from",
                    create_type=False,
                ),
                nullable=True,
            ),
            sa.Column("commit_sha_at_release", sa.String(40), nullable=True),
            sa.Column(
                "created_by_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_releases_status "
            "ON releases (status)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_releases_published_at "
            "ON releases (published_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_releases_status_published_at "
            "ON releases (status, published_at DESC)"
        )

    # ── user_release_dismissals ───────────────────────────────────────────────
    if "user_release_dismissals" not in existing_tables:
        op.create_table(
            "user_release_dismissals",
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "release_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("releases.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "dont_show_again",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "dismissed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    # ── users.hide_releases_forever ───────────────────────────────────────────
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "hide_releases_forever" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "hide_releases_forever",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── users.hide_releases_forever ───────────────────────────────────────────
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "hide_releases_forever" in user_columns:
        op.drop_column("users", "hide_releases_forever")

    # ── user_release_dismissals ───────────────────────────────────────────────
    existing_tables = set(inspector.get_table_names())
    if "user_release_dismissals" in existing_tables:
        op.drop_table("user_release_dismissals")

    # ── releases (indexes first, then table) ──────────────────────────────────
    if "releases" in existing_tables:
        op.execute("DROP INDEX IF EXISTS ix_releases_status_published_at")
        op.execute("DROP INDEX IF EXISTS ix_releases_published_at")
        op.execute("DROP INDEX IF EXISTS ix_releases_status")
        op.drop_table("releases")

    # ── enum types ────────────────────────────────────────────────────────────
    op.execute("DROP TYPE IF EXISTS release_generated_from")
    op.execute("DROP TYPE IF EXISTS release_status")
