"""
One-time backfill: re-apply the CURRENT categorization + draft logic to recent
threads (default: last 7 days), as if the app had just polled them with the new
code.

Does NOT touch Outlook — no delete / spam / move — and never auto-sends.

Per active thread in the window:
  1. Re-categorize via the current categorizer (the promotional sender heuristic
     is free; otherwise the LLM, which now has the `promotional` category).
     Updates category / confidence / summary / tone and re-decides tier.
  2. If the re-categorized thread is T1-eligible, not escalated, not promotional,
     and has no draft yet → generate a draft for review (shadow-safe; the draft
     is NEVER auto-sent — we don't call maybe_auto_send).

Dry-run by default: prints scope using only free signals (no writes, no LLM
calls — the promotional preview uses the heuristic). Pass --execute to apply.

Targets the configured DATABASE_URL — PRODUCTION in this project. Requires
migration 016 (the `promotional` enum value) applied before --execute, or the
re-categorization write will fail.

Usage:
    python scripts/backfill_recent_reprocess.py            # dry run
    python scripts/backfill_recent_reprocess.py --days 7   # window
    python scripts/backfill_recent_reprocess.py --execute  # apply
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select

from app.database import SessionLocal
from app.models.email import (
    DraftResponse,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.services.categorizer import _automated_sender_result, get_categorizer
from app.services.tier_engine import decide_tier

# Threads in a workable (non-terminal) state are eligible for re-processing.
_ACTIVE = [
    EmailStatus.new,
    EmailStatus.categorized,
    EmailStatus.draft_ready,
    EmailStatus.pending_review,
    EmailStatus.escalated,
]


def _candidate_threads(db, days: int) -> list[EmailThread]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent_ids = db.execute(
        select(EmailMessage.thread_id)
        .where(EmailMessage.received_at >= cutoff)
        .distinct()
    ).scalars().all()
    if not recent_ids:
        return []
    return db.execute(
        select(EmailThread).where(
            EmailThread.id.in_(recent_ids),
            EmailThread.status.in_(_ACTIVE),
        )
    ).scalars().all()


def _latest_inbound(thread: EmailThread) -> EmailMessage | None:
    inbound = [m for m in thread.messages if m.direction == MessageDirection.inbound]
    return max(inbound, key=lambda m: m.received_at) if inbound else None


def _has_draft(db, thread_id) -> bool:
    return bool(
        db.execute(select(exists().where(DraftResponse.thread_id == thread_id))).scalar()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-process recent threads with current logic.")
    parser.add_argument("--days", type=int, default=7, help="Look-back window in days (default 7)")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()

    db = SessionLocal()
    threads = _candidate_threads(db, args.days)
    print(f"Window: last {args.days} days · active candidate threads: {len(threads)}")
    print(f"Mode: {'EXECUTE (writing to DB + LLM calls)' if args.execute else 'DRY RUN (read-only, no LLM)'}")
    print("-" * 72)

    if not args.execute:
        # Free preview: heuristic-promotional + T1-without-draft + category mix.
        heur_promo = [t for t in threads if _automated_sender_result(t.client_email) is not None]
        cat_mix = Counter(t.category.value for t in threads)
        t1_no_draft = [
            t for t in threads
            if t.tier == ThreadTier.t1_auto
            and t.status in (EmailStatus.new, EmailStatus.categorized, EmailStatus.draft_ready)
            and not _has_draft(db, t.id)
        ]
        print("Current category mix:", dict(cat_mix))
        print(f"Match free promotional heuristic (no LLM needed): {len(heur_promo)}")
        for t in heur_promo[:8]:
            print(f"   - {t.client_email[:55]} (now: {t.category.value})")
        print(f"T1 'auto-handled' threads with NO draft: {len(t1_no_draft)}")
        print("")
        print("On --execute: each candidate is re-categorized via the categorizer")
        print("(heuristic free; otherwise 1 LLM call), and each T1-without-draft that")
        print("stays non-promotional gets 1 draft LLM call. Outlook is never touched.")
        return

    # ── EXECUTE ───────────────────────────────────────────────────────────────
    categorizer = get_categorizer()
    from app.services.draft_generator import get_draft_generator
    generator = get_draft_generator()

    recategorized = 0
    drafted = 0
    skipped_promo = 0
    failed = 0

    for thread in threads:
        latest = _latest_inbound(thread)
        if latest is None:
            continue
        body = latest.body_text or latest.body_html or ""
        try:
            result = categorizer.categorize(
                sender=latest.sender, subject=thread.subject, body=body
            )
            tier_decision = decide_tier(db, result=result, source=result.source)

            thread.category = result.category
            thread.category_confidence = result.confidence
            thread.ai_summary = result.summary
            thread.suggested_reply_tone = result.suggested_reply_tone
            thread.categorization_source = result.source
            thread.tier = tier_decision.tier
            thread.tier_set_at = datetime.now(timezone.utc)
            thread.tier_set_by = "backfill"
            thread.updated_at = datetime.now(timezone.utc)
            db.flush()
            recategorized += 1

            if result.category == EmailCategory.promotional:
                skipped_promo += 1
            elif (
                tier_decision.tier == ThreadTier.t1_auto
                and not result.escalation_needed
                and thread.status in (EmailStatus.new, EmailStatus.categorized, EmailStatus.draft_ready)
                and not _has_draft(db, thread.id)
            ):
                # Generate a review draft. Never auto-sent (no maybe_auto_send).
                generator.generate(db, thread)
                drafted += 1

            db.commit()
        except Exception as exc:  # noqa: BLE001 — per-thread isolation
            db.rollback()
            failed += 1
            print(f"  FAILED {str(thread.id)[:8]} ({thread.client_email[:40]}): {type(exc).__name__}: {str(exc)[:120]}")

    print("-" * 72)
    print(f"Re-categorized: {recategorized}")
    print(f"Tagged promotional (no draft): {skipped_promo}")
    print(f"Drafts generated for review: {drafted}")
    print(f"Failed (isolated, see above): {failed}")


if __name__ == "__main__":
    main()
