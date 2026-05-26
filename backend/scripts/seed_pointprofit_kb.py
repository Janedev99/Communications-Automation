"""Seed the knowledge_entries table with Point Profit firm canon.

Run manually:
    PYTHONPATH=. venv/Scripts/python.exe scripts/seed_pointprofit_kb.py

Idempotency: each entry's `title` is the natural key. Re-running the
seeder UPSERTs - existing rows are updated with the latest content/tags,
missing rows are inserted. Human-authored entries (anything not in the
SEED_ENTRIES list) are never touched. Safe to run any number of times.

Content philosophy: these entries get injected into the draft-generator
prompt as labeled blocks the AI reads when composing a reply. Content
is written as FACTS the AI can use, not as marketing copy - the goal is
to inform the AI's tone and statements, not to push brand messaging
into client emails.

Policies (entry_type='policy') are universal - the draft generator
returns them for every email category. Use for firm-wide truth.

Templates (entry_type='response_template') and snippets
(entry_type='snippet') are scoped by category match or tag match. Tag
with the relevant EmailCategory values (status_update, document_request,
appointment, clarification, general_inquiry, complaint, urgent) so the
OR-on-tags clause in KnowledgeService.get_relevant_entries picks them
up for the right threads.
"""
from __future__ import annotations

import logging
import sys
from typing import TypedDict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email import KnowledgeEntry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("seed_pp_kb")


class SeedEntry(TypedDict):
    title: str
    content: str
    category: str
    tags: list[str]
    entry_type: str  # 'policy' | 'response_template' | 'snippet'


# All EmailCategory values - used to tag generic templates/snippets
# so they surface for any inbound category.
ALL_EMAIL_CATEGORIES = [
    "status_update",
    "document_request",
    "appointment",
    "clarification",
    "general_inquiry",
    "complaint",
    "urgent",
]


SEED_ENTRIES: list[SeedEntry] = [
    # ─── POLICIES ── universal context for every draft ──────────────────────
    {
        "title": "Point Profit — Firm Overview",
        "content": (
            "Point Profit LLC is a CPA and business-advisory firm founded by "
            "Jane Schilmoeller. We work with business owners on tax planning "
            "and compliance, financial strategy, operational improvements, and "
            "AI-enhanced advisory. Our clients range from owners starting a "
            "business, to those scaling, to those preparing for an exit. "
            "Our public site is https://www.pointprofit.com."
        ),
        "category": "firm_info",
        "tags": ["about", "firm", "overview", "pp-seed-v1"],
        "entry_type": "policy",
    },
    {
        "title": "Point Profit — Services Offered",
        "content": (
            "Point Profit offers: (1) comprehensive tax planning and "
            "compliance for individuals, partnerships, and corporations; "
            "(2) financial strategy and advisory services; (3) operational "
            "and AI-enhanced solutions for small and growing businesses; "
            "(4) goal-setting and actionable planning engagements that "
            "align financial outcomes with the owner's personal and "
            "professional aspirations. Specific pricing and engagement "
            "structures are discussed during a discovery call."
        ),
        "category": "services",
        "tags": ["services", "tax", "advisory", "bookkeeping", "planning", "pp-seed-v1"],
        "entry_type": "policy",
    },
    {
        "title": "Point Profit — Three-Phase Engagement Approach",
        "content": (
            "We work with clients in three phases: (1) Clarity - we define "
            "current state, goals, and constraints; (2) Action - we execute "
            "tactical plans (tax filings, strategy implementation, operational "
            "fixes); (3) Growth - we set up sustainable systems and revisit "
            "the plan as the business evolves. The approach applies whether "
            "the client is starting, scaling, or exiting their business. When "
            "responding to a client asking 'how do we work together,' frame "
            "the answer in terms of these three phases."
        ),
        "category": "process",
        "tags": ["approach", "process", "methodology", "engagement", "pp-seed-v1"],
        "entry_type": "policy",
    },
    {
        "title": "Point Profit — Founder Background (Jane Schilmoeller, CPA)",
        "content": (
            "Jane Schilmoeller is the founder of Point Profit. She is a "
            "licensed CPA who began her career at PricewaterhouseCoopers, "
            "where she managed complex tax planning for corporations, "
            "partnerships, and individuals. She spent nearly 16 years in "
            "corporate leadership before leaving to acquire and scale her "
            "own business, and now combines Big-4 technical experience with "
            "entrepreneurial perspective for Point Profit clients. When a "
            "client asks about credentials or wants to confirm Jane's "
            "background, this is the canonical reference."
        ),
        "category": "firm_info",
        "tags": ["founder", "jane", "credentials", "cpa", "pp-seed-v1"],
        "entry_type": "policy",
    },
    # ─── RESPONSE TEMPLATES ── category- or scenario-targeted ───────────────
    {
        "title": "Point Profit — Standard Email Signature",
        "content": (
            "Use this signature block to close client emails:\n\n"
            "Best regards,\n"
            "The Point Profit Team\n"
            "https://www.pointprofit.com\n\n"
            "If the sender of the response is explicitly Jane, use:\n\n"
            "Best,\n"
            "Jane Schilmoeller, CPA\n"
            "Point Profit LLC\n"
            "https://www.pointprofit.com\n\n"
            "Do not include a phone number or office address - these are not "
            "published publicly. Direct clients who want to book a call to "
            "the 'Book a call' link on https://www.pointprofit.com/contact."
        ),
        "category": "signature",
        "tags": ["signature", "signoff", "closing", "pp-seed-v1"] + ALL_EMAIL_CATEGORIES,
        "entry_type": "response_template",
    },
    {
        "title": "Point Profit — Booking a Call Reply Template",
        "content": (
            "When a client asks to schedule a call, meeting, or "
            "consultation, direct them to the public booking flow:\n\n"
            "'I'd be glad to set up a call. You can book a time that works "
            "for you at https://www.pointprofit.com/contact - choose the "
            "'Book a call' option and pick any open slot. If none of the "
            "available times work, reply here with two or three windows "
            "that suit you and we'll find a fit.'\n\n"
            "Avoid promising specific dates or times in the reply itself - "
            "the booking flow is the source of truth for availability."
        ),
        "category": "appointment",
        "tags": ["appointment", "booking", "meeting", "call", "scheduling", "pp-seed-v1"],
        "entry_type": "response_template",
    },
    # ─── SNIPPETS ── short reusable bits ────────────────────────────────────
    {
        "title": "Point Profit — Brand Tagline",
        "content": (
            "Point Profit's public tagline is 'Clear Goals. Bold Actions. "
            "Real Growth.' Use sparingly - this is a marketing line, not a "
            "phrase to drop into routine client correspondence. Appropriate "
            "contexts: welcome emails for brand-new clients, year-end recap "
            "emails, anniversary or milestone messages. Do not use in "
            "routine status updates, document requests, or appointment "
            "confirmations."
        ),
        "category": "branding",
        "tags": ["tagline", "brand", "marketing", "pp-seed-v1"],
        "entry_type": "snippet",
    },
]


