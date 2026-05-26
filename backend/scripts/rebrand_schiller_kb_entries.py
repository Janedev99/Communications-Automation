"""Rebrand pre-existing Schiller-named KB entries to Point Profit.

Run manually:
    # Preview (default, safe — never mutates the DB):
    PYTHONPATH=. venv/Scripts/python.exe scripts/rebrand_schiller_kb_entries.py

    # Apply for real (requires explicit flag):
    PYTHONPATH=. venv/Scripts/python.exe scripts/rebrand_schiller_kb_entries.py --execute

Safety model
------------
``--dry-run`` is the default. The script never mutates the DB unless
``--execute`` is passed explicitly. Re-running with ``--dry-run`` against
either pre- or post-execute state is always safe.

Entries tagged with ``pp-seed-v1`` are skipped entirely. Those are Point
Profit canon seeded by ``scripts/seed_pointprofit_kb.py`` and must never
be auto-edited.

Replacement model
-----------------
Two categories of brand strings, kept deliberately separate:

* ``REPLACEMENTS`` — auto-applied. Only unambiguous brand substitutions
  (e.g. "Schiller CPA" → "Point Profit"). Order matters: longer matches
  go first so "Schiller CPA LLC" wins over "Schiller CPA".

* ``DETECT_ONLY`` — surfaced in the dry-run output but never mutated.
  These are brand-adjacent strings (the legacy email domain, ambiguous
  standalone "Schiller" references) whose correct rewrite depends on
  infra decisions the script cannot make. Flagged for human review.

Why ``DETECT_ONLY`` matters: the production mailbox is still
``jane@schilcpa.com``. Replacing the domain in a KB entry without
migrating the mailbox would put a non-functional address into AI-drafted
replies. Auto-replace would be incorrect.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email import KnowledgeEntry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rebrand_kb")


PP_SEED_MARKER = "pp-seed-v1"

# Order matters: longer matches first. ``str.replace`` is greedy but we
# iterate sequentially, so applying "Schiller CPA LLC" → "Point Profit
# LLC" before "Schiller CPA" → "Point Profit" prevents the shorter rule
# from producing "Point Profit LLC LLC" via double-rewrite.
REPLACEMENTS: list[tuple[str, str]] = [
    ("Schiller CPA, LLC", "Point Profit LLC"),
    ("Schiller CPA LLC", "Point Profit LLC"),
    ("Schiller CPA", "Point Profit"),
]

# Brand-adjacent strings flagged for human review. These intentionally
# overlap with REPLACEMENTS (e.g. "Schiller" appears inside "Schiller
# CPA"), so we run detection AFTER replacement to surface only what
# remains.
DETECT_ONLY: list[str] = [
    "schilcpa.com",
    "jane@schilcpa.com",
    "Schiller",  # standalone, after the "Schiller CPA" form is rewritten
    "schiller",  # lowercase (likely domain fragments or slugs)
]


@dataclass
class FieldChange:
    """One field's before/after diff for a single entry."""
    field_name: str
    before: str
    after: str


@dataclass
class EntryAudit:
    """Per-entry audit record produced by ``audit_entry``."""
    entry_id: str
    title: str
    tags: list[str]
    changes: list[FieldChange] = field(default_factory=list)
    leftover_mentions: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)


def apply_replacements(text: str, rules: list[tuple[str, str]]) -> str:
    """Apply each (find, replace) rule to ``text`` in order. Returns the
    rewritten string; returns the input unchanged if no rule matches."""
    out = text
    for find, replace in rules:
        out = out.replace(find, replace)
    return out


def detect_remaining(text: str, needles: Iterable[str]) -> list[str]:
    """Return the subset of ``needles`` that still appear in ``text``.

    Used after ``apply_replacements`` to flag brand-adjacent strings the
    auto-rewriter deliberately left alone."""
    return [n for n in needles if n in text]


