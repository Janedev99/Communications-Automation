"""Tests for release_notes_ai service — structured JSON parsing variants + fallback."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from app.services.llm_client import LLMResult


def _llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, prompt_tokens=10, completion_tokens=20)


def _structured_payload(
    *,
    title: str = "T",
    summary: str = "What staff will notice this release.",
    highlights: list[dict] | None = None,
) -> str:
    if highlights is None:
        highlights = [{"category": "new", "text": "Adds a new thing"}]
    return json.dumps({"title": title, "summary": summary, "highlights": highlights})


def test_strict_json_parse_returns_structured_suggestion():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = _structured_payload(
        title="T",
        summary="Some summary",
        highlights=[
            {"category": "new", "text": "Adds X"},
            {"category": "fixed", "text": "Fixes Y"},
        ],
    )
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m_client = MagicMock()
        m_client.complete.return_value = _llm_result(payload)
        m_get.return_value = m_client
        out = generate_release_notes_suggestion(commits=["feat: thing"])
    assert out.title == "T"
    assert out.summary == "Some summary"
    assert out.highlights == [
        {"category": "new", "text": "Adds X"},
        {"category": "fixed", "text": "Fixes Y"},
    ]
    assert out.low_confidence is False


def test_fenced_json_parse():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "```json\n" + _structured_payload() + "\n```"
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.title == "T"
    assert len(out.highlights) == 1
    assert out.low_confidence is False


def test_fenced_without_lang_tag_parse():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "```\n" + _structured_payload() + "\n```"
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.title == "T"
    assert out.low_confidence is False


def test_substring_json_parse():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "Sure, here it is: " + _structured_payload() + " -- enjoy."
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.title == "T"
    assert len(out.highlights) >= 1
    assert out.low_confidence is False


def test_last_resort_fallback_sets_low_confidence():
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = "completely unstructured prose with no json at all"
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is True
    assert out.title.startswith("Updates on ")
    # Empty highlights signal "AI couldn't structure" — admin authors manually.
    assert out.highlights == []
    # Summary explains the situation rather than embedding raw output.
    assert "could not be parsed" in out.summary.lower() or "review" in out.summary.lower()


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


def test_partial_json_missing_highlights_falls_through_to_fallback():
    """If parse succeeds but the dict lacks 'highlights', fall through to fallback."""
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = json.dumps({"title": "Only title", "summary": "Only summary"})
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is True
    assert out.highlights == []


def test_invalid_category_in_highlights_is_dropped():
    """Highlights with categories outside the allowed set are dropped, valid ones kept."""
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = json.dumps({
        "title": "T",
        "summary": "S",
        "highlights": [
            {"category": "new", "text": "Valid one"},
            {"category": "WHATEVER", "text": "Invalid category"},
            {"category": "fixed", "text": "Another valid"},
        ],
    })
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is False
    assert len(out.highlights) == 2
    categories = {h["category"] for h in out.highlights}
    assert categories == {"new", "fixed"}


def test_oversized_highlight_text_is_truncated():
    """Highlights with text >140 chars are truncated to fit, not dropped."""
    from app.services.release_notes_ai import generate_release_notes_suggestion
    long_text = "X" * 200
    payload = json.dumps({
        "title": "T",
        "summary": "S",
        "highlights": [{"category": "improved", "text": long_text}],
    })
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is False
    assert len(out.highlights) == 1
    assert len(out.highlights[0]["text"]) <= 140


def test_summary_synthesized_when_missing_but_highlights_present():
    """If AI returns title + highlights but no summary, synthesize from title."""
    from app.services.release_notes_ai import generate_release_notes_suggestion
    payload = json.dumps({
        "title": "Some Release",
        "highlights": [{"category": "new", "text": "Adds X"}],
    })
    with patch("app.services.release_notes_ai.get_llm_client") as m_get:
        m = MagicMock(); m.complete.return_value = _llm_result(payload); m_get.return_value = m
        out = generate_release_notes_suggestion(commits=["feat: x"])
    assert out.low_confidence is False
    assert out.title == "Some Release"
    assert "Some Release" in out.summary
    assert len(out.highlights) == 1
