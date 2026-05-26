"""Tests for scripts/rebrand_schiller_kb_entries.py.

Five contracts to verify:

1. ``apply_replacements`` is a pure rewriter — known inputs map to known
   outputs, longer rules win when both could apply, no rule means no change.
2. ``detect_remaining`` flags brand-adjacent strings the replacer left alone.
3. ``audit_entry`` produces field-level diffs and surfaces leftover mentions,
   without touching the input entry.
4. ``load_non_pp_entries`` filters out anything tagged ``pp-seed-v1`` and
   anything inactive.
5. ``rebrand_entries`` is safe by default (dry-run leaves DB untouched) and
   produces an idempotent result under ``execute=True`` (re-running finds
   nothing to change).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import KnowledgeEntry

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
from scripts.rebrand_schiller_kb_entries import (  # noqa: E402
    DETECT_ONLY,
    PP_SEED_MARKER,
    REPLACEMENTS,
    apply_replacements,
    audit_entry,
    detect_remaining,
    load_non_pp_entries,
    rebrand_entries,
)


# ─── Contract 1: apply_replacements ─────────────────────────────────────────

def test_apply_replacements_rewrites_a_known_match() -> None:
    out = apply_replacements("Welcome to Schiller CPA.", REPLACEMENTS)
    assert out == "Welcome to Point Profit."


def test_apply_replacements_returns_input_when_no_rule_matches() -> None:
    text = "An entirely unrelated string about taxes."
    assert apply_replacements(text, REPLACEMENTS) == text


def test_apply_replacements_handles_multiple_occurrences() -> None:
    text = "Schiller CPA does X. Schiller CPA does Y."
    out = apply_replacements(text, REPLACEMENTS)
    assert out == "Point Profit does X. Point Profit does Y."


def test_apply_replacements_longest_rule_wins() -> None:
    """'Schiller CPA LLC' → 'Point Profit LLC' must beat 'Schiller CPA'
    → 'Point Profit', or the result would be 'Point Profit LLC LLC'."""
    out = apply_replacements("Schiller CPA LLC", REPLACEMENTS)
    assert out == "Point Profit LLC"


# ─── Contract 2: detect_remaining ───────────────────────────────────────────

def test_detect_remaining_finds_leftover_brand_strings() -> None:
    text = "Visit schilcpa.com or email jane@schilcpa.com."
    found = detect_remaining(text, DETECT_ONLY)
    assert "schilcpa.com" in found
    assert "jane@schilcpa.com" in found


def test_detect_remaining_empty_when_text_is_clean() -> None:
    text = "All references already migrated."
    assert detect_remaining(text, DETECT_ONLY) == []


# ─── Contract 3: audit_entry ────────────────────────────────────────────────

def test_audit_entry_rewrites_title_and_content_independently() -> None:
    entry = KnowledgeEntry(
        title="Schiller CPA disclaimer",
        content="This communication is from Schiller CPA, LLC.",
        category="legal",
        tags=[],
        entry_type="policy",
        is_active=True,
    )
    audit = audit_entry(entry)

    changed_fields = {c.field_name for c in audit.changes}
    assert changed_fields == {"title", "content"}

    title_diff = next(c for c in audit.changes if c.field_name == "title")
    assert title_diff.after == "Point Profit disclaimer"

    content_diff = next(c for c in audit.changes if c.field_name == "content")
    assert content_diff.after == "This communication is from Point Profit LLC."


def test_audit_entry_surfaces_leftover_mentions() -> None:
    entry = KnowledgeEntry(
        title="Welcome from Schiller CPA",
        content="Contact us at jane@schilcpa.com for details.",
        category="welcome",
        tags=[],
        entry_type="response_template",
        is_active=True,
    )
    audit = audit_entry(entry)

    # The title gets rewritten ("Schiller CPA" → "Point Profit").
    assert any(c.field_name == "title" for c in audit.changes)
    # The email address is in DETECT_ONLY, not REPLACEMENTS, so it
    # remains and is flagged for human review.
    assert "jane@schilcpa.com" in audit.leftover_mentions


def test_audit_entry_returns_no_changes_when_already_clean() -> None:
    entry = KnowledgeEntry(
        title="Point Profit welcome",
        content="From the Point Profit team.",
        category="welcome",
        tags=[],
        entry_type="response_template",
        is_active=True,
    )
    audit = audit_entry(entry)

    assert audit.changes == []
    assert audit.leftover_mentions == []


def test_audit_entry_does_not_mutate_input() -> None:
    """The audit must be a pure function — running it twice yields the
    same result and the source entry is untouched."""
    original_title = "Schiller CPA disclaimer"
    original_content = "Issued by Schiller CPA."
    entry = KnowledgeEntry(
        title=original_title,
        content=original_content,
        category="legal",
        tags=[],
        entry_type="policy",
        is_active=True,
    )
    audit_entry(entry)
    audit_entry(entry)  # second call

    assert entry.title == original_title
    assert entry.content == original_content


# ─── Contract 4: load_non_pp_entries ────────────────────────────────────────

def test_load_non_pp_entries_excludes_pp_seeded(db_session: Session) -> None:
    """PP-seeded entries (carrying the marker tag) must not be loaded."""
    _clear_kb(db_session)
    db_session.add_all([
        KnowledgeEntry(
            title="Old Schiller entry",
            content="Schiller CPA stuff.",
            tags=["legacy"],
            entry_type="policy",
            is_active=True,
        ),
        KnowledgeEntry(
            title="Point Profit canon",
            content="PP stuff.",
            tags=[PP_SEED_MARKER, "firm"],
            entry_type="policy",
            is_active=True,
        ),
    ])
    db_session.commit()

    rows = load_non_pp_entries(db_session)
    titles = {r.title for r in rows}
    assert "Old Schiller entry" in titles
    assert "Point Profit canon" not in titles


def test_load_non_pp_entries_excludes_inactive(db_session: Session) -> None:
    _clear_kb(db_session)
    db_session.add_all([
        KnowledgeEntry(
            title="Live entry",
            content="Schiller CPA active",
            tags=[],
            entry_type="snippet",
            is_active=True,
        ),
        KnowledgeEntry(
            title="Archived entry",
            content="Schiller CPA archived",
            tags=[],
            entry_type="snippet",
            is_active=False,
        ),
    ])
    db_session.commit()

    titles = {r.title for r in load_non_pp_entries(db_session)}
    assert "Live entry" in titles
    assert "Archived entry" not in titles


# ─── Contract 5: rebrand_entries safety + idempotency ───────────────────────

def test_dry_run_does_not_mutate_db(db_session: Session) -> None:
    _clear_kb(db_session)
    entry = KnowledgeEntry(
        title="Schiller CPA disclaimer",
        content="Issued by Schiller CPA.",
        tags=[],
        entry_type="policy",
        is_active=True,
    )
    db_session.add(entry)
    db_session.commit()

    rebrand_entries(db_session, load_non_pp_entries(db_session), execute=False)
    db_session.expire_all()  # force re-fetch from DB

    persisted = db_session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.title == "Schiller CPA disclaimer")
    ).scalar_one()
    assert persisted.title == "Schiller CPA disclaimer"
    assert persisted.content == "Issued by Schiller CPA."


def test_execute_applies_changes_and_is_idempotent(db_session: Session) -> None:
    _clear_kb(db_session)
    db_session.add(KnowledgeEntry(
        title="Schiller CPA disclaimer",
        content="Issued by Schiller CPA.",
        tags=[],
        entry_type="policy",
        is_active=True,
    ))
    db_session.commit()

    # First pass: rewrites
    audits1 = rebrand_entries(db_session, load_non_pp_entries(db_session), execute=True)
    assert sum(1 for a in audits1 if a.has_changes) == 1

    persisted = db_session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.title == "Point Profit disclaimer")
    ).scalar_one()
    assert persisted.content == "Issued by Point Profit."

    # Second pass: nothing to do
    audits2 = rebrand_entries(db_session, load_non_pp_entries(db_session), execute=True)
    assert all(not a.has_changes for a in audits2)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _clear_kb(db: Session) -> None:
    """Wipe the knowledge_entries table for a clean per-test baseline.

    The shared StaticPool fixture means rows accumulate across tests; each
    rebrand test wants a known-empty start state."""
    db.execute(KnowledgeEntry.__table__.delete())
    db.commit()


_ = pytest  # silence unused-import; the marker library needs the import
