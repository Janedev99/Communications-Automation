"""LLM-backed release-notes generation (structured output).

Routes through the existing provider-agnostic LLMClient Protocol so it works
with whichever provider is configured (Anthropic in dev, RunPod-hosted Gemma
in prod, or any future swap-in). The release-notes service must NOT import
anthropic or openai directly — that would break the abstraction.

The model emits a structured JSON object — title, summary, highlights[] —
which drives chip rendering (NEW/IMPROVED/FIXED) in the modal and archive.

Defensive parsing handles cases where the model wraps output in fenced
blocks, prepends conversational filler, or returns partial / malformed
highlights. Anything unrecoverable falls through to a deterministic
last-resort fallback that sets low_confidence=True so the admin UI
can warn and let the human author the highlights manually.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.llm_client import LLMError, get_llm_client, is_llm_configured

logger = logging.getLogger(__name__)


_VALID_CATEGORIES = {"new", "improved", "fixed"}


_SYSTEM_PROMPT = (
    "You are a release-notes writer for non-technical staff at an "
    "accounting firm. Input is a list of commit messages from the last "
    "release. Each commit starts with a category prefix: feat: a new "
    "capability staff can use, fix: a bug that was corrected.\n\n"
    "Produce a single JSON object with EXACTLY these three keys, in this "
    "order, with no surrounding prose:\n"
    "  - title: 5 to 8 words, no jargon, present tense.\n"
    "  - summary: 1 to 2 sentences in plain language describing what "
    "staff will notice this release. 30 to 80 words.\n"
    "  - highlights: an array of 1 to 8 objects. Each object has exactly "
    "two keys: category (one of \"new\", \"improved\", \"fixed\") and "
    "text (a single sentence under 140 characters describing one "
    "change in user-visible terms).\n\n"
    "Category rules — apply your judgment:\n"
    "  - new: introduces a capability staff did not have before.\n"
    "  - improved: an existing feature works better, faster, or in more "
    "situations.\n"
    "  - fixed: corrects a defect (most fix: commits map here).\n"
    "  - When uncertain between new and improved, prefer improved unless "
    "the commit clearly introduces something brand new.\n\n"
    "Voice rules:\n"
    "  - Lead each highlight with a verb in present tense (\"adds\", "
    "\"speeds up\", \"fixes\").\n"
    "  - Describe what staff will notice, not what changed in the code.\n"
    "  - Never invent features. If a commit is unclear or technical, "
    "summarise it generically (e.g. \"small reliability improvements\") "
    "rather than guessing.\n"
    "  - Avoid these terms: SHA, deploy, migration, schema, refactor, "
    "dependency, framework names, file names.\n"
    "  - Tone: friendly, factual, neutral. Not marketing.\n\n"
    "Output the JSON object only — no markdown fences, no explanation, "
    "no trailing text."
)

_USER_PROMPT_TEMPLATE = (
    "Commits since the last release (most recent first):\n\n{commits}\n\n"
    "Output the JSON object now."
)

_MAX_TOKENS = 800
_TEMPERATURE = 0.4


@dataclass(frozen=True)
class ReleaseNotesSuggestion:
    title: str
    summary: str
    # list of {"category": str, "text": str} — already validated to the
    # _VALID_CATEGORIES set with text length-bounded. May be empty when
    # low_confidence is True (last-resort fallback).
    highlights: list[dict] = field(default_factory=list)
    low_confidence: bool = False


def is_release_notes_ai_available() -> bool:
    return is_llm_configured()


def _try_extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from raw LLM output via a cascade.

    Returns the dict if any strategy yields a parse with at least one of
    title/summary/highlights present. Returns None otherwise. The caller
    is responsible for shape validation downstream.
    """
    text = text.strip()

    # 1. Strict — the model produced exactly what we asked for.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Fenced — model wrapped JSON in ```json ... ``` or just ``` ... ```.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 3. Substring — find the first { to last } and try that slice.
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            obj = json.loads(text[first:last + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _coerce_highlights(raw: object) -> list[dict]:
    """Validate and normalize a parsed highlights list.

    Drops entries that are not dict-shaped, are missing required keys,
    have invalid categories, or have empty/oversized text. Returns a
    clean list (possibly empty if everything was bad).
    """
    if not isinstance(raw, list):
        return []
    clean: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        category = entry.get("category")
        text = entry.get("text")
        if not isinstance(category, str) or category not in _VALID_CATEGORIES:
            continue
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue
        # Truncate over-long highlights rather than dropping — preserves
        # the AI's intent, admin can shorten via the editor.
        if len(text) > 140:
            text = text[:137].rstrip() + "…"
        clean.append({"category": category, "text": text})
    return clean


def generate_release_notes_suggestion(
    *, commits: list[str],
) -> ReleaseNotesSuggestion:
    """Generate a release-notes suggestion from filtered commit subjects.

    Args:
        commits: list of commit subject strings, already filtered to feat:/fix:
            (caller is responsible for the filter — see filter_user_facing in
            github_commits.py).

    Raises:
        ValueError: when commits is empty (no point calling the LLM).
        LLMError: when the underlying LLM call fails (network, quota, auth).
            Caller should translate to HTTP 502.

    Never raises on parse failure — falls through to a deterministic
    fallback that sets low_confidence=True so the admin UI can warn and
    the human can author the highlights manually.
    """
    if not commits:
        raise ValueError(
            "Cannot generate release notes from an empty commit list."
        )

    user_prompt = _USER_PROMPT_TEMPLATE.format(commits="\n".join(commits))
    client = get_llm_client()

    # Note: not catching LLMError here — let it propagate so the route
    # layer can translate to a 502.
    result = client.complete(
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
    )

    obj = _try_extract_json(result.text)
    if obj is not None:
        title = obj.get("title")
        summary = obj.get("summary")
        highlights = _coerce_highlights(obj.get("highlights"))

        # Require at minimum a title and at least one valid highlight to
        # call the structured path successful. A summary-less response
        # synthesizes the summary from the title — admin can rewrite.
        if isinstance(title, str) and title.strip() and highlights:
            return ReleaseNotesSuggestion(
                title=title.strip(),
                summary=(
                    summary.strip()
                    if isinstance(summary, str) and summary.strip()
                    else f"Updates: {title.strip()}."
                ),
                highlights=highlights,
                low_confidence=False,
            )
        # Partial output: structured but missing required pieces.
        logger.warning(
            "Release-notes AI returned partial structured output. "
            "title_ok=%s summary_ok=%s highlights_count=%d. Output preview: %s",
            isinstance(title, str) and bool(title and title.strip()),
            isinstance(summary, str) and bool(summary and summary.strip()),
            len(highlights),
            result.text[:200],
        )

    # Last-resort fallback. Output couldn't be structured into our shape.
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    return ReleaseNotesSuggestion(
        title=f"Updates on {today}",
        summary=(
            "The AI response could not be parsed automatically. Please "
            "review the raw output below and author highlights manually."
        ),
        highlights=[],
        low_confidence=True,
    )
