"""
Alembic migration regression guard.

This test verifies that the migration files contain the SQL (or Alembic ops)
needed to add 'send_failed' to the draft_status enum on Postgres. It is a
fast static check — no database connection required — that guards against
accidental regression of CRIT-1.

Why static inspection instead of running `alembic upgrade head --sql`:
  The test environment overrides DATABASE_URL to SQLite. Alembic --sql
  (offline mode) uses the configured dialect; SQLite cannot render
  certain Postgres-specific ops (e.g., ADD VALUE on an enum type or ALTER
  of unique constraints), causing the subprocess to error out.
  Inspecting the migration source is simpler, faster, and dialect-agnostic.
"""
from __future__ import annotations

from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _read_migration(filename: str) -> str:
    """Return the source of a migration file."""
    path = VERSIONS_DIR / filename
    assert path.exists(), f"Migration file not found: {path}"
    return path.read_text(encoding="utf-8")


def test_migration_008_exists():
    """Migration 008 must exist as a versioned file."""
    files = list(VERSIONS_DIR.glob("008_*.py"))
    assert files, (
        "Migration 008 (008_add_send_failed_enum.py) is missing from "
        f"{VERSIONS_DIR}. This migration adds 'send_failed' to the Postgres "
        "draft_status enum and is required for prod correctness."
    )


def test_send_failed_in_migration_008():
    """
    Regression guard for CRIT-1: migration 008 must add 'send_failed'
    to the draft_status Postgres enum.
    """
    files = list(VERSIONS_DIR.glob("008_*.py"))
    assert files, "Migration 008 file is missing — cannot verify enum value."

    src = _read_migration(files[0].name)
    assert "send_failed" in src, (
        f"'send_failed' not found in {files[0].name}. "
        "Without this, Postgres rejects DraftStatus.send_failed writes with "
        "DataError: invalid input value for enum draft_status."
    )
    assert "ADD VALUE" in src, (
        f"'ADD VALUE' DDL not found in {files[0].name}. "
        "Migration must use ALTER TYPE ... ADD VALUE to extend the enum."
    )
    assert "autocommit_block" in src, (
        f"'autocommit_block' not found in {files[0].name}. "
        "PostgreSQL requires ALTER TYPE ... ADD VALUE to run outside a "
        "transaction block. Use op.get_context().autocommit_block()."
    )


def test_migration_008_revision_chain():
    """Migration 008 must chain from 007 so alembic runs them in order."""
    files = list(VERSIONS_DIR.glob("008_*.py"))
    assert files, "Migration 008 file is missing."

    src = _read_migration(files[0].name)
    assert 'down_revision = "007"' in src or "down_revision = '007'" in src, (
        "Migration 008 must set down_revision = '007' to maintain the "
        "correct migration chain."
    )


def test_all_draft_status_values_present_across_migrations():
    """
    Full enum coverage: all draft_status values must appear somewhere across
    the migrations directory (initial CREATE TYPE + subsequent ADD VALUE).
    """
    all_src = "\n".join(p.read_text(encoding="utf-8") for p in VERSIONS_DIR.glob("*.py"))

    expected_values = ["pending", "approved", "rejected", "sent", "edited", "send_failed"]
    missing = [v for v in expected_values if v not in all_src]
    assert not missing, (
        f"The following draft_status enum values are missing from all migration files: {missing}."
    )
