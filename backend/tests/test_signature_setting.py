"""
Tests for the company signature setting (system_settings.company_signature)
and the system-settings PATCH allowlist. (Pre-018 this key was the global
`draft_signature`; per-user signatures are covered in
test_per_user_signatures.py.)
"""
from app.services import system_settings as ss
from app.services.draft_generator import _USER_PROMPT_TEMPLATE


def test_company_signature_patch_preserves_formatting(logged_in_admin, db_session):
    sig = "Schilmoeller & Schoenfield, PC\n3131 Eastside Street, Suite 430\nOffice:  (713) 527-9281 Ext 1"
    resp = logged_in_admin.patch(
        "/api/v1/system-settings/company_signature",
        json={"value": sig},
    )
    assert resp.status_code == 200
    # Case + newlines preserved (NOT lowercased like the boolean flags).
    assert resp.json()["value"] == sig
    db_session.expire_all()
    assert ss.get_setting(db_session, ss.COMPANY_SIGNATURE) == sig


def test_retired_draft_signature_key_is_404(logged_in_admin):
    # The pre-018 global key is no longer patchable.
    resp = logged_in_admin.patch(
        "/api/v1/system-settings/draft_signature", json={"value": "x"}
    )
    assert resp.status_code == 404


def test_legacy_signature_key_is_not_patchable(logged_in_admin):
    # Frozen transition value — editing it would break legacy-strip matching.
    resp = logged_in_admin.patch(
        "/api/v1/system-settings/legacy_draft_signature", json={"value": "x"}
    )
    assert resp.status_code == 404


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
    assert "{signoff_instruction}" in _USER_PROMPT_TEMPLATE
    assert "{firm_name} team" not in _USER_PROMPT_TEMPLATE
