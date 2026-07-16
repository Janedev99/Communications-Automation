"""saved_folders registry (first-class folders)

Revision ID: 021
Revises: 020
Create Date: 2026-07-10

Adds the saved_folders registry table and backfills it with the distinct
saved_folder labels currently in use on saved threads/messages (source='app',
top-level), so the existing folder rail does not regress on first deploy.
"""
import uuid
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_folders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True),
                  sa.ForeignKey("saved_folders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="app"),
        sa.Column("outlook_folder_id", sa.String(length=512), nullable=True),
        sa.Column("outlook_item_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_saved_folders_name", "saved_folders", ["name"], unique=True)
    op.create_index("ix_saved_folders_parent_id", "saved_folders", ["parent_id"])

    # Backfill: one row per distinct non-null saved_folder label in use.
    conn = op.get_bind()
    names = set()
    for tbl in ("email_threads", "email_messages"):
        rows = conn.execute(sa.text(
            f"SELECT DISTINCT saved_folder FROM {tbl} "
            f"WHERE is_saved = true AND saved_folder IS NOT NULL"
        )).fetchall()
        names.update(r[0] for r in rows if r[0])
    for name in names:
        conn.execute(
            sa.text("INSERT INTO saved_folders (id, name, source) "
                    "VALUES (:id, :name, 'app')"),
            {"id": str(uuid.uuid4()), "name": name},
        )


def downgrade() -> None:
    op.drop_index("ix_saved_folders_parent_id", table_name="saved_folders")
    op.drop_index("ix_saved_folders_name", table_name="saved_folders")
    op.drop_table("saved_folders")
