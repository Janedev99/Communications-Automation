"""
LLM provider abstraction.

Per the 05/02 product call: Schiller CPA approved migrating off third-party
hosted LLM APIs (Anthropic Claude / OpenAI direct) onto a self-hosted Gemma
model running on RunPod's GPU rental. The data path is now:

    inbound email → Schiller server → RunPod (process) → response → Schiller server

with no client-data ever resting on a third party. RunPod's serverless GPU
endpoints expose an OpenAI-compatible API (vLLM under the hood), so the
"openai_compat" provider here works for RunPod, OpenAI proper, vLLM, and
any other OpenAI-compatible serving stack.

Two providers are supported:

  - "anthropic"     — wraps the anthropic SDK (the original implementation).
                       Kept so the dev environment can still run with a Claude
                       key while Gar provisions the RunPod endpoint, and so
                       the test suite's anthropic mocks keep working.
  - "openai_compat" — wraps the openai SDK with a configurable base_url. Use
                       for RunPod, OpenAI direct, or anything vLLM-shaped.

Pick via ``settings.llm_provider`` ("anthropic" | "openai_compat"). Both
providers expose the same shape:

    client.complete(system=..., user=..., max_tokens=..., temperature=...)
        -> LLMResult(text, prompt_tokens, completion_tokens)

so call sites (categorizer, draft_generator) don't care which provider is
active — they just code against the protocol.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResult:
    """Normalised completion result, provider-agnostic."""
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMError(Exception):
    """
    Wraps any underlying provider error (network, quota, parse, auth) so
    callers can `except LLMError` once instead of teaching every call site
    about anthropic.APIError, openai.APIError, urllib timeouts, etc.
    """


@runtime_checkable
class LLMClient(Protocol):
    """The minimal interface every provider implements."""

    @property
    def model(self) -> str: ...

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult: ...


# ── Anthropic provider ────────────────────────────────────────────────────────


class AnthropicLLMClient:
    """
    Wraps anthropic.Anthropic. Kept for backward compatibility — every test
    fixture and the original demo data was built against Claude, and we don't
    want to lose that fallback while RunPod is being provisioned.
    """

    def __init__(self, *, api_key: str, model: str, timeout: float) -> None:
        # Local import so this module loads even if the optional anthropic
        # package isn't installed (e.g. lean RunPod-only deployments).
        import anthropic
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

        text = response.content[0].text if response.content else ""
        usage = response.usage
        return LLMResult(
            text=text,
            prompt_tokens=usage.input_tokens if usage else None,
            completion_tokens=usage.output_tokens if usage else None,
        )


# ── OpenAI-compatible provider (RunPod, OpenAI, vLLM, …) ──────────────────────


class OpenAICompatLLMClient:
    """
    Wraps openai.OpenAI with a configurable base_url. Works against any
    endpoint that speaks OpenAI's chat-completions protocol — RunPod
    serverless endpoints, OpenAI proper, self-hosted vLLM, llama.cpp's
    server, etc.

    For RunPod, the endpoint URL pattern is:
        https://api.runpod.ai/v2/<endpoint-id>/openai/v1
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
    ) -> None:
        import openai
        self._openai = openai
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url or None,  # None falls back to OpenAI's default
            timeout=timeout,
        )
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except self._openai.APIError as exc:
            raise LLMError(f"OpenAI-compatible API error: {exc}") from exc

        # Defensive: some serving stacks return empty choices on certain
        # safety/rate-limit conditions; treat as an LLM error rather than
        # crashing on indexing.
        if not response.choices:
            raise LLMError("LLM returned no choices")

        text = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResult(
            text=text,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )


# ── Factory ───────────────────────────────────────────────────────────────────


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """
    Return a singleton client for the configured provider.

    Settings precedence (so the same .env can carry both old and new vars
    during the migration):

      - ``llm_api_key`` falls back to ``anthropic_api_key`` for the
        anthropic provider so existing dev .envs keep working.
      - ``llm_model`` falls back to ``claude_model`` for the anthropic
        provider for the same reason.
    """
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    provider = settings.llm_provider
    timeout = settings.llm_timeout

    if provider == "openai_compat":
        api_key = settings.llm_api_key or settings.anthropic_api_key  # ANTHROPIC_API_KEY shouldn't be a real OpenAI key, but allow it as a last-ditch fallback
        base_url = settings.llm_base_url
        model = settings.llm_model or "google/gemma-2-27b-it"
        if not api_key:
            logger.warning(
                "LLM provider=openai_compat but no LLM_API_KEY is set — "
                "calls will fail at the underlying SDK with an auth error."
            )
        if not base_url:
            logger.warning(
                "LLM provider=openai_compat but no LLM_BASE_URL is set — "
                "the openai SDK will default to api.openai.com which may "
                "not be intended in this deployment."
            )
        logger.info(
            "LLM client initialised: provider=openai_compat model=%s base_url=%s",
            model,
            base_url or "<openai default>",
        )
        _client = OpenAICompatLLMClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
        return _client

    # Default: anthropic. Pull from llm_* first, fall back to legacy fields.
    api_key = settings.llm_api_key or settings.anthropic_api_key
    model = settings.llm_model or settings.claude_model
    logger.info("LLM client initialised: provider=anthropic model=%s", model)
    _client = AnthropicLLMClient(
        api_key=api_key,
        model=model,
        timeout=timeout,
    )
    return _client


def reset_llm_client() -> None:
    """Test hook — clears the singleton so a fresh provider can be picked up."""
    global _client
    _client = None
