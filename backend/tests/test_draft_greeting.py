"""
Tests for the draft-generation greeting contract.

Client-reported bug (meeting 2026-05-27): the AI greeted a client as
"Dear TC" — initials carried over from the email address / display name —
instead of "Tyra", the name she signed her message with. Jane's requested
behaviour: prefer the sign-off name written in the email body; if none is
found, fall back to a plain greeting rather than guessing.

These assert the *prompt contract* at the template level (same approach as
test_draft_persona.py) — fast, no LLM call, no generate() dependency graph.
"""
from app.services.draft_generator import (
    _COMPOSE_SYSTEM_PROMPT,
    _SYSTEM_PROMPT_TEMPLATE,
)


def test_reply_prompt_has_greeting_rule():
    t = _SYSTEM_PROMPT_TEMPLATE
    assert "GREETING" in t
    # Primary source: the name the sender signed their own message with.
    assert "signed their own message with" in t
    # The reported bug is named explicitly so the rule is unambiguous to the model.
    assert 'do NOT \nwrite "Dear TC"' in t or 'do NOT write "Dear TC"' in t


def test_reply_prompt_forbids_address_derived_names():
    t = _SYSTEM_PROMPT_TEMPLATE
    assert "derived from the email address" in t
    assert "initials" in t


def test_reply_prompt_has_generic_fallback():
    # Jane's spec: "if they can't find anything, then they just say hello or hi".
    assert '"Hello,"' in _SYSTEM_PROMPT_TEMPLATE


def test_greeting_rule_renders_in_final_prompt():
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
    assert "GREETING" in rendered
    assert "derived from the email address" in rendered


def test_compose_prompt_forbids_address_derived_names():
    t = _COMPOSE_SYSTEM_PROMPT
    assert "Never derive a" in t
    assert "email address" in t
    assert '"Hello,"' in t
