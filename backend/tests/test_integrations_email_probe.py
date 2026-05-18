"""
Tests for ``_probe_email_provider`` — focused on the "M365 credentials
staged but not the active provider" surface added in
FEAT/integrations-show-m365-staged.

The full integrations endpoint has no existing test surface; these tests
target only the new branch so they stay tight and stable.
"""
from __future__ import annotations

from unittest.mock import patch

from app.api.integrations import _probe_email_provider


class _StubSettings:
    """Tiny stand-in for app.config.Settings — only the attributes the
    probe touches are populated. Mutable so each test can dial in the
    state under test without going through pydantic-settings lifecycle."""

    def __init__(self, **overrides):
        # Defaults match the dev env: imap active, no creds anywhere.
        self.email_provider = "imap"
        self.imap_host = ""
        self.imap_username = ""
        self.msgraph_client_id = ""
        self.msgraph_client_secret = ""
        self.msgraph_tenant_id = ""
        self.msgraph_mailbox = ""
        for k, v in overrides.items():
            setattr(self, k, v)


def _probe_with(settings_stub, poller_at=None):
    """Run the probe with patched dependencies. ``poller_at`` controls
    ``last_successful_poll_at`` so we can assert status independently of
    the poller's real state."""
    with patch("app.api.integrations.get_settings", return_value=settings_stub):
        with patch(
            "app.services.email_intake.last_successful_poll_at",
            poller_at,
        ):
            return _probe_email_provider()


# =============================================================================
# Active provider = imap, no creds anywhere → unchanged baseline behavior
# =============================================================================

def test_imap_active_no_msgraph_credentials_no_extra_keys():
    """Baseline: no microsoft_graph keys when M365 creds are not staged."""
    result = _probe_with(_StubSettings())
    assert "microsoft_graph" not in result["config"]
    assert "microsoft_graph_mailbox" not in result["config"]


# =============================================================================
# Active provider = imap, MSGraph creds staged → positive signal surfaces
# =============================================================================

def test_imap_active_with_msgraph_staged_shows_integrated():
    """Staged M365 credentials surface as a positive 'integrated' signal."""
    result = _probe_with(_StubSettings(
        msgraph_client_id="test-cid",
        msgraph_client_secret="test-secret",
        msgraph_tenant_id="test-tid",
        msgraph_mailbox="jane@schilcpa.com",
    ))
    assert result["config"]["microsoft_graph"] == "integrated"
    assert result["config"]["microsoft_graph_mailbox"] == "jane@schilcpa.com"
    # The active provider remains imap — staged is not active.
    assert result["config"]["provider"] == "imap"


def test_partial_msgraph_credentials_do_not_show_integrated():
    """One missing field disqualifies — don't show 'integrated' if incomplete."""
    result = _probe_with(_StubSettings(
        msgraph_client_id="test-cid",
        msgraph_client_secret="test-secret",
        msgraph_tenant_id="test-tid",
        # mailbox intentionally blank
    ))
    assert "microsoft_graph" not in result["config"]


# =============================================================================
# Active provider = msgraph → no duplicate "integrated" key
# =============================================================================

def test_msgraph_active_does_not_duplicate_with_integrated_key():
    """When MSGraph is already active, don't also show a redundant 'integrated'
    signal — the existing mailbox/tenant rows say enough."""
    result = _probe_with(_StubSettings(
        email_provider="msgraph",
        msgraph_client_id="test-cid",
        msgraph_client_secret="test-secret",
        msgraph_tenant_id="test-tid",
        msgraph_mailbox="jane@schilcpa.com",
    ))
    # Active-provider branch populates mailbox + tenant, not the staged signal.
    assert result["config"]["mailbox"] == "jane@schilcpa.com"
    assert "microsoft_graph" not in result["config"]
    assert "microsoft_graph_mailbox" not in result["config"]
