"""Initial schema — all Phase 1 tables.

Revision ID: 001
Revises:
Create Date: 2026-03-15

This migration is idempotent: every CREATE TYPE / CREATE TABLE / CREATE INDEX
is guarded so a partially-applied state (e.g. a previous deploy that crashed
mid-migration) can be re-run without DuplicateObject errors.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Idempotency helpers ──────────────────────────────────────────────────────
def _create_enum(name: str, values: Sequence[str]) -> None:
    """CREATE TYPE … AS ENUM, swallowing duplicate_object."""
    vals = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE {name} AS ENUM ({vals});
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :n"
        ),
        {"n": name},
    ).scalar()
    return bool(result)


# Reusable column types that reference pre-existing enums (never re-create).
def _enum(name: str, *values: str):
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    _create_enum("user_role", ["staff", "admin"])
    _create_enum(
        "email_status",
        ["new", "categorized", "draft_ready", "pending_review",
         "sent", "escalated", "closed"],
    )
    _create_enum(
        "email_category",
        ["status_update", "document_request", "appointment", "clarification",
         "general_inquiry", "complaint", "urgent", "uncategorized"],
    )
    _create_enum("message_direction", ["inbound", "outbound"])
    _create_enum("draft_status", ["pending", "approved", "rejected", "sent"])
    _create_enum("escalation_severity", ["low", "medium", "high", "critical"])
    _create_enum("escalation_status", ["pending", "acknowledged", "resolved"])

    # ── users ─────────────────────────────────────────────────────────────────
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column(
                "role",
                _enum("user_role", "staff", "admin"),
                nullable=False,
                server_default="staff",
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        )
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)')

    # ── sessions ──────────────────────────────────────────────────────────────
    if not _table_exists("sessions"):
        op.create_table(
            "sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)')

    # ── email_threads ─────────────────────────────────────────────────────────
    if not _table_exists("email_threads"):
        op.create_table(
            "email_threads",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("subject", sa.String(998), nullable=False),
            sa.Column("client_email", sa.String(255), nullable=False),
            sa.Column("client_name", sa.String(255), nullable=True),
            sa.Column(
                "status",
                _enum("email_status", "new", "categorized", "draft_ready",
                      "pending_review", "sent", "escalated", "closed"),
                nullable=False,
                server_default="new",
            ),
            sa.Column(
                "category",
                _enum("email_category", "status_update", "document_request",
                      "appointment", "clarification", "general_inquiry",
                      "complaint", "urgent", "uncategorized"),
                nullable=False,
                server_default="uncategorized",
            ),
            sa.Column("category_confidence", sa.Float(), nullable=True),
            sa.Column("ai_summary", sa.Text(), nullable=True),
            sa.Column("provider_thread_id", sa.String(512), nullable=True),
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
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_threads_client_email ON email_threads (client_email)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_threads_status ON email_threads (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_threads_category ON email_threads (category)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_threads_provider_thread_id ON email_threads (provider_thread_id)')

    # ── email_messages ────────────────────────────────────────────────────────
    if not _table_exists("email_messages"):
        op.create_table(
            "email_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "thread_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("message_id_header", sa.String(998), nullable=False, unique=True),
            sa.Column("sender", sa.String(255), nullable=False),
            sa.Column("recipient", sa.String(255), nullable=True),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "direction",
                _enum("message_direction", "inbound", "outbound"),
                nullable=False,
                server_default="inbound",
            ),
            sa.Column("is_processed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("raw_headers", sa.JSON(), nullable=True),
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_messages_thread_id ON email_messages (thread_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_messages_received_at ON email_messages (received_at)')

    # ── draft_responses ───────────────────────────────────────────────────────
    if not _table_exists("draft_responses"):
        op.create_table(
            "draft_responses",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "thread_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("body_text", sa.Text(), nullable=False),
            sa.Column(
                "status",
                _enum("draft_status", "pending", "approved", "rejected", "sent"),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "reviewed_by_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_draft_responses_thread_id ON draft_responses (thread_id)')

    # ── escalations ───────────────────────────────────────────────────────────
    if not _table_exists("escalations"):
        op.create_table(
            "escalations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "thread_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column(
                "severity",
                _enum("escalation_severity", "low", "medium", "high", "critical"),
                nullable=False,
                server_default="medium",
            ),
            sa.Column(
                "status",
                _enum("escalation_status", "pending", "acknowledged", "resolved"),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "assigned_to_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "resolved_by_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("resolution_notes", sa.Text(), nullable=True),
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_escalations_thread_id ON escalations (thread_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_escalations_severity ON escalations (severity)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_escalations_status ON escalations (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_escalations_assigned_to_id ON escalations (assigned_to_id)')

    # ── knowledge_entries ─────────────────────────────────────────────────────
    if not _table_exists("knowledge_entries"):
        op.create_table(
            "knowledge_entries",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("category", sa.String(128), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_by_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
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
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_knowledge_entries_category ON knowledge_entries (category)')

    # ── audit_log ─────────────────────────────────────────────────────────────
    if not _table_exists("audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("action", sa.String(128), nullable=False),
            sa.Column("entity_type", sa.String(64), nullable=False),
            sa.Column("entity_id", sa.String(128), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("ip_address", sa.String(45), nullable=True),
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_entity_type ON audit_log (entity_type)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_entity_id ON audit_log (entity_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at)')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS knowledge_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS escalations CASCADE")
    op.execute("DROP TABLE IF EXISTS draft_responses CASCADE")
    op.execute("DROP TABLE IF EXISTS email_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS email_threads CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    for enum_name in [
        "escalation_status", "escalation_severity", "draft_status",
        "message_direction", "email_category", "email_status", "user_role",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
