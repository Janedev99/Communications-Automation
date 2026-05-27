"""add promotional category for automated / no-reply mail

Revision ID: 016
Revises: 015
Create Date: 2026-05-27

Adds a `promotional` value to the email_category enum so automated, bulk, and
no-reply mail (LinkedIn/Pinterest & app notifications, newsletters, brand
subscriptions, marketing) is tagged distinctly. The intake pipeline skips draft
generation for this category (saves AI credits) and the tier engine never marks
it T1 ("auto-handled"). Seeds a T1-disabled tier_rule row for the new category.
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block — commit it
    # in an autocommit block first so the INSERT below can reference the value.
    # `IF NOT EXISTS` keeps this safe to re-run on a partially-applied deploy.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE email_category ADD VALUE IF NOT EXISTS 'promotional'")

    # Seed the per-category tier rule — T1-disabled (promotional is never
    # auto-sent). ON CONFLICT makes this idempotent against the unique
    # (category) constraint.
    op.execute(
        """
        INSERT INTO tier_rules (id, category, t1_eligible, t1_min_confidence)
        VALUES (gen_random_uuid(), 'promotional', false, 0.92)
        ON CONFLICT (category) DO NOTHING
        """
    )


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value without recreating the type — no-op,
    # consistent with the other enum-value migrations in this tree. The seeded
    # tier_rule row is left in place (harmless).
    pass
