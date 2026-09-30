"""
Secrets never appear when Settings is printed (FIX/hide-secrets-in-settings-repr).

A test failure on 2026-09-30 printed the whole Settings object, including the
live Graph client secret, because pydantic's repr lists every field. Any log
line or error that formats settings would leak the same way.
"""
from __future__ import annotations

from app.config import Settings

SECRET_FIELDS = (
    "app_secret_key",
    "llm_api_key",
    "anthropic_api_key",
    "msgraph_client_secret",
    "imap_password",
    "smtp_password",
    "slack_webhook_url",
    "admin_password",
)


def test_repr_and_str_hide_every_secret():
    values = {f: f"LEAK-{f}-9f3a" for f in SECRET_FIELDS}
    s = Settings(**values)
    for text in (repr(s), str(s)):
        for f, v in values.items():
            assert v not in text, f"{f} leaked into settings output"


def test_secret_values_are_still_readable_in_code():
    s = Settings(msgraph_client_secret="still-usable")
    assert s.msgraph_client_secret == "still-usable"


def test_non_secret_fields_still_shown():
    s = Settings(msgraph_mailbox="mailbox@example.com")
    assert "mailbox@example.com" in repr(s)
