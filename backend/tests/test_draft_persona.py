"""
Tests for the draft-generation persona + branding contract.

These assert the *prompt contract* — drafts are written as Jane Schilmoeller
personally (not "the firm"), and the content-driven brand sign-off rule is
present with a "pure Jane" default. Kept at the template level so they're
fast and free of the full generate() dependency graph; the runtime wiring
that injects firm_owner_name into the template comes from config defaults
exercised elsewhere.
"""
from app.services.draft_generator import (
    _SYSTEM_PROMPT_TEMPLATE,
    _USER_PROMPT_TEMPLATE,
)


def test_system_prompt_drafts_as_the_owner_not_the_firm():
    # The old framing ("on behalf of the firm") manufactured a firm-vs-firm
    # confusion that split Jane into two people. It must be gone.
    assert "on behalf of the firm" not in _SYSTEM_PROMPT_TEMPLATE
    # Persona is the owner, writing in first person.
    assert "personal email assistant for {firm_owner_name}" in _SYSTEM_PROMPT_TEMPLATE
    assert "in her own voice" in _SYSTEM_PROMPT_TEMPLATE


def test_system_prompt_has_content_driven_branding_rule():
    t = _SYSTEM_PROMPT_TEMPLATE
    # Both brands are named with their domains so the model can match content.
    assert "Point Profit" in t and "pointprofit.com" in t
    assert "Schilmoeller & Schoenfield" in t and "schilcpa.com" in t
    # Never split Jane across firms / redirect a sender elsewhere.
    assert "reached the wrong place" in t


def test_rendered_system_prompt_uses_real_owner_name_not_the_bug():
    rendered = _SYSTEM_PROMPT_TEMPLATE.format(
        firm_name="Schiller CPA",
        firm_owner_name="Jane Schilmoeller",
        firm_owner_email="jane@schilcpa.com",
        suggested_reply_tone="professional",
        knowledge_context="(none)",
        feedback_examples="",
        feedback_negatives="",
        closing_rule="(closing rule injected at runtime)",
    )
    assert "Jane Schilmoeller" in rendered
    # "Jane Schiller" was the firm-derived hallucination we fixed.
    assert "Jane Schiller" not in rendered


def test_user_prompt_uses_injected_signoff_instruction():
    # The sign-off is now an injected instruction (signature override or the
    # branding rule), not a hard-coded firm-team line.
    assert "{firm_name} team" not in _USER_PROMPT_TEMPLATE
    assert "{brand_hint}" in _USER_PROMPT_TEMPLATE
    assert "{signoff_instruction}" in _USER_PROMPT_TEMPLATE
    # Renders cleanly with an empty hint (the common case — single mailbox).
    rendered = _USER_PROMPT_TEMPLATE.format(
        subject="Q3 question",
        client_name="Sara",
        client_email="sara@example.com",
        brand_hint="",
        category="general_inquiry",
        ai_summary="A general question.",
        formatted_messages="[CLIENT — ...]",
        signoff_instruction="End with this signature: Jane",
    )
    assert "End with this signature: Jane" in rendered
    assert "Client: Sara" not in rendered  # old label replaced by "From:"
    assert "From: Sara" in rendered
