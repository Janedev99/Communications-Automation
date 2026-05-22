"""Tests for scripts/seed_pointprofit_kb.py.

Three contracts to verify:
1. Every entry in SEED_ENTRIES has a valid shape (required fields, valid
   entry_type, non-empty tags).
2. Running the seeder against an empty DB inserts every entry.
3. Running the seeder a second time on the same DB produces zero inserts
   and zero updates — pure idempotency.
4. Editing one entry's content and re-seeding produces exactly one
   update (not a re-insert).
5. The KnowledgeService.get_relevant_entries query returns the seeded
   policies for an arbitrary email category (because policies are
   universal by design).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import KnowledgeEntry
from app.services.knowledge import get_knowledge_service

# Make scripts/ importable for tests. Pytest discovers tests/ but the
# seeder lives outside the package root, so it needs an explicit path entry.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
from scripts.seed_pointprofit_kb import (  # noqa: E402
    SEED_ENTRIES,
    SeedEntry,
    run_seeder,
)


VALID_ENTRY_TYPES = {"policy", "response_template", "snippet"}


# ─── Contract 1: SEED_ENTRIES shape ─────────────────────────────────────────

def test_every_seed_entry_has_required_fields() -> None:
    """Each entry must have title, content, category, tags, entry_type."""
    required = {"title", "content", "category", "tags", "entry_type"}
    for entry in SEED_ENTRIES:
        missing = required - set(entry.keys())
        assert not missing, f"Entry {entry.get('title')!r} missing fields: {missing}"


def test_every_seed_entry_uses_valid_entry_type() -> None:
    """entry_type must be one of the three the model accepts."""
    for entry in SEED_ENTRIES:
        assert entry["entry_type"] in VALID_ENTRY_TYPES, (
            f"Entry {entry['title']!r} has invalid entry_type={entry['entry_type']!r}; "
            f"expected one of {VALID_ENTRY_TYPES}"
        )


def test_every_seed_entry_has_nonempty_title_and_content() -> None:
    for entry in SEED_ENTRIES:
        assert entry["title"].strip(), f"Empty title: {entry}"
        assert entry["content"].strip(), f"Empty content for {entry['title']!r}"


def test_every_seed_entry_carries_the_marker_tag() -> None:
    """All seeded entries should carry the pp-seed-v1 marker tag so future
    seeder versions can target them precisely if a rename or sweep is needed."""
    for entry in SEED_ENTRIES:
        assert "pp-seed-v1" in entry["tags"], (
            f"Entry {entry['title']!r} missing marker tag 'pp-seed-v1'"
        )


def test_titles_are_unique() -> None:
    """Titles serve as the upsert natural key — duplicates would cause
    nondeterministic behavior on re-run."""
    titles = [e["title"] for e in SEED_ENTRIES]
    duplicates = {t for t in titles if titles.count(t) > 1}
    assert not duplicates, f"Duplicate titles in SEED_ENTRIES: {duplicates}"


# ─── Contract 2: Seeder behavior ────────────────────────────────────────────

def test_first_run_inserts_every_entry(db_session: Session) -> None:
    """Against an empty DB, all entries should be inserted."""
    _clear_pp_seeded_rows(db_session)

    counts = run_seeder(db_session)

    assert counts["inserted"] == len(SEED_ENTRIES)
    assert counts["updated"] == 0
    assert counts["unchanged"] == 0


def test_second_run_is_idempotent(db_session: Session) -> None:
    """A second run on the same DB should produce zero inserts AND zero
    updates — every entry recognized as already-current."""
    _clear_pp_seeded_rows(db_session)

    run_seeder(db_session)  # First pass — inserts everything
    counts = run_seeder(db_session)  # Second pass — should be a no-op

    assert counts["inserted"] == 0
    assert counts["updated"] == 0
    assert counts["unchanged"] == len(SEED_ENTRIES)


def test_modified_entry_triggers_exactly_one_update(db_session: Session) -> None:
    """If one entry's content drifts (e.g. human edit), the next seeder run
    should update that one row and report 'unchanged' for the rest."""
    _clear_pp_seeded_rows(db_session)
    run_seeder(db_session)

    # Tamper with one entry's content in the DB
    sample = SEED_ENTRIES[0]
    row = db_session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.title == sample["title"])
    ).scalar_one()
    row.content = "drifted content"
    db_session.commit()

    counts = run_seeder(db_session)

    assert counts["inserted"] == 0
    assert counts["updated"] == 1
    assert counts["unchanged"] == len(SEED_ENTRIES) - 1


# ─── Contract 3: KnowledgeService picks up seeded policies ──────────────────

def test_seeded_policies_surface_for_arbitrary_category(db_session: Session) -> None:
    """Policies must surface for every email category because the draft
    generator queries by category but always includes entry_type='policy'."""
    _clear_pp_seeded_rows(db_session)
    run_seeder(db_session)

    svc = get_knowledge_service()
    # Use an EmailCategory value that doesn't match any of our seeded
    # entries' categories — the only way they should still surface is via
    # the entry_type='policy' clause.
    entries = svc.get_relevant_entries(db_session, category="status_update", limit=20)

    policy_titles = {e.title for e in entries if e.entry_type == "policy"}
    expected_policies = {
        s["title"] for s in SEED_ENTRIES if s["entry_type"] == "policy"
    }
    missing = expected_policies - policy_titles
    assert not missing, f"Seeded policies not returned by KnowledgeService: {missing}"


# ─── Helpers ────────────────────────────────────────────────────────────────

def _clear_pp_seeded_rows(db: Session) -> None:
    """Strip any rows previous tests in the session may have inserted.
    The shared-DB fixture (StaticPool) accumulates rows across tests, so
    each idempotency test starts from a known-clean PP-seeded baseline."""
    db.execute(
        KnowledgeEntry.__table__.delete().where(
            KnowledgeEntry.title.in_([e["title"] for e in SEED_ENTRIES])
        )
    )
    db.commit()


# Type-checker shim — used only to validate the TypedDict imports
_ = SeedEntry
