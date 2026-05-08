"""LLM-backed release-notes generation.

Routes through the existing provider-agnostic LLMClient Protocol so it works
with whichever provider is configured (Anthropic in dev, RunPod-hosted Gemma
in prod, or any future swap-in). The release-notes service must NOT import
anthropic or openai directly — that would break the abstraction.

Defensive JSON parsing handles cases where the model wraps output in fenced
blocks or prepends conversational filler (common with smaller models).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.llm_client import LLMError, get_llm_client, is_llm_configured

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are a release-notes writer for non-technical staff at an "
    "accounting firm. Input is a list of commit messages from the last "
    "release. Each commit starts with a category prefix: feat: a new "
    "capability staff can use, fix: a bug that was corrected.\n\n"
    "Produce two outputs as a single JSON object with exactly two keys, "
    "title and body, with no surrounding prose.\n\n"
    "title: 5 to 8 words, no jargon, present tense.\n"
    "body: 80 to 150 words of markdown. Group changes under headings "
    "when there are 3 or more items. Use bullets. Describe what staff "
    "will notice, not what changed in the code. Never invent features. "
    "If a commit is unclear or technical, summarise it generically (for "
    "example, small reliability improvements) rather than guessing.\n\n"
    "Avoid these terms in the output: SHA, deploy, migration, schema, "
    "refactor, dependency, framework names, file names. Do not promise "
    "capabilities the commits do not describe. Do not invite the user "
    "to take actions; those belong in a different channel.\n\n"
    "Tone: friendly, factual, neutral. Not marketing."
)

_USER_PROMPT_TEMPLATE = (
    "Commits since the last release (most recent first):\n\n{commits}\n\n"
    "Output the JSON object now."
)

_MAX_TOKENS = 600
_TEMPERATURE = 0.4


@dataclass(frozen=True)
class ReleaseNotesSuggestion:
    title: str
    body: str
    low_confidence: bool


def is_release_notes_ai_available() -> bool:
    return is_llm_configured()


def _try_parse(text: str) -> dict | None:
    """Try to extract a {title, body} JSON object via a cascade of strategies.

    Returns the dict if parsing succeeds AND both 'title' and 'body' keys
    are present. Returns None otherwise (caller falls through to
    last-resort fallback).
    """
    text = text.strip()

    # 1. Strict — the model produced exactly what we asked for.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "title" in obj and "body" in obj:
            return obj
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Fenced — the model wrapped JSON in ```json ... ``` or just ``` ... ```.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if isinstance(obj, dict) and "title" in obj and "body" in obj:
                return obj
        except json.JSONDecodeError:
            pass

    # 3. Substring — find the first { to last } and try that slice.
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            obj = json.loads(text[first:last + 1])
            if isinstance(obj, dict) and "title" in obj and "body" in obj:
                return obj
        except json.JSONDecodeError:
            pass

    return None


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
    fallback that sets low_confidence=True so the admin UI can warn.
    """
    if not commits:
        raise ValueError(
            "Cannot generate release notes from an empty commit list."
        )

    user_prompt = _USER_PROMPT_TEMPLATE.format(commits="\n".join(commits))
    client = get_llm_client()

    # Note: not catching LLMError here — let it propagate so the route
    # layer can translate to a 502. The contract is that this function
    # raises LLMError on upstream failures.
    result = client.complete(
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
    )

    parsed = _try_parse(result.text)
    if parsed is not None:
        return ReleaseNotesSuggestion(
            title=str(parsed["title"]).strip(),
            body=str(parsed["body"]).strip(),
            low_confidence=False,
        )

    # Last-resort fallback. Output couldn't be structured.
    logger.warning(
        "Release-notes AI output could not be parsed as JSON; falling back. "
        "Output preview: %s",
        result.text[:200],
    )
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    return ReleaseNotesSuggestion(
        title=f"Updates on {today}",
        body=result.text.strip(),
        low_confidence=True,
    )
