"""Migration 020 — strip Jane's signature closing.

The repo has no alembic test-runner harness (017/018/019 are untested), so we
verify the two things that actually matter: (1) the new value is exactly the
old value minus the closing prefix (drift guard), and (2) the guarded UPDATE
transforms only an exact-seed match and no-ops otherwise.

The migration module name starts with a digit and `alembic/versions` is not an
importable package, so we load it by file path via importlib. `strip_jane_closing`
takes any object with `.execute(text, params)` — a Connection in the migration,
the test Session here (a bare Engine has no `.execute()` in SQLAlchemy 2.0, so we
pass `db_session`, never `db_session.get_bind()`).
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa

from app.models.user import User, UserRole

_MIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "020_strip_jane_signature_closing.py"
)
_spec = importlib.util.spec_from_file_location("migration_020", _MIG_PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_new_signature_is_old_minus_closing_prefix():
    assert mig._OLD_SIGNATURE.startswith(mig._CLOSING_PREFIX)
    assert mig._NEW_SIGNATURE == mig._OLD_SIGNATURE[len(mig._CLOSING_PREFIX):]
    # Sanity: the name/title block survives, the closing is gone.
    assert mig._NEW_SIGNATURE.startswith("Jane M. Schilmoeller, CPA")
    assert "Thanks so much," not in mig._NEW_SIGNATURE
    assert mig._NEW_SIGNATURE.endswith("Fax: (346) 415-6337")


def _make_user(db, email, signature):
    u = User(
        id=uuid.uuid4(),
        email=email,
        name="Test",
        hashed_password="x",
        role=UserRole.staff,
        signature=signature,
    )
    db.add(u)
    db.commit()
    return u


def test_strip_transforms_exact_seed_and_is_idempotent(db_session):
    email = f"jane+{uuid.uuid4().hex}@schilcpa.com"
    # Point the migration at this throwaway address for the test.
    orig_email = mig._JANE_EMAIL
    mig._JANE_EMAIL = email
    try:
        _make_user(db_session, email, mig._OLD_SIGNATURE)

        mig.strip_jane_closing(db_session)
        db_session.commit()
        row = db_session.execute(
            sa.select(User).where(User.email == email)
        ).scalar_one()
        db_session.refresh(row)
        assert row.signature == mig._NEW_SIGNATURE

        # Idempotent: running again does nothing (no exact-seed match now).
        mig.strip_jane_closing(db_session)
        db_session.commit()
        db_session.refresh(row)
        assert row.signature == mig._NEW_SIGNATURE
    finally:
        mig._JANE_EMAIL = orig_email


def test_strip_leaves_a_customized_signature_untouched(db_session):
    email = f"jane+{uuid.uuid4().hex}@schilcpa.com"
    custom = "Cheers,\n\nJane\n\nJane M. Schilmoeller, CPA"
    orig_email = mig._JANE_EMAIL
    mig._JANE_EMAIL = email
    try:
        _make_user(db_session, email, custom)
        mig.strip_jane_closing(db_session)
        db_session.commit()
        row = db_session.execute(
            sa.select(User).where(User.email == email)
        ).scalar_one()
        db_session.refresh(row)
        assert row.signature == custom  # not the seed → untouched
    finally:
        mig._JANE_EMAIL = orig_email
