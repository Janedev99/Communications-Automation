"""
Application configuration loaded from environment variables via Pydantic Settings.
All settings have sensible defaults so the app can boot for local development
without a fully populated .env — but secrets (API keys, DB passwords) must be
provided explicitly.
"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
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

    # ── Seed admin ────────────────────────────────────────────────────────────
    admin_email: str = "jane@example.com"
    admin_name: str = "Jane"
    admin_password: str = ""

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @field_validator("app_secret_key")
    @classmethod
    def warn_weak_secret(cls, v: str) -> str:
        if v == "dev-secret-key-replace-in-production":
            import warnings
            warnings.warn(
                "APP_SECRET_KEY is using the insecure default. "
                "Set a strong random value before deploying.",
                stacklevel=2,
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. Import this throughout the app."""
    return Settings()
