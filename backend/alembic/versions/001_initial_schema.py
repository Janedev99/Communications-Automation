"""Initial schema — all Phase 1 tables.

Revision ID: 001
Revises:
Create Date: 2026-03-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    user_role = postgresql.ENUM("staff", "admin", name="user_role", create_type=True)
    email_status = postgresql.ENUM(
        "new", "categorized", "draft_ready", "pending_review",
        "sent", "escalated", "closed",
        name="email_status", create_type=True,
    )
    email_category = postgresql.ENUM(
        "status_update", "document_request", "appointment", "clarification",
        "general_inquiry", "complaint", "urgent", "uncategorized",
        name="email_category", create_type=True,
    )
    message_direction = postgresql.ENUM(
        "inbound", "outbound", name="message_direction", create_type=True
    )
    draft_status = postgresql.ENUM(
        "pending", "approved", "rejected", "sent",
        name="draft_status", create_type=True,
    )
    escalation_severity = postgresql.ENUM(
        "low", "medium", "high", "critical",
        name="escalation_severity", create_type=True,
    )
    escalation_status = postgresql.ENUM(
        "pending", "acknowledged", "resolved",
        name="escalation_status", create_type=True,
    )

    for enum_type in [
        user_role, email_status, email_category, message_direction,
        draft_status, escalation_severity, escalation_status,
    ]:
        enum_type.create(op.get_bind(), checkfirst=True)

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("staff", "admin", name="user_role", create_type=False),
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
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── sessions ──────────────────────────────────────────────────────────────
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
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # ── email_threads ─────────────────────────────────────────────────────────
    op.create_table(
        "email_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject", sa.String(998), nullable=False),
        sa.Column("client_email", sa.String(255), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("new", "categorized", "draft_ready", "pending_review",
                    "sent", "escalated", "closed",
                    name="email_status", create_type=False),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "category",
            postgresql.ENUM("status_update", "document_request", "appointment", "clarification",
                    "general_inquiry", "complaint", "urgent", "uncategorized",
                    name="email_category", create_type=False),
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
    op.create_index("ix_email_threads_client_email", "email_threads", ["client_email"])
    op.create_index("ix_email_threads_status", "email_threads", ["status"])
    op.create_index("ix_email_threads_category", "email_threads", ["category"])
    op.create_index("ix_email_threads_provider_thread_id", "email_threads", ["provider_thread_id"])

    # ── email_messages ────────────────────────────────────────────────────────
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
            postgresql.ENUM("inbound", "outbound", name="message_direction", create_type=False),
            nullable=False,
            server_default="inbound",
        ),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("raw_headers", sa.JSON(), nullable=True),
    )
    op.create_index("ix_email_messages_thread_id", "email_messages", ["thread_id"])
    op.create_index("ix_email_messages_received_at", "email_messages", ["received_at"])
    op.create_unique_constraint(
        "uq_message_id_header", "email_messages", ["message_id_header"]
    )

    # ── draft_responses ───────────────────────────────────────────────────────
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
            postgresql.ENUM("pending", "approved", "rejected", "sent",
                    name="draft_status", create_type=False),
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
    op.create_index("ix_draft_responses_thread_id", "draft_responses", ["thread_id"])

    # ── escalations ───────────────────────────────────────────────────────────
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
            postgresql.ENUM("low", "medium", "high", "critical",
                    name="escalation_severity", create_type=False),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "acknowledged", "resolved",
                    name="escalation_status", create_type=False),
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
    op.create_index("ix_escalations_thread_id", "escalations", ["thread_id"])
    op.create_index("ix_escalations_severity", "escalations", ["severity"])
    op.create_index("ix_escalations_status", "escalations", ["status"])
    op.create_index("ix_escalations_assigned_to_id", "escalations", ["assigned_to_id"])

    # ── knowledge_entries ─────────────────────────────────────────────────────
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
    op.create_index("ix_knowledge_entries_category", "knowledge_entries", ["category"])

    # ── audit_log ─────────────────────────────────────────────────────────────
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
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_entity_type", "audit_log", ["entity_type"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("knowledge_entries")
    op.drop_table("escalations")
    op.drop_table("draft_responses")
    op.drop_table("email_messages")
    op.drop_table("email_threads")
    op.drop_table("sessions")
    op.drop_table("users")

    for enum_name in [
        "escalation_status", "escalation_severity", "draft_status",
        "message_direction", "email_category", "email_status", "user_role",
    ]:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
