"""
Tests for the configurable draft signature (system_settings.draft_signature)
and its wiring into the draft prompt.
"""
from app.services import system_settings as ss
from app.services.draft_generator import _USER_PROMPT_TEMPLATE


def test_signature_patch_preserves_formatting(logged_in_admin, db_session):
    sig = "Thanks so much,\n\nJane\n\nJane M. Schilmoeller, CPA\nSchilmoeller & Schoenfield, PC"
    resp = logged_in_admin.patch(
        "/api/v1/system-settings/draft_signature",
        json={"value": sig},
    )
    assert resp.status_code == 200
    # Case + newlines preserved (NOT lowercased like the boolean flags).
    assert resp.json()["value"] == sig
    db_session.expire_all()
    assert ss.get_setting(db_session, ss.DRAFT_SIGNATURE) == sig


def test_auto_send_still_validates_boolean(logged_in_admin):
    bad = logged_in_admin.patch(
        "/api/v1/system-settings/auto_send_enabled", json={"value": "maybe"}
    )
    assert bad.status_code == 422
    ok = logged_in_admin.patch(
        "/api/v1/system-settings/auto_send_enabled", json={"value": "TRUE"}
    )
    assert ok.status_code == 200
    assert ok.json()["value"] == "true"  # normalized to lowercase


def test_unknown_setting_key_is_404(logged_in_admin):
    resp = logged_in_admin.patch(
        "/api/v1/system-settings/bogus_key", json={"value": "x"}
    )
    assert resp.status_code == 404


def test_user_prompt_uses_signoff_instruction_placeholder():
    # The sign-off line is now injected (signature override or branding rule),
    # not the old hard-coded firm-team text.
    assert "{signoff_instruction}" in _USER_PROMPT_TEMPLATE
    assert "{firm_name} team" not in _USER_PROMPT_TEMPLATE
