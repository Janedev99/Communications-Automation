"""
One-off cleanup: remove pre-cutover demo threads (and cascading messages,
drafts, escalations) so first-login users see only real M365-polled content.

Context: when the project was set up, `scripts/seed_demo.py` populated the
DB with fixture threads representing realistic client emails (Carol Bishop,
Diane Moreau, Linda Castellano, etc.) so the dashboard had content during
development. After the M365 cutover (2026-05-15) real client mail started
flowing in. The demo threads stuck around and were misleading:
  - The "3" red badge on the Escalations nav item was counting 3 demo
    escalations (IRS CP2000, PII compliance, invoice dispute) as if they
    were real.
  - Demo drafts in `sent` state looked like the system had been mailing
    out replies.
  - First-login users couldn't tell which content was real vs. seeded.

This script deletes everything tied to a thread created before
2026-05-15 UTC — the M365 cutover date. Idempotent: re-running on a
post-cleanup DB is a no-op.

Run from backend/:
  python scripts/remove_demo_threads.py            # dry-run preview
  python scripts/remove_demo_threads.py --apply    # commit the deletion
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete as sql_delete, func, select

from app.database import SessionLocal
from app.models.email import DraftResponse, EmailMessage, EmailThread
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus


CUTOFF = datetime(2026, 5, 15, tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag, runs as dry-run preview.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        ids = [
            row[0]
            for row in db.execute(
                select(EmailThread.id).where(EmailThread.created_at < CUTOFF)
            ).all()
        ]
        if not ids:
            print(f"No threads created before {CUTOFF.date()} — nothing to do.")
            return 0

        # Cascade counts for the report
        esc_count = db.execute(
            select(func.count(Escalation.id)).where(Escalation.thread_id.in_(ids))
        ).scalar()
        draft_count = db.execute(
            select(func.count(DraftResponse.id)).where(DraftResponse.thread_id.in_(ids))
        ).scalar()
        msg_count = db.execute(
            select(func.count(EmailMessage.id)).where(EmailMessage.thread_id.in_(ids))
        ).scalar()

        print(f"Pre-cutover threads (created before {CUTOFF.date()}): {len(ids)}")
        print(f"  Cascading deletions:")
        print(f"    escalations : {esc_count}")
        print(f"    drafts      : {draft_count}")
        print(f"    messages    : {msg_count}")
        print()

        if not args.apply:
            print("DRY RUN -- no changes written. Re-run with --apply to commit.")
            return 0

        # FK-safe order: leaves first, then root.
        db.execute(sql_delete(Escalation).where(Escalation.thread_id.in_(ids)))
        db.execute(sql_delete(DraftResponse).where(DraftResponse.thread_id.in_(ids)))
        db.execute(sql_delete(EmailMessage).where(EmailMessage.thread_id.in_(ids)))
        db.execute(sql_delete(EmailThread).where(EmailThread.id.in_(ids)))
        db.commit()

        # Post-state for the operator's confidence
        remaining = db.execute(select(func.count(EmailThread.id))).scalar()
        high_crit = db.execute(
            select(func.count(Escalation.id)).where(
                Escalation.status != EscalationStatus.resolved,
                Escalation.severity.in_([
                    EscalationSeverity.high,
                    EscalationSeverity.critical,
                ]),
            )
        ).scalar()
        print(f"Applied. Remaining threads: {remaining}. "
              f"Unresolved high/critical escalations: {high_crit}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
