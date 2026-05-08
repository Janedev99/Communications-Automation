"""Tests for release_notes_ai service — JSON parsing variants + fallback."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from app.services.llm_client import LLMResult


def _llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, prompt_tokens=10, completion_tokens=20)


def test_strict_json_parse_returns_structured_suggestion():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = json.dumps({"title": "T", "body": "## Body\nhi"})
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m_client = MagicMock()
        m_client.complete.return_value = _llm_result(payload)
        m_get.return_value = m_client
        out = generate_release_notes_suggestion(commits=["feat: thing"])
    assert out.title == "T"
    assert out.body.startswith("## Body")
    assert out.low_confidence is False


def test_fenced_json_parse():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "```json\n" + json.dumps({"title": "T", "body": "B"}) + "\n```"
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.title == "T"
    assert out.body == "B"
    assert out.low_confidence is False


def test_fenced_without_lang_tag_parse():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "```\n" + json.dumps({"title": "T", "body": "B"}) + "\n```"
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.title == "T"
    assert out.low_confidence is False


def test_substring_json_parse():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = 'Sure, here it is: {"title": "T", "body": "B"} -- enjoy.'
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.title == "T"
    assert out.low_confidence is False


def test_last_resort_fallback_sets_low_confidence():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "completely unstructured prose with no json at all"
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is True
    assert "unstructured prose" in out.body
    assert out.title.startswith("Updates on ")


def test_empty_commit_list_raises_value_error():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    with pytest.raises(ValueError):
        generate_release_notes_suggestion(commits=[])


def test_is_release_notes_ai_available_reflects_llm_configured():
    from app.services.release_notes_ai import is_release_notes_ai_available
    with patch("app.services.release_notes_ai.is_llm_configured") as m:
        m.return_value = True
        assert is_release_notes_ai_available() is True
        m.return_value = False
        assert is_release_notes_ai_available() is False


def test_llm_error_propagates():
    """LLMError from the underlying client surfaces unchanged so the route can 502."""
    from app.services.release_notes_ai import generate_release_notes_suggestion
    from app.services.llm_client import LLMError
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock()
        m.complete.side_effect = LLMError("upstream timeout")
        m_get.return_value = m
        with pytest.raises(LLMError):
            generate_release_notes_suggestion(commits=["feat: x"])


def test_partial_json_missing_body_falls_through_to_fallback():
    """If parse succeeds but the dict lacks 'body', fall through to fallback."""
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = json.dumps({"title": "Only title"})
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is True
