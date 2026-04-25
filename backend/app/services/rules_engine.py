"""
Rule-based categorization fallback.

Used when Claude is unavailable (no API key, budget exceeded, network error).
Produces the same `CategorizationResult` shape as the Claude categorizer so
callers can be source-agnostic. Confidence is intentionally capped well below
typical Claude confidence so tier_engine never auto-sends a rules_fallback
result.

Strategy:
  1. Run the deterministic escalation keyword check first. If it fires, we
     return uncategorized + escalation_needed=True (defer to staff).
  2. Match category keywords against subject + body. First match wins.
  3. If nothing matches, return uncategorized + escalation_needed=True (safe
     default — staff sees the email).
"""
from __future__ import annotations

import logging
import re

from app.models.email import EmailCategory
from app.schemas.email import CategorizationResult
from app.utils.sanitize import strip_html

logger = logging.getLogger(__name__)


# Confidence emitted by the rules engine. Capped at 0.5 so tier_engine
# never elevates a rules-fallback result to T1 (T1 thresholds are 0.92+).
_RULES_CONFIDENCE = 0.5


# Same keyword set as the categorizer's deterministic pre-check.
_ESCALATION_KEYWORDS: re.Pattern[str] = re.compile(
    r"\b(irs|audit|subpoena|penalty|attorney|lawsuit|complaint|dispute|"
    r"fraud|lien|levy)\b",
    re.IGNORECASE,
)


# Per-category keyword bundles. Order matters: earlier matches win.
# Tuples are (category, regex). All regexes are word-boundary anchored
# and case-insensitive.
_CATEGORY_PATTERNS: list[tuple[EmailCategory, re.Pattern[str]]] = [
    (
        EmailCategory.appointment,
        re.compile(
            r"\b(meeting|appointment|reschedul\w*|schedule|book|calendar|zoom|call)\b",
            re.IGNORECASE,
        ),
    ),
    (
        EmailCategory.document_request,
        re.compile(
            r"\b(w-?2|w-?9|1099|receipt|document|attach\w*|upload|tax form|"
            r"return copy|prior return|statement)\b",
            re.IGNORECASE,
        ),
    ),
    (
        EmailCategory.status_update,
        re.compile(
            r"\b(status|progress|update|where are we|how is.*going|when will|"
            r"received|got the|thanks)\b",
            re.IGNORECASE,
        ),
    ),
    (
        EmailCategory.urgent,
        re.compile(
            r"\b(urgent|asap|immediately|today|deadline|by tomorrow|emergency)\b",
            re.IGNORECASE,
        ),
    ),
    (
        EmailCategory.complaint,
        re.compile(
            r"\b(unhappy|frustrat\w*|angry|disappoint\w*|terrible|worst|"
            r"unacceptable)\b",
            re.IGNORECASE,
        ),
    ),
    (
        EmailCategory.clarification,
        re.compile(
            r"\b(clarif\w*|explain|what does.*mean|don't understand|help me understand|"
            r"can you tell me)\b",
            re.IGNORECASE,
        ),
    ),
    (
        EmailCategory.general_inquiry,
        re.compile(
            r"\b(question|inquir\w*|wondering|curious|interested in)\b",
            re.IGNORECASE,
        ),
    ),
]


def categorize_with_rules(
    *,
    sender: str,
    subject: str,
    body: str,
) -> CategorizationResult:
    """Categorize an email using keyword rules only — no API calls.

    Always returns a result; never raises. Confidence is capped at
    `_RULES_CONFIDENCE` (0.5) by design.
    """
    clean_body = strip_html(body or "")
    haystack = f"{subject or ''} {clean_body}"

    # 1. Deterministic escalation check
    if _ESCALATION_KEYWORDS.search(haystack):
        return CategorizationResult(
            category=EmailCategory.uncategorized,
            confidence=_RULES_CONFIDENCE,
            escalation_needed=True,
            escalation_reasons=["Keyword-triggered escalation (rules fallback)"],
            summary="Escalation-triggering keyword detected; AI was unavailable.",
            suggested_reply_tone="professional",
        )

    # 2. Category match (first wins)
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(haystack):
            logger.info(
                "rules_engine: matched category=%s for sender=%s",
                category.value, sender,
            )
            return CategorizationResult(
                category=category,
                confidence=_RULES_CONFIDENCE,
                escalation_needed=False,
                escalation_reasons=[],
                summary=f"Categorized as {category.value} via keyword fallback.",
                suggested_reply_tone="professional",
            )

    # 3. Nothing matched — defer to staff
    return CategorizationResult(
        category=EmailCategory.uncategorized,
        confidence=_RULES_CONFIDENCE,
        escalation_needed=True,
        escalation_reasons=["No keyword match; AI unavailable"],
        summary="Could not classify with keyword fallback.",
        suggested_reply_tone="professional",
    )
