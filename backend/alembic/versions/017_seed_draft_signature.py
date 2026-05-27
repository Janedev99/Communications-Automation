"""seed Jane's draft signature into system_settings

Revision ID: 017
Revises: 016
Create Date: 2026-05-28

Seeds the `draft_signature` system setting with Jane's email signature (provided
at the 2026-05-27 meeting) so AI drafts sign off with it immediately. Editable
afterward from Settings → Email Signature. Idempotent (ON CONFLICT DO NOTHING) —
won't clobber a value Jane has already customized.

Adding a system_settings row is deploy-safe: the prior app version only reads
the keys it asks for, so an unknown key it never queries can't affect it.
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO system_settings (key, value, updated_at)
        VALUES ('draft_signature', $sig$Thanks so much,

Jane

Jane M. Schilmoeller, CPA
Business Growth and Profitability Advisor

Schilmoeller & Schoenfield, PC
3131 Eastside Street, Suite 430
Houston, Texas  77098

Office:  (713) 527-9281 Ext 1
Direct Line:  (346) 415-6330
Fax: (346) 415-6337$sig$, now())
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE key = 'draft_signature'")
