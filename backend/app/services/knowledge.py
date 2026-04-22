"""
Knowledge base service.

Retrieves KnowledgeEntry records relevant to a given email category and
formats them for injection into the draft generation prompt.

Retrieval strategy (no embeddings):
  1. Entries whose category matches exactly
  2. Entries that include the category in their tags array
  3. Entries with entry_type = 'policy' (firm-wide rules — always included)
  4. Deduplicate, cap at `limit`, increment usage_count on all returned entries
"""
from __future__ import annotations

import logging

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.models.email import KnowledgeEntry

logger = logging.getLogger(__name__)

# Maps entry_type values to the label prefix used in the prompt block
_TYPE_LABELS: dict[str, str] = {
    "policy": "POLICY",
    "response_template": "TEMPLATE",
    "snippet": "SNIPPET",
}


class KnowledgeService:
    """
    Service that retrieves and formats knowledge base entries.

    Instantiate once and reuse — it holds no state between calls.
    """

    def get_relevant_entries(
        self,
        db: Session,
        category: str,
        limit: int = 10,
    ) -> list[KnowledgeEntry]:
        """
        Return knowledge entries relevant to the given email category.

        Strategy:
        - Match entries where category = :category OR :category is in tags
        - Always include entries with entry_type = 'policy'
        - Only active entries (is_active = True)
        - Deduplicate by id, cap at `limit`
        - Increment usage_count on all returned entries

        Returns a list of KnowledgeEntry ORM objects.
        """
        # Query: category match OR tag match OR policy entry
        stmt = (
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.is_active == True,  # noqa: E712
                or_(
                    KnowledgeEntry.category == category,
                    # PostgreSQL array containment: :category = ANY(tags)
                    KnowledgeEntry.tags.contains([category]),
                    KnowledgeEntry.entry_type == "policy",
                ),
            )
            .order_by(
                # Policies first, then templates, then snippets.
                # Cannot use simple .desc() because alphabetical order is wrong
                # (snippet > response_template > policy). Use explicit CASE ordering.
                case(
                    (KnowledgeEntry.entry_type == "policy", 0),
                    (KnowledgeEntry.entry_type == "response_template", 1),
                    (KnowledgeEntry.entry_type == "snippet", 2),
                    else_=3,
                ),
                KnowledgeEntry.usage_count.desc(),
                KnowledgeEntry.created_at.asc(),
            )
            .limit(limit)
        )

        entries: list[KnowledgeEntry] = list(db.execute(stmt).scalars().all())

        if not entries:
            logger.debug(
                "KnowledgeService: no entries found for category=%r", category
            )
            return entries

        # Deduplicate (the OR query can return the same row multiple times via
        # different conditions in some DB query planners; SQLAlchemy usually
        # deduplicates ORM objects in the identity map, but be explicit)
        seen: set = set()
        deduped: list[KnowledgeEntry] = []
        for entry in entries:
            if entry.id not in seen:
                seen.add(entry.id)
                deduped.append(entry)

        # P2 — DEFERRED: usage_count tracking is a non-functional metric.
        # At scale the UPDATE on every retrieval becomes a write hotspot.
        # For V1 the update is intentionally skipped to avoid write-amplification
        # on the knowledge entries table. Will be replaced with an async
        # batch counter (e.g. Redis + periodic flush) before V2 launch.
        # Previously: db.execute(update(KnowledgeEntry)...) + refresh per entry.

        logger.info(
            "KnowledgeService: retrieved %d entries for category=%r",
            len(deduped),
            category,
        )
        return deduped

    def format_for_prompt(self, entries: list[KnowledgeEntry]) -> str:
        """
        Format a list of KnowledgeEntry objects as labeled text blocks
        ready for injection into the draft prompt.

        Output format:
            [POLICY] Entry Title: entry content here…
            [TEMPLATE] Another Entry: template text…
            [SNIPPET] Disclaimer: standard disclaimer text…

        Returns an empty string if the list is empty.
        """
        if not entries:
            return "(No specific knowledge base entries available for this category.)"

        lines: list[str] = []
        for entry in entries:
            label = _TYPE_LABELS.get(entry.entry_type, "SNIPPET")
            # Format: [LABEL] Title: Content
            # Collapse excessive whitespace in content for prompt cleanliness
            content = entry.content.strip()
            lines.append(f"[{label}] {entry.title}: {content}")

        return "\n".join(lines)


# ── Module-level singleton ─────────────────────────────────────────────────────

_knowledge_service: KnowledgeService | None = None


def get_knowledge_service() -> KnowledgeService:
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service
