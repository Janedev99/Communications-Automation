"""
Tests for the email categorizer service.

Covers:
  - Keyword pre-check forces escalation even when Claude says no
  - Claude API error → fallback escalates
  - Non-JSON response from Claude → fallback escalates
  - Valid JSON but wrong schema → fallback escalates
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest


# ===========================================================================
# 1. Keyword pre-check forces escalation
# ===========================================================================

def test_keyword_precheck_forces_escalation(mock_anthropic):
    """
    Email containing 'IRS audit notice' must return escalation_needed=True
    even when Claude's response says escalation_needed=False.
    """
    # Configure mock to return non-escalating JSON
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=(
            '{"category": "status_update", "confidence": 0.85, '
            '"escalation_needed": false, "escalation_reasons": [], '
            '"summary": "Client wants status update.", '
            '"suggested_reply_tone": "professional"}'
        ))],
        usage=MagicMock(input_tokens=100, output_tokens=40),
    )

    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="client@example.com",
        subject="IRS audit notice regarding my 2023 return",
        body="Please tell me the status of my IRS audit.",
    )

    assert result.escalation_needed is True, (
        "Keyword 'IRS audit' must force escalation regardless of Claude's answer"
    )
    assert any("keyword" in r.lower() or "deterministic" in r.lower()
               for r in result.escalation_reasons), (
        "Escalation reason should mention keyword/deterministic check"
    )


# ===========================================================================
# 2. Claude API error → fallback escalates
# ===========================================================================

def test_claude_api_error_falls_back_to_rules_engine(mock_anthropic):
    """
    Phase 3: Claude API error gracefully degrades to the keyword rules engine
    instead of always escalating. The result is tagged with source=rules_fallback,
    and confidence is the rules-engine cap (0.5) so tier_engine never auto-sends.
    """
    from app.models.email import CategorizationSource

    mock_anthropic.messages.create.side_effect = anthropic.APIConnectionError(
        request=MagicMock()
    )

    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="client@example.com",
        subject="My tax return",
        body="What is the status of my return?",
    )

    # Source is now rules_fallback (the categorizer wraps the rules-engine
    # result with the fallback attribution).
    assert result.source == CategorizationSource.rules_fallback
    # The rules engine caps confidence at 0.5 — this is what prevents T1.
    assert result.confidence == 0.5


def test_claude_api_error_with_unclassifiable_body_still_escalates(mock_anthropic):
    """
    Safety floor: when Claude is down AND the rules engine can't classify the
    body either, the result must still escalate so a human sees it.
    """
    mock_anthropic.messages.create.side_effect = anthropic.APIConnectionError(
        request=MagicMock()
    )

    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="client@example.com",
        subject="zzz",
        body="lorem ipsum dolor sit amet — no keywords match here",
    )

    assert result.escalation_needed is True, (
        "Rules engine must escalate when it cannot classify (safety floor)."
    )


# ===========================================================================
# 3. Non-JSON response from Claude → fallback escalates
# ===========================================================================

def test_json_parse_failure_fallback_escalates(mock_anthropic):
    """
    When Claude returns garbled non-JSON text, _parse_response triggers the
    fallback and the result must escalate.
    """
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Sorry, I cannot classify this email right now.")],
        usage=MagicMock(input_tokens=50, output_tokens=20),
    )

    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="client@example.com",
        subject="Question about invoice",
        body="Why is my invoice different?",
    )

    assert result.escalation_needed is True, (
        "Non-JSON Claude response should trigger fallback escalation"
    )
    assert result.confidence == 0.0


# ===========================================================================
# 4. Pydantic validation failure → fallback escalates
# ===========================================================================

# ===========================================================================
# 5. Markdown-fenced JSON from Claude must parse cleanly
# ===========================================================================
# Claude wraps JSON output in ```json ... ``` fences. Before _strip_json_fences,
# json.loads choked on the leading "```json\n", silently demoting every
# Claude categorization to rules_fallback. These tests pin that down.


def test_strip_json_fences_with_language_tag():
    """```json\\n{...}\\n``` should yield bare JSON."""
    from app.services.categorizer import _strip_json_fences
    raw = '```json\n{"category": "status_update", "confidence": 0.9}\n```'
    assert _strip_json_fences(raw) == '{"category": "status_update", "confidence": 0.9}'


def test_strip_json_fences_without_language_tag():
    """Bare ``` ... ``` (no 'json' tag) should also strip."""
    from app.services.categorizer import _strip_json_fences
    raw = '```\n{"a": 1}\n```'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_preserves_unfenced():
    """Plain JSON (no fences) should pass through unchanged after strip()."""
    from app.services.categorizer import _strip_json_fences
    raw = '{"a": 1}'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_handles_trailing_whitespace():
    """Trailing newlines/spaces between content and closing fence should not break parsing."""
    from app.services.categorizer import _strip_json_fences
    raw = '```json\n{"a": 1}\n\n  \n```'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_categorizer_parses_claude_fenced_response(mock_anthropic):
    """
    End-to-end: when Claude returns its typical ```json ... ``` wrapper,
    the categorizer must extract a valid CategorizationResult — not silently
    fall back to rules_fallback (which was the prior production behavior).
    """
    from app.models.email import CategorizationSource

    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=(
            '```json\n'
            '{"category": "document_request", "confidence": 0.92, '
            '"escalation_needed": false, "escalation_reasons": [], '
            '"summary": "Client requesting K-1 documents for tax filing.", '
            '"suggested_reply_tone": "professional"}\n'
            '```'
        ))],
        usage=MagicMock(input_tokens=120, output_tokens=60),
    )

    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="client@example.com",
        subject="Need last year's K-1",
        body="Can you send the K-1 from 2024 for my tax filing?",
    )

    # Source must be claude — proves we did NOT fall back to rules_fallback
    assert result.source == CategorizationSource.claude, (
        "Fenced JSON should parse and attribute to claude, not rules_fallback"
    )
    assert result.confidence == 0.92
    assert "K-1" in result.summary


def test_pydantic_validation_failure_escalates(mock_anthropic):
    """
    Claude returns valid JSON but with the wrong shape (missing required fields
    or wrong types) — Pydantic validation fails and the fallback escalates.
    """
    # Valid JSON but missing 'confidence' key entirely — will fail _CategorizerResponse validation
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=(
            '{"type": "some_unknown_type", "needs_review": true}'
        ))],
        usage=MagicMock(input_tokens=50, output_tokens=20),
    )

    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="client@example.com",
        subject="Billing question",
        body="Can you clarify my invoice?",
    )

    # The missing 'category' and 'escalation_needed' fields force fallback
    # Note: _CategorizerResponse has defaults for most fields; 'category' and
    # 'escalation_needed' are required. If Claude returns them as wrong types,
    # validation fails.
    # Since 'confidence' has a default in Pydantic if not provided it won't fail,
    # but 'category' and 'escalation_needed' are required with no default.
    # → fallback result always has escalation_needed=True
    assert result.escalation_needed is True
    assert result.confidence == 0.0
