"""Phase 3: Tier-based triage + categorization source.

Adds:
- email_threads.tier (T1 auto / T2 review / T3 escalate)
- email_threads.tier_set_at, tier_set_by
- email_threads.categorization_source (claude / rules_fallback / manual)
- email_threads.auto_sent_at  (audit trail for T1 auto-sends)
- tier_rules table (per-category T1 eligibility + confidence threshold)

Backfill is implicit via server_default — all existing rows become T2 (staff review),
which is the safe default. No row needs to migrate to T1 retroactively.

Revision ID: 009
Revises: 008
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


THREAD_TIER_VALUES = ("t1_auto", "t2_review", "t3_escalate")
CATEGORIZATION_SOURCE_VALUES = ("claude", "rules_fallback", "manual")
EMAIL_CATEGORY_VALUES = (
    "status_update", "document_request", "appointment", "clarification",
    "general_inquiry", "complaint", "urgent", "uncategorized",
)


def upgrade() -> None:
    # ── Create new enum types ──────────────────────────────────────────────
    thread_tier_enum = postgresql.ENUM(
        *THREAD_TIER_VALUES, name="thread_tier", create_type=True
    )
    cat_source_enum = postgresql.ENUM(
        *CATEGORIZATION_SOURCE_VALUES, name="categorization_source", create_type=True
    )
    bind = op.get_bind()
    thread_tier_enum.create(bind, checkfirst=True)
    cat_source_enum.create(bind, checkfirst=True)

    # ── email_threads additions ────────────────────────────────────────────
    op.add_column(
        "email_threads",
        sa.Column(
            "tier",
            postgresql.ENUM(*THREAD_TIER_VALUES, name="thread_tier", create_type=False),
            nullable=False,
            server_default="t2_review",
        ),
    )
    op.add_column(
        "email_threads",
        sa.Column("tier_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_threads",
        sa.Column("tier_set_by", sa.String(64), nullable=True),
    )
    op.add_column(
        "email_threads",
        sa.Column(
            "categorization_source",
            postgresql.ENUM(
                *CATEGORIZATION_SOURCE_VALUES,
                name="categorization_source",
                create_type=False,
            ),
            nullable=False,
            server_default="claude",
        ),
    )
    op.add_column(
        "email_threads",
        sa.Column("auto_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_threads_tier", "email_threads", ["tier"])

    # ── tier_rules table ───────────────────────────────────────────────────
    op.create_table(
        "tier_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "category",
            postgresql.ENUM(
                *EMAIL_CATEGORY_VALUES, name="email_category", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("t1_eligible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "t1_min_confidence", sa.Float(), nullable=False, server_default="0.92"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_unique_constraint("uq_tier_rules_category", "tier_rules", ["category"])

    # Seed: a row per category, all T1-disabled by default.
    # Admins must explicitly opt-in any category for auto-send.
    op.execute(
        """
        INSERT INTO tier_rules (id, category, t1_eligible, t1_min_confidence)
        VALUES
            (gen_random_uuid(), 'status_update',    false, 0.92),
            (gen_random_uuid(), 'document_request', false, 0.92),
            (gen_random_uuid(), 'appointment',      false, 0.95),
            (gen_random_uuid(), 'clarification',    false, 0.92),
            (gen_random_uuid(), 'general_inquiry',  false, 0.92),
            (gen_random_uuid(), 'complaint',        false, 0.99),
            (gen_random_uuid(), 'urgent',           false, 0.99),
            (gen_random_uuid(), 'uncategorized',    false, 0.99)
        """
    )


def downgrade() -> None:
    op.drop_table("tier_rules")
    op.drop_index("ix_email_threads_tier", table_name="email_threads")
    op.drop_column("email_threads", "auto_sent_at")
    op.drop_column("email_threads", "categorization_source")
    op.drop_column("email_threads", "tier_set_by")
    op.drop_column("email_threads", "tier_set_at")
    op.drop_column("email_threads", "tier")

    bind = op.get_bind()
    postgresql.ENUM(name="categorization_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="thread_tier").drop(bind, checkfirst=True)
