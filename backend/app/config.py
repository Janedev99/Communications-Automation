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

    # ── Anthropic / Claude ────────────────────────────────────────────────────
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

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,http://localhost:3004,http://localhost:5173"

    # ── Seed admin ────────────────────────────────────────────────────────────
    admin_email: str = "jane@example.com"
    admin_name: str = "Jane"
    admin_password: str = ""

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
        if self.app_secret_key == "dev-secret-key-replace-in-production":
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
