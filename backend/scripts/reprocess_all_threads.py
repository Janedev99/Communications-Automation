"""
Full reconciliation: re-apply the CURRENT categorization + draft logic to EVERY
polled thread (not just the recent window), so historical mail that was processed
under older code lines up with how the app behaves today.

This is the all-emails superset of ``backfill_recent_reprocess.py``. In addition
to re-categorizing and generating missing drafts, it RECONCILES drafts in both
directions:

  • If a thread now warrants a draft (T1/T2, non-promotional, not escalated) and
    has none → generate one for review (NEVER auto-sent).
  • If a thread now warrants NO draft (promotional / automated, or escalated /
    T3) but carries a stale AI draft → REMOVE that draft and reset status.

It also normalizes ``status`` so the inbox reflects reality:
  draft_ready when a draft exists, escalated for escalation/T3, otherwise
  categorized.

Outlook is NEVER touched — no delete / spam / move — and nothing is ever
auto-sent (we don't call maybe_auto_send).

SAFETY — which drafts can be removed:
  Only ``DraftStatus.pending`` drafts are deletable. They are pure AI output that
  no human has touched. Drafts in edited / approved / sent / rejected /
  send_failed encode staff decisions or completed sends — those are PRESERVED;
  such a thread is updated metadata-only (category/tier/summary) and its draft +
  status are left alone.

DEPLOY ORDERING (important):
  Run this only AFTER the current code (tightened promotional categorizer +
  draft_catchup promotional exclusion) is deployed to the same environment whose
  DB you are targeting. Otherwise the deployed login-sweep / polling loop will
  happily re-draft the promotional threads this script just cleaned, undoing the
  work and re-spending AI credits. Migration 016 (the ``promotional`` enum value)
  must also be applied before --execute, or the re-categorization write fails.

Dry-run by default: prints scope using only FREE signals (no writes, no LLM —
the promotional preview uses the sender heuristic). Pass --execute to apply.

Targets the configured DATABASE_URL — PRODUCTION in this project.

Usage:
    python scripts/reprocess_all_threads.py                 # dry run, ALL threads
    python scripts/reprocess_all_threads.py --days 30        # limit to a window
    python scripts/reprocess_all_threads.py --execute        # apply to ALL threads
    python scripts/reprocess_all_threads.py --days 30 --execute
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.services.categorizer import _automated_sender_result, get_categorizer
from app.services.email_intake import _should_generate_draft
from app.services.tier_engine import decide_tier

# Threads in a workable (non-terminal) state are eligible for re-processing.
# sent / closed / deleted / spam are terminal — we never reopen or re-draft them.
_ACTIVE = [
    EmailStatus.new,
    EmailStatus.categorized,
    EmailStatus.draft_ready,
    EmailStatus.pending_review,
    EmailStatus.escalated,
]

# Draft states that represent pure, untouched AI output — safe to remove when a
# thread no longer warrants a draft. Everything else (edited / approved / sent /
# rejected / send_failed) encodes a human decision or a completed send and is
# preserved.
_DELETABLE_DRAFT_STATES = {DraftStatus.pending}


def _candidate_threads(db, days: int | None) -> list[EmailThread]:
    """All active threads, optionally limited to those with a message in the
    last ``days`` days. ``days is None`` (the default) means EVERY active thread.
    """
    stmt = select(EmailThread).where(EmailThread.status.in_(_ACTIVE))
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent_ids = db.execute(
            select(EmailMessage.thread_id)
            .where(EmailMessage.received_at >= cutoff)
            .distinct()
        ).scalars().all()
        if not recent_ids:
            return []
        stmt = stmt.where(EmailThread.id.in_(recent_ids))
    return db.execute(stmt).scalars().all()


def _latest_inbound(thread: EmailThread) -> EmailMessage | None:
    inbound = [m for m in thread.messages if m.direction == MessageDirection.inbound]
    return max(inbound, key=lambda m: m.received_at) if inbound else None


def _drafts_for(db, thread_id) -> list[DraftResponse]:
    return list(
        db.execute(
            select(DraftResponse).where(DraftResponse.thread_id == thread_id)
        ).scalars().all()
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-process ALL polled threads with the current categorization + draft logic."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Optional look-back window in days. Omit to process ALL active threads.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default: dry run, read-only, no LLM).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    threads = _candidate_threads(db, args.days)
    window = f"last {args.days} days" if args.days is not None else "ALL time"
    print(f"Scope: {window} | active candidate threads: {len(threads)}")
    print(f"Mode: {'EXECUTE (writing to DB + LLM calls)' if args.execute else 'DRY RUN (read-only, no LLM)'}")
    print("-" * 72)

    if not args.execute:
        # FREE preview only — no LLM, no writes. We can predict promotional via
        # the sender heuristic and count existing drafts, but the true new
        # category for non-heuristic mail needs the LLM (only run on --execute).
        heur_promo = [t for t in threads if _automated_sender_result(t.client_email) is not None]
        cat_mix = Counter(t.category.value for t in threads)

        # Heuristic-promotional threads that still carry a deletable (pending)
        # draft — these are the clearest "draft will be removed" candidates.
        promo_with_pending = 0
        for t in heur_promo:
            drafts = _drafts_for(db, t.id)
            if any(d.status in _DELETABLE_DRAFT_STATES for d in drafts):
                promo_with_pending += 1

        print("Current category mix:", dict(cat_mix))
        print(f"Match free promotional heuristic (no LLM needed): {len(heur_promo)}")
        print(f"  ...of which carry a removable pending draft: {promo_with_pending}")
        for t in heur_promo[:8]:
            print(f"   - {t.client_email[:55]} (now: {t.category.value})")
        print("")
        print("On --execute each candidate is re-categorized (heuristic free; otherwise")
        print("1 LLM call). Threads that no longer warrant a draft have their pending")
        print("draft removed; eligible threads with no draft get 1 generated. Drafts")
        print("touched by staff (edited/approved/sent/rejected) are always preserved.")
        print("Outlook is never touched; nothing is auto-sent.")
        return

    # ── EXECUTE ───────────────────────────────────────────────────────────────
    settings = get_settings()
    categorizer = get_categorizer()
    from app.services.draft_generator import get_draft_generator
    generator = get_draft_generator()

    recategorized = 0
    drafted = 0
    drafts_removed = 0
    preserved_human = 0
    skipped_no_inbound = 0
    failed = 0

    for thread in threads:
        latest = _latest_inbound(thread)
        if latest is None:
            skipped_no_inbound += 1
            continue
        body = latest.body_text or latest.body_html or ""
        try:
            result = categorizer.categorize(
                sender=latest.sender, subject=thread.subject, body=body
            )
            tier_decision = decide_tier(db, result=result, source=result.source)

            # Always refresh categorization metadata.
            thread.category = result.category
            thread.category_confidence = result.confidence
            thread.ai_summary = result.summary
            thread.suggested_reply_tone = result.suggested_reply_tone
            thread.categorization_source = result.source
            thread.tier = tier_decision.tier
            thread.tier_set_at = datetime.now(timezone.utc)
            thread.tier_set_by = "reprocess"
            thread.updated_at = datetime.now(timezone.utc)
            db.flush()
            recategorized += 1

            # Canonical draft-decision rule — imported, never re-implemented, so
            # this script and the live intake pipeline can't drift.
            should = _should_generate_draft(
                escalated=result.escalation_needed,
                tier=tier_decision.tier,
                category=result.category,
                draft_auto_generate=settings.draft_auto_generate,
            )
            drafts = _drafts_for(db, thread.id)
            deletable = [d for d in drafts if d.status in _DELETABLE_DRAFT_STATES]
            human_touched = [d for d in drafts if d.status not in _DELETABLE_DRAFT_STATES]

            if human_touched:
                # Staff already engaged with this thread's draft (or it was
                # sent). Update category metadata only — never delete or
                # regenerate, and leave status untouched.
                preserved_human += 1
                db.commit()
                continue

            if not should:
                # No draft warranted. Remove any pending AI-only drafts.
                for d in deletable:
                    db.delete(d)
                    drafts_removed += 1
                thread.status = (
                    EmailStatus.escalated
                    if (result.escalation_needed or tier_decision.tier == ThreadTier.t3_escalate)
                    else EmailStatus.categorized
                )
            else:
                # Draft warranted.
                if not drafts:
                    generator.generate(db, thread)  # never auto-sent
                    drafted += 1
                # A draft now exists (just-generated or a pre-existing pending
                # one) — surface it for review without clobbering an active
                # pending_review state.
                if thread.status != EmailStatus.pending_review:
                    thread.status = EmailStatus.draft_ready

            db.commit()
        except Exception as exc:  # noqa: BLE001 — per-thread isolation
            db.rollback()
            failed += 1
            print(
                f"  FAILED {str(thread.id)[:8]} ({thread.client_email[:40]}): "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )

    print("-" * 72)
    print(f"Re-categorized:                       {recategorized}")
    print(f"Drafts generated for review:          {drafted}")
    print(f"Stale drafts removed (pending only):  {drafts_removed}")
    print(f"Preserved (human-touched draft):      {preserved_human}")
    print(f"Skipped (no inbound message):         {skipped_no_inbound}")
    print(f"Failed (isolated, see above):         {failed}")


if __name__ == "__main__":
    main()