def upsert_entry(db: Session, seed: SeedEntry) -> str:
    """Insert or update one KB entry. Returns 'inserted', 'updated', or
    'unchanged' for logging."""
    existing = db.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.title == seed["title"])
    ).scalar_one_or_none()

    if existing is None:
        entry = KnowledgeEntry(
            title=seed["title"],
            content=seed["content"],
            category=seed["category"],
            tags=seed["tags"],
            entry_type=seed["entry_type"],
            is_active=True,
        )
        db.add(entry)
        return "inserted"

    # Compare normalized fields to detect actual change
    same = (
        existing.content == seed["content"]
        and existing.category == seed["category"]
        and list(existing.tags or []) == seed["tags"]
        and existing.entry_type == seed["entry_type"]
        and existing.is_active is True
    )
    if same:
        return "unchanged"

    existing.content = seed["content"]
    existing.category = seed["category"]
    existing.tags = seed["tags"]
    existing.entry_type = seed["entry_type"]
    existing.is_active = True
    return "updated"


def run_seeder(db: Session, entries: list[SeedEntry] = SEED_ENTRIES) -> dict[str, int]:
    """Apply all `entries` to the database via UPSERT.

    Returns a dict of {'inserted', 'updated', 'unchanged'} counters.
    Commits on success; rolls back and re-raises on any failure.

    Extracted from main() so tests can drive the seeder with a fixture
    session against the in-memory test DB.
    """
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    try:
        for seed in entries:
            outcome = upsert_entry(db, seed)
            counts[outcome] += 1
            log.info("%s: %s", outcome.upper(), seed["title"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)

    try:
        with Session(engine) as db:
            counts = run_seeder(db)
    except Exception as e:  # noqa: BLE001
        log.error("Seeder failed: %s", e)
        return 2

    log.info(
        "Done. inserted=%d  updated=%d  unchanged=%d  total=%d",
        counts["inserted"],
        counts["updated"],
        counts["unchanged"],
        len(SEED_ENTRIES),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
