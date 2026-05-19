"""
Tests for LLM client provider isolation.

Background: llm_client.py previously fell through `settings.llm_api_key or
settings.anthropic_api_key` (and similarly for model) when LLM_PROVIDER=anthropic.
That asymmetry — openai_compat refused cross-pollution, anthropic accepted it
— meant a stale LLM_API_KEY (e.g. a RunPod `rpa_*` key in the same .env)
would be sent to Anthropic, producing silent 401 / 404 failures and silent
demotion to rules_fallback.

These tests pin the symmetric isolation: when provider=anthropic, only
ANTHROPIC_API_KEY + CLAUDE_MODEL are used.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _reset_singletons():
    """Force both the llm_client and categorizer singletons to rebuild."""
    from app.services import categorizer as _cat
    from app.services import llm_client as _llm
    _llm.reset_llm_client()
    _cat._categorizer = None


def _clear_settings_cache():
    """Bust the lru_cache on get_settings so env changes take effect."""
    from app.config import get_settings
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure each test starts with fresh singletons + settings cache."""
    _clear_settings_cache()
    _reset_singletons()
    yield
    _clear_settings_cache()
    _reset_singletons()


def test_anthropic_provider_ignores_runpod_llm_api_key(monkeypatch):
    """
    Reproduces the production bug: LLM_PROVIDER=anthropic with a stale
    LLM_API_KEY (RunPod's `rpa_*` shape) in the same .env. The client must
    use ANTHROPIC_API_KEY, NOT the RunPod key.
    """
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key-for-test")
    monkeypatch.setenv("LLM_API_KEY", "rpa_RUNPOD_LEFTOVER_KEY")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-5")
    _clear_settings_cache()
    _reset_singletons()

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        from app.services.llm_client import get_llm_client
        client = get_llm_client()

    # Verify the Anthropic SDK was constructed with the ANTHROPIC key,
    # not the RunPod key.
    assert mock_anthropic_cls.called, "AnthropicLLMClient must construct anthropic.Anthropic"
    call_kwargs = mock_anthropic_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-ant-real-key-for-test", (
        f"Expected ANTHROPIC_API_KEY, got {call_kwargs['api_key']!r} "
        f"(cross-pollination bug regression)"
    )
    # And the model came from CLAUDE_MODEL, not LLM_MODEL
    assert client.model == "claude-sonnet-4-5", (
        f"Expected CLAUDE_MODEL, got {client.model!r}"
    )


def test_anthropic_provider_with_unset_llm_vars_still_works(monkeypatch):
    """Sanity: when LLM_API_KEY/LLM_MODEL aren't set at all, anthropic path works."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key-for-test")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-5")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    _clear_settings_cache()
    _reset_singletons()

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        from app.services.llm_client import get_llm_client
        client = get_llm_client()

    call_kwargs = mock_anthropic_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-ant-real-key-for-test"
    assert client.model == "claude-sonnet-4-5"


def test_openai_compat_provider_isolation_unchanged(monkeypatch):
    """
    Regression guard: the openai_compat path's existing isolation (it refuses
    to fall back to anthropic_api_key) must not regress as a side-effect of
    the anthropic-side fix.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-DO-NOT-USE-FOR-OPENAI")
    monkeypatch.setenv("LLM_API_KEY", "rpa_runpod_key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example-runpod.proxy/v1")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    _clear_settings_cache()
    _reset_singletons()

    with patch("openai.OpenAI") as mock_openai_cls:
        from app.services.llm_client import get_llm_client
        client = get_llm_client()

    call_kwargs = mock_openai_cls.call_args.kwargs
    # openai_compat should use LLM_API_KEY — never ANTHROPIC_API_KEY
    assert call_kwargs["api_key"] == "rpa_runpod_key", (
        f"openai_compat must NOT cross-pollinate to anthropic_api_key; "
        f"got {call_kwargs['api_key']!r}"
    )
    assert client.model == "Qwen/Qwen2.5-7B-Instruct"


def test_is_llm_configured_anthropic_ignores_stale_llm_api_key(monkeypatch):
    """
    is_llm_configured() must mirror get_llm_client's isolation. Before the fix,
    a stale LLM_API_KEY (any non-empty value) made is_llm_configured() return
    True even when ANTHROPIC_API_KEY was empty, masking misconfiguration as
    a healthy provider.
    """
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # truly unconfigured
    monkeypatch.setenv("LLM_API_KEY", "rpa_runpod_leftover")
    _clear_settings_cache()

    from app.services.llm_client import is_llm_configured
    assert is_llm_configured() is False, (
        "Empty ANTHROPIC_API_KEY must mean 'not configured' even when a "
        "stale LLM_API_KEY is present — it can't substitute for the real one."
    )


def test_is_llm_configured_anthropic_placeholder_treated_as_unconfigured(monkeypatch):
    """The "sk-ant-placeholder" sentinel must still register as not-configured."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-tests")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    _clear_settings_cache()

    from app.services.llm_client import is_llm_configured
    assert is_llm_configured() is False


def test_warning_logged_when_stale_llm_api_key_set(monkeypatch, caplog):
    """
    Operator UX: stale LLM_API_KEY shouldn't fail silently. A warning should
    fire on client init telling the operator that LLM_API_KEY is being
    ignored and pointing them at LLM_PROVIDER=openai_compat.
    """
    import logging
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("LLM_API_KEY", "rpa_runpod_leftover")
    _clear_settings_cache()
    _reset_singletons()

    with patch("anthropic.Anthropic"):
        from app.services.llm_client import get_llm_client
        with caplog.at_level(logging.WARNING, logger="app.services.llm_client"):
            get_llm_client()

    assert any(
        "non-Anthropic" in rec.message and "LLM_API_KEY" in rec.message
        for rec in caplog.records
    ), "Expected a warning about the stale non-Anthropic LLM_API_KEY"
