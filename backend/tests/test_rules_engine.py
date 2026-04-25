"""
Tests for the keyword-based rules-engine fallback.

The rules engine is a pure function — no DB, no API calls. It exists to keep
the system functional when Claude is unavailable. Critical invariants:

  1. Confidence is always capped at 0.5 (so tier_engine never auto-sends).
  2. Escalation keywords ALWAYS force escalation_needed=True.
  3. The result.source is left at the default and the categorizer wraps it
     with `rules_fallback`.
  4. Unknown content escalates (fail safe).
"""
from __future__ import annotations

import pytest

from app.models.email import EmailCategory
from app.services.rules_engine import categorize_with_rules


CONF_CAP = 0.5  # mirrors _RULES_CONFIDENCE in rules_engine.py


# ── 1. Confidence cap is invariant ────────────────────────────────────────────

@pytest.mark.parametrize(
    "subject,body",
    [
        ("Quick question", "Just wondering about pricing for new clients"),
        ("Re: my return", "What is the status of my return?"),
        ("URGENT", "I need this today"),
        ("Random gibberish lkjasdf", "asdfasdf"),
    ],
)
def test_confidence_is_always_capped(subject, body):
    """Whatever the input, confidence must equal the documented cap."""
    result = categorize_with_rules(sender="x@y.com", subject=subject, body=body)
    assert result.confidence == CONF_CAP, (
        f"rules engine should cap confidence at {CONF_CAP}; got {result.confidence}"
    )


# ── 2. Escalation keywords ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "trigger",
    [
        "I just received an IRS audit notice",
        "An attorney has been retained",
        "This is a legal subpoena",
        "I am filing a lawsuit",
        "There may be fraud involved",
        "We received a tax lien notice",
        "Penalty notice from the state",
    ],
)
def test_escalation_keywords_always_escalate(trigger: str):
    """Any matching escalation keyword must force escalation_needed=True."""
    result = categorize_with_rules(sender="x@y.com", subject="Re: tax", body=trigger)
    assert result.escalation_needed is True, f"'{trigger}' must escalate"
    assert result.escalation_reasons, "escalation_reasons must not be empty"


def test_escalation_overrides_category_match():
    """When BOTH escalation and category keywords match, escalation wins."""
    result = categorize_with_rules(
        sender="x@y.com",
        subject="Status of audit",  # 'status' would match status_update
        body="What is the status of my IRS audit?",
    )
    assert result.escalation_needed is True
    # Category in escalation case is uncategorized (we don't try to refine)
    assert result.category == EmailCategory.uncategorized


# ── 3. Category keyword routing ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "subject,body,expected",
    [
        # Appointment patterns
        ("Reschedule meeting", "Can we reschedule our 3pm call?",
         EmailCategory.appointment),
        ("Booking", "I'd like to book a consultation next week",
         EmailCategory.appointment),
        # Document request patterns
        ("Need W-2", "Could you send me a copy of my W-2 from last year?",
         EmailCategory.document_request),
        ("Receipt", "Please confirm receipt of the documents I attached",
         EmailCategory.document_request),
        # Status update patterns
        ("Quick check", "Just got the docs—thanks!",
         EmailCategory.status_update),
        # Urgent patterns
        ("ASAP", "I need this today, deadline is tomorrow",
         EmailCategory.urgent),
        # Complaint patterns (non-escalation-keyword)
        ("Frustrated", "I am extremely frustrated and disappointed",
         EmailCategory.complaint),
        # Clarification patterns
        ("Question", "Can you explain what this notice means?",
         EmailCategory.clarification),
        # General inquiry
        ("Inquiry", "I am interested in your services and have a question",
         EmailCategory.general_inquiry),
    ],
)
def test_category_routing(subject: str, body: str, expected: EmailCategory):
    """Each category's keywords route to the expected EmailCategory."""
    result = categorize_with_rules(sender="x@y.com", subject=subject, body=body)
    assert result.category == expected, (
        f"Expected {expected.value} for '{subject}/{body}', got {result.category.value}"
    )


# ── 4. Fail-safe: nothing matches → escalate ──────────────────────────────────

def test_no_match_escalates():
    """Random content with no keyword matches must escalate (fail-safe)."""
    result = categorize_with_rules(
        sender="x@y.com",
        subject="zzz",
        body="lorem ipsum dolor sit amet",
    )
    assert result.escalation_needed is True
    assert result.category == EmailCategory.uncategorized


def test_empty_input_escalates():
    """Empty subject + empty body should escalate."""
    result = categorize_with_rules(sender="x@y.com", subject="", body="")
    assert result.escalation_needed is True


# ── 5. HTML body is stripped before matching ──────────────────────────────────

def test_html_body_is_handled():
    """If the body is HTML, the engine should still match keywords inside it."""
    result = categorize_with_rules(
        sender="x@y.com",
        subject="hi",
        body="<p>Could you <b>send</b> me the W-2 form please?</p>",
    )
    assert result.category == EmailCategory.document_request


# ── 6. Case-insensitive matching ──────────────────────────────────────────────

def test_case_insensitive_match():
    result = categorize_with_rules(
        sender="x@y.com", subject="MEETING", body="LET'S RESCHEDULE."
    )
    assert result.category == EmailCategory.appointment
