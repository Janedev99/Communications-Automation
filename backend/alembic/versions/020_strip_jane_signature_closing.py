"""strip the closing lines from Jane's personal signature

Revision ID: 020
Revises: 019
Create Date: 2026-07-09

Iteration 2 (signature closing split): the AI now writes an editable closing
line in the draft body, so the stored signature must be the name/title/firm
block ONLY — otherwise a sent email double-closes (AI closing + signature
closing). Jane's `users.signature` (seeded in 017, migrated into her row in
018) still begins with "Thanks so much,\n\nJane\n\n"; this removes exactly
that prefix.

Guarded + idempotent: the UPDATE only fires when the stored value still equals
the exact seeded text, so if Jane has already customized her signature the
migration no-ops and never clobbers her change (same spirit as 017/018 guards).
`_NEW_SIGNATURE` is derived from `_OLD_SIGNATURE` by removing `_CLOSING_PREFIX`,
so the two can never drift apart.
"""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

_JANE_EMAIL = "jane@schilcpa.com"

_CLOSING_PREFIX = "Thanks so much,\n\nJane\n\n"

# The exact value seeded in 017 and migrated into Jane's row in 018.
_OLD_SIGNATURE = """Thanks so much,

Jane

Jane M. Schilmoeller, CPA
Business Growth and Profitability Advisor

Schilmoeller & Schoenfield, PC
3131 Eastside Street, Suite 430
Houston, Texas  77098

Office:  (713) 527-9281 Ext 1
Direct Line:  (346) 415-6330
Fax: (346) 415-6337"""

# Name/title/firm block only — old value minus the leading closing.
_NEW_SIGNATURE = _OLD_SIGNATURE[len(_CLOSING_PREFIX):]


def _set_signature(bind, *, where_value: str, new_value: str) -> None:
    """Rewrite Jane's signature old->new, guarded on the exact current value.

    `bind` is anything with `.execute(text, params)` — a Connection in the
    migration, a Session in tests. `_JANE_EMAIL` is read at call time so tests
    can point it at a throwaway address.
    """
    bind.execute(
        sa.text(
            "UPDATE users SET signature = :new "
            "WHERE email = :email AND signature = :old"
        ),
        {"new": new_value, "old": where_value, "email": _JANE_EMAIL},
    )


def strip_jane_closing(bind) -> None:
    """Rewrite Jane's signature old->new, only if it still equals the seed."""
    _set_signature(bind, where_value=_OLD_SIGNATURE, new_value=_NEW_SIGNATURE)


def upgrade() -> None:
    strip_jane_closing(op.get_bind())


def downgrade() -> None:
    _set_signature(op.get_bind(), where_value=_NEW_SIGNATURE, new_value=_OLD_SIGNATURE)
