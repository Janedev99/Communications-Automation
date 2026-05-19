"""
One-off backfill: derive body_text from body_html for every EmailMessage where
body_text is NULL but body_html is set.

Context: MSGraphProvider.fetch_new_emails previously mapped body fields as
mutually exclusive, leaving body_text=None on every HTML email polled from
M365. The provider is now fixed (FIX/msgraph-empty-body-text), but the rows
already in the database are still empty on body_text — this script populates
them in place using the same _html_to_text converter the provider now uses.

Safe to run multiple times: idempotent (no-op for rows that already have
body_text). Defaults to --dry-run; pass --apply to write.

Usage:
  python scripts/backfill_msgraph_body_text.py            # dry-run (default)
  python scripts/backfill_msgraph_body_text.py --apply    # actually update
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `app.*` importable when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import SessionLocal
from app.models.email import EmailMessage
from app.services.email_provider import _html_to_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the changes. Without this flag, runs as dry-run.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        candidates = db.execute(
            select(EmailMessage).where(
                EmailMessage.body_text.is_(None),
                EmailMessage.body_html.isnot(None),
            )
        ).scalars().all()

        print(f"Candidates (body_text NULL, body_html NOT NULL): {len(candidates)}")
        if not candidates:
            print("Nothing to do.")
            return 0

        # Show a small sample for visual confirmation before applying.
        print("\nSample (first 3):")
        for m in candidates[:3]:
            derived = _html_to_text(m.body_html)
            preview = derived[:200].replace("\n", " | ")
            print(f"  - id={m.id} sender={m.sender!r}")
            print(f"    body_html length = {len(m.body_html)} chars")
            # ASCII-escape for safe printing on Windows cp1252 consoles —
            # real client emails contain emoji, em-dashes, etc.
            print(f"    derived body_text preview ({len(derived)} chars): {ascii(preview)}")

        if not args.apply:
            print(
                "\nDRY RUN — no changes written. "
                "Re-run with --apply to commit the backfill."
            )
            return 0

        updated = 0
        for m in candidates:
            derived = _html_to_text(m.body_html)
            # If derivation produces nothing usable (e.g. body_html was all CSS),
            # leave the row alone so the audit trail shows "no useful text",
            # rather than overwriting with empty string.
            if not derived:
                continue
            m.body_text = derived
            updated += 1

        db.commit()
        print(f"\nUpdated {updated} of {len(candidates)} rows.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
