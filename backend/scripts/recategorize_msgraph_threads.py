"""
One-off re-categorization: re-run the categorizer against threads polled
during the M365 cutover window now that their body_text has been backfilled.

Context: When MSGraphProvider was first activated (2026-05-15), it stored
`body_text=None` on every polled email (HTML-only body extraction bug, fixed
in FIX/msgraph-empty-body-text). The categorizer's fallback then fed the
RAW HTML into the LLM client; that LLM call appears to have failed for every
thread (the local LLM_PROVIDER=openai_compat target was unreachable), so the
system ultimately fell back to the deterministic rules engine for ALL 33
cutover-window threads. Combined: the AI categorizer never actually ran on
real client email.

After running this script, every targeted thread will have:
  - a fresh categorization from Anthropic against the clean (backfilled)
    body_text
  - a re-derived tier
  - an audit log entry recording old -> new

What this script intentionally does NOT do:
  - Touch existing Escalation rows. If a thread shifts away from
    t3_escalate, its Escalation row is left in place for Jane to triage
    manually. (We can't safely auto-resolve escalations without knowing
    intent.) Shifts INTO t3 do NOT create new escalations either — same
    reason.
  - Trigger auto-send. SHADOW_MODE=true is the env gate; the
    auto_send_enabled DB flag is also off. Even if a thread becomes
    t1_auto, the polling-loop draft generation path is what triggers
    sends, and we don't invoke it here.
  - Regenerate drafts.

Anthropic is forced via env override so that local .env (which currently
points LLM_PROVIDER at a RunPod endpoint that may be down) does not silently
fall back to rules again — defeating the entire purpose of the rerun.

Usage:
  python scripts/recategorize_msgraph_threads.py            # dry-run (default)
  python scripts/recategorize_msgraph_threads.py --apply    # actually update
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force Anthropic BEFORE any app imports — settings is lru_cache'd.
os.environ["LLM_PROVIDER"] = "anthropic"

# Make `app.*` importable when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.email import (
    CategorizationSource,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.services.categorizer import get_categorizer
from app.services.tier_engine import decide_tier
from app.utils.audit import log_action

# The M365 cutover began on 2026-05-15. Anything earlier was IMAP / seed data
# and either has body_text populated already or is intentional fixture data.
CUTOVER_START = datetime(2026, 5, 15, tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the changes. Without this flag, runs as dry-run.",
    )
    args = parser.parse_args()

    # Sanity-check the env override took effect before we waste any API calls.
    settings = get_settings()
    if getattr(settings, "llm_provider", None) != "anthropic":
        print(
            f"ERROR: expected llm_provider='anthropic' after env override, "
            f"got {settings.llm_provider!r}. Aborting to avoid another "
            "rules_fallback run."
        )
        return 1

    db = SessionLocal()
    try:
        threads = db.execute(
            select(EmailThread).where(
                EmailThread.created_at >= CUTOVER_START,
                EmailThread.status.in_([EmailStatus.categorized, EmailStatus.escalated]),
            ).order_by(EmailThread.created_at.asc())
        ).scalars().all()

        if not threads:
            print("No threads to re-categorize.")
            return 0

        print(f"Threads in scope (created since {CUTOVER_START.date()}): {len(threads)}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}\n")

        categorizer = get_categorizer()
        tier_changes: dict[str, dict[str, int]] = {}
        cat_changes: dict[str, dict[str, int]] = {}
        changed_threads = 0
        unchanged_threads = 0

        for t in threads:
            latest = db.execute(
                select(EmailMessage).where(
                    EmailMessage.thread_id == t.id,
                    EmailMessage.direction == MessageDirection.inbound,
                ).order_by(EmailMessage.received_at.desc()).limit(1)
            ).scalar_one_or_none()

            if latest is None:
                print(f"  SKIP thread={t.id} — no inbound message")
                continue

            body = latest.body_text or latest.body_html or ""
            if not body:
                print(f"  SKIP thread={t.id} — no body content even after backfill")
                continue

            old_category = t.category.value if t.category else None
            old_tier = t.tier.value if t.tier else None
            old_source = t.categorization_source.value if t.categorization_source else None

            result = categorizer.categorize(
                sender=latest.sender or "",
                subject=t.subject or "(no subject)",
                body=body,
            )
            tier_decision = decide_tier(db, result=result, source=result.source)

            new_category = result.category.value
            new_tier = tier_decision.tier.value
            new_source = result.source.value

            cat_key = f"{old_category} -> {new_category}"
            tier_key = f"{old_tier} -> {new_tier}"
            cat_changes.setdefault(cat_key, {"count": 0})["count"] += 1
            tier_changes.setdefault(tier_key, {"count": 0})["count"] += 1

            changed = (
                old_category != new_category
                or old_tier != new_tier
                or old_source != new_source
            )

            if changed:
                changed_threads += 1
                print(
                    f"  CHANGE thread={t.id} subj={ascii(t.subject or '')[:60]}\n"
                    f"    category : {old_category} -> {new_category} "
                    f"(conf {result.confidence:.2f}, source {new_source})\n"
                    f"    tier     : {old_tier} -> {new_tier} ({tier_decision.reason})"
                )
            else:
                unchanged_threads += 1

            if args.apply:
                t.category = result.category
                t.category_confidence = result.confidence
                t.ai_summary = result.summary
                t.suggested_reply_tone = result.suggested_reply_tone
                t.categorization_source = result.source
                t.tier = tier_decision.tier
                t.tier_set_at = datetime.now(timezone.utc)
                t.tier_set_by = "recategorize_script"
                t.updated_at = datetime.now(timezone.utc)

                log_action(
                    db,
                    action="email.recategorized",
                    entity_type="email_thread",
                    entity_id=str(t.id),
                    details={
                        "reason": "FIX/msgraph-empty-body-text backfill rerun",
                        "old": {
                            "category": old_category,
                            "tier": old_tier,
                            "source": old_source,
                        },
                        "new": {
                            "category": new_category,
                            "tier": new_tier,
                            "source": new_source,
                            "confidence": result.confidence,
                        },
                    },
                )

        if args.apply:
            db.commit()

        print(f"\n=== Summary ===")
        print(f"Threads processed     : {len(threads)}")
        print(f"Threads changed       : {changed_threads}")
        print(f"Threads unchanged     : {unchanged_threads}")
        print(f"\nCategory transitions:")
        for k, v in sorted(cat_changes.items(), key=lambda kv: -kv[1]["count"]):
            print(f"  {v['count']:3d}  {k}")
        print(f"\nTier transitions:")
        for k, v in sorted(tier_changes.items(), key=lambda kv: -kv[1]["count"]):
            print(f"  {v['count']:3d}  {k}")

        if not args.apply:
            print("\nDRY RUN -- no changes written. Re-run with --apply to commit.")
        else:
            print("\nApplied. Audit-log entries written: email.recategorized")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