def audit_entry(entry: KnowledgeEntry) -> EntryAudit:
    """Compute the proposed rewrite for one entry without touching it.

    Pure function over the entry's current field values. The returned
    ``EntryAudit`` is what the dry-run prints and what ``--execute``
    applies."""
    audit = EntryAudit(
        entry_id=str(entry.id),
        title=entry.title,
        tags=list(entry.tags or []),
    )

    new_title = apply_replacements(entry.title, REPLACEMENTS)
    if new_title != entry.title:
        audit.changes.append(FieldChange("title", entry.title, new_title))

    new_content = apply_replacements(entry.content, REPLACEMENTS)
    if new_content != entry.content:
        audit.changes.append(FieldChange("content", entry.content, new_content))

    leftover_haystack = "\n".join([new_title, new_content, " ".join(audit.tags)])
    audit.leftover_mentions = detect_remaining(leftover_haystack, DETECT_ONLY)

    return audit


def load_non_pp_entries(db: Session) -> list[KnowledgeEntry]:
    """Return all active KB entries that are NOT Point Profit canon.

    The ``pp-seed-v1`` tag is the marker: any entry carrying it was
    seeded by ``seed_pointprofit_kb.py`` and is off-limits."""
    stmt = (
        select(KnowledgeEntry)
        .where(KnowledgeEntry.is_active.is_(True))
        .order_by(KnowledgeEntry.title)
    )
    rows = list(db.execute(stmt).scalars())
    return [
        e for e in rows
        if PP_SEED_MARKER not in (e.tags or [])
    ]


def rebrand_entries(
    db: Session,
    entries: list[KnowledgeEntry],
    *,
    execute: bool,
) -> list[EntryAudit]:
    """Audit every entry; if ``execute`` is True, apply changes and commit.

    Returns the per-entry audits. With ``execute=False`` the DB is
    untouched. With ``execute=True`` all changes are applied in a single
    transaction — any failure rolls back the entire batch.
    """
    audits = [audit_entry(e) for e in entries]
    if not execute:
        return audits

    try:
        for entry, audit in zip(entries, audits):
            for change in audit.changes:
                setattr(entry, change.field_name, change.after)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return audits


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def format_audit(audit: EntryAudit) -> str:
    """Build the full per-entry report block as a single string.

    Returned as one string so the caller can ``print`` it in one shot —
    keeping each entry's lines contiguous in the output stream. Logger
    output and ``print`` output buffer independently on Windows, so
    interleaving them garbles per-entry ordering."""
    lines: list[str] = []
    lines.append(f"--- {audit.title} ---")
    lines.append(f"  id:   {audit.entry_id}")
    lines.append(f"  tags: {audit.tags or '(none)'}")

    if not audit.changes and not audit.leftover_mentions:
        lines.append("  no brand references found - leave as-is")
        return "\n".join(lines)

    for change in audit.changes:
        lines.append(f"  CHANGE {change.field_name}:")
        lines.append("    - before:")
        lines.append(_indent(change.before, "        "))
        lines.append("    + after:")
        lines.append(_indent(change.after, "        "))

    if audit.leftover_mentions:
        lines.append(
            f"  REVIEW: {len(audit.leftover_mentions)} brand-adjacent "
            f"string(s) remain (not auto-rewritten): "
            f"{', '.join(audit.leftover_mentions)}"
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rebrand_schiller_kb_entries",
        description=(
            "Audit and optionally rebrand non-PP knowledge entries from "
            "Schiller CPA → Point Profit. Dry-run by default."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes to the database. Without this flag, the script "
             "only prints the proposed diff.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = create_engine(settings.database_url)

    try:
        with Session(engine) as db:
            entries = load_non_pp_entries(db)
            print(
                f"Loaded {len(entries)} active non-PP entries "
                f"(filter: pp-seed-v1 tag excluded)\n"
            )

            audits = rebrand_entries(db, entries, execute=args.execute)
    except Exception as e:  # noqa: BLE001
        log.error("Rebrand failed: %s", e)
        return 2

    for audit in audits:
        print(format_audit(audit))
        print()  # blank line between entries

    changed = sum(1 for a in audits if a.has_changes)
    needs_review = sum(1 for a in audits if a.leftover_mentions)
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(
        f"Summary: {len(audits)} entries scanned · "
        f"{changed} with auto-changes · "
        f"{needs_review} with leftover review · "
        f"mode={mode}"
    )
    if not args.execute and changed:
        print(f"Re-run with --execute to apply the {changed} auto-changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
