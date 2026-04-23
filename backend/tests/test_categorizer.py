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

def test_claude_api_error_fallback_escalates(mock_anthropic):
    """
    When the Claude API raises an anthropic.APIError, the fallback result
    must be returned with escalation_needed=True (fail-safe).
    """
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

    assert result.escalation_needed is True, (
        "API error must trigger the fail-safe fallback with escalation_needed=True"
    )
    assert result.confidence == 0.0


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
