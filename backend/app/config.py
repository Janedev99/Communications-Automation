"""
Application configuration loaded from environment variables via Pydantic Settings.
All settings have sensible defaults so the app can boot for local development
without a fully populated .env — but secrets (API keys, DB passwords) must be
provided explicitly.
"""
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=["../.env", ".env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: Literal["development", "production"] = "development"
    app_secret_key: str = "dev-secret-key-replace-in-production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: Literal["debug", "info", "warning", "error"] = "info"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+psycopg2://jane_user:jane_pass@localhost:5432/jane_automation"
    )

    # ── Session ───────────────────────────────────────────────────────────────
    session_ttl_hours: int = 8

    # ── LLM provider (Anthropic / RunPod / OpenAI / vLLM) ─────────────────────
    # The 05/02 product call approved migrating off third-party hosted LLM
    # APIs onto a self-hosted Gemma model on RunPod (data stays inside the
    # firm's rented hardware). RunPod's serverless GPU endpoints expose an
    # OpenAI-compatible API, so "openai_compat" works for RunPod, OpenAI
    # proper, vLLM, and llama.cpp's server.
    #
    # Default is "openai_compat" — that is the canonical path for this
    # deployment. "anthropic" is now an explicit opt-in for environments
    # that still want Claude (notably the test suite, which mocks the
    # anthropic SDK; tests/conftest.py pins LLM_PROVIDER=anthropic before
    # importing the app so existing fixtures keep working).
    llm_provider: Literal["anthropic", "openai_compat"] = "openai_compat"
    llm_api_key: str = ""
    llm_base_url: str = ""  # e.g. https://api.runpod.ai/v2/<endpoint-id>/openai/v1
    llm_model: str = ""  # falls back to claude_model when provider=anthropic
    llm_timeout: float = 30.0

    # Legacy fields — still read by AnthropicLLMClient for back-compat with
    # existing .env files and tests. New deployments should use llm_*.
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"

    # ── Email Provider ────────────────────────────────────────────────────────
    email_provider: Literal["msgraph", "imap"] = "imap"

    # MS Graph
    msgraph_client_id: str = ""
    msgraph_client_secret: str = ""
    msgraph_tenant_id: str = ""
    msgraph_mailbox: str = ""

    # IMAP / SMTP
    imap_host: str = ""
    imap_port: int = 993
    imap_use_ssl: bool = True
    imap_username: str = ""
    imap_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_username: str = ""
    smtp_password: str = ""

    # ── Polling ───────────────────────────────────────────────────────────────
    email_poll_interval_seconds: int = 60

    # ── Notifications ─────────────────────────────────────────────────────────
    notify_log_file: str = ""
    slack_webhook_url: str = ""

    # ── Draft Generation ──────────────────────────────────────────────────────
    draft_temperature: float = 0.3
    draft_max_tokens: int = 1024
    draft_auto_generate: bool = True   # Set to False to disable auto-generation in pipeline
    firm_name: str = "Schiller CPA"
    firm_owner_name: str = "Jane Schiller"
    firm_owner_email: str = "jane@schilcpa.com"

    # ── GitHub integration ────────────────────────────────────────────────────
    # GitHub integration for release-notes draft generation
    github_token: str = ""
    github_repo_owner: str = "rheynardjan"
    github_repo_name: str = "schillerCPA"

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,http://localhost:3004,http://localhost:5173"

    # ── Seed admin ────────────────────────────────────────────────────────────
    admin_email: str = "jane@example.com"
    admin_name: str = "Jane"
    admin_password: str = ""

    # ── Trusted Proxies (rate-limiter / IP extraction) ────────────────────────
    # Comma-separated list of trusted proxy IP addresses (e.g. Caddy, Railway LB).
    # When non-empty, X-Forwarded-For is trusted ONLY if the direct connection IP
    # matches one of these. Prevents rate-limit spoofing via header injection.
    # Example: TRUSTED_PROXIES=10.0.0.1,172.31.0.1
    trusted_proxies: str = ""

    @property
    def trusted_proxy_set(self) -> frozenset[str]:
        """Return the set of trusted proxy IPs (parsed from TRUSTED_PROXIES)."""
        return frozenset(
            ip.strip() for ip in self.trusted_proxies.split(",") if ip.strip()
        )

    # ── AI Budget (T2.3) ──────────────────────────────────────────────────────
    # Daily token budget across all Claude API calls. Set to 0 to disable.
    daily_token_budget: int = 1_000_000

    # ── Shadow Mode (T2.4) ────────────────────────────────────────────────────
    # When True, emails are categorized but no AI drafts are auto-generated.
    # Useful for initial deployment validation without sending AI-generated replies.
    shadow_mode: bool = False

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _validate_imap_consistency(self) -> "Settings":
        """
        T2.2: When email_provider is 'imap', IMAP and SMTP usernames must match.
        SPF/DKIM alignment requires the sending address to match the envelope-from.
        """
        if self.email_provider == "imap":
            if self.imap_username and self.smtp_username:
                if self.imap_username.lower() != self.smtp_username.lower():
                    raise ValueError(
                        f"IMAP_USERNAME ({self.imap_username!r}) and "
                        f"SMTP_USERNAME ({self.smtp_username!r}) must match when "
                        "EMAIL_PROVIDER=imap. Mismatched usernames cause SPF/DKIM "
                        "alignment failures."
                    )
        return self

    @model_validator(mode="after")
    def _warn_weak_secret(self) -> "Settings":
        is_dev_secret = self.app_secret_key == "dev-secret-key-replace-in-production"
        is_placeholder_anthropic = self.anthropic_api_key.startswith("sk-ant-placeholder")

        # The LLM-key check is provider-aware: only enforce a real key for
        # the active provider so a RunPod deployment isn't blocked by a
        # placeholder Anthropic key it doesn't use.
        if self.llm_provider == "openai_compat":
            llm_key_missing = not self.llm_api_key
        else:
            llm_key_missing = is_placeholder_anthropic or not self.anthropic_api_key

        if self.is_production:
            if is_dev_secret:
                raise ValueError(
                    "APP_SECRET_KEY is the development default but APP_ENV=production. "
                    "Generate a strong key: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            if llm_key_missing and self.llm_provider == "openai_compat":
                raise ValueError(
                    "LLM_PROVIDER=openai_compat but LLM_API_KEY is empty. "
                    "Set the RunPod / OpenAI key and ensure LLM_BASE_URL points "
                    "at the right endpoint."
                )
            if llm_key_missing and self.llm_provider == "anthropic":
                raise ValueError(
                    "ANTHROPIC_API_KEY is a placeholder but APP_ENV=production. "
                    "Set a real key from https://console.anthropic.com, or "
                    "switch LLM_PROVIDER to openai_compat."
                )
            return self

        if is_dev_secret:
            import warnings
            warnings.warn(
                "APP_SECRET_KEY is using the insecure default. "
                "Set a strong random value before deploying.",
                stacklevel=2,
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. Import this throughout the app."""
    return Settings()
