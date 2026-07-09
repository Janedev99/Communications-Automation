"""
Tests for per-user signatures (migration 018) — the SEND-time half.

Resolution chain under test:
    human sender → personal signature → (none set) → company signature
    T1 auto-send (no human)          → company signature

Plus the transition behavior: a pre-018 draft with the old global signature
baked into its body gets that block stripped and replaced by the sender's
at send time (exact-suffix match only — staff-typed closings are never
touched).

Generation-side guarantees (body is signature-less, model writes no closing)
live in test_draft_signature_append.py.
"""
from __future__ import annotations

import pytest

from app.services import system_settings as ss
from app.services.signatures import (
    apply_signature,
    company_signature,
    signature_for_sender,
)
from tests.test_drafts_send import _seed_thread_with_draft

COMPANY_SIG = "Schilmoeller & Schoenfield, PC\nOffice:  (713) 527-9281 Ext 1"
PERSONAL_SIG = "Thanks,\n\nGus\nSchilmoeller & Schoenfield, PC"
LEGACY_SIG = "Thanks so much,\n\nJane\n\nJane M. Schilmoeller, CPA"


@pytest.fixture(autouse=True)
def _isolate_signature_settings(db_session):
    """The test DB is shared without per-test rollback — pin the signature
    settings to known values before each test and clear them after, so this
    module is order-independent and can't taint other modules' sends."""
    ss.set_setting(db_session, ss.COMPANY_SIGNATURE, COMPANY_SIG)
    ss.set_setting(db_session, ss.LEGACY_DRAFT_SIGNATURE, LEGACY_SIG)
    db_session.commit()
    yield
    ss.set_setting(db_session, ss.COMPANY_SIGNATURE, "")
    ss.set_setting(db_session, ss.LEGACY_DRAFT_SIGNATURE, "")
    db_session.commit()


# ===========================================================================
# 1. Resolution chain (unit)
# ===========================================================================

def test_sender_with_personal_signature_wins(db_session, admin_user):
    admin_user.signature = PERSONAL_SIG
    db_session.flush()
    assert signature_for_sender(db_session, admin_user) == PERSONAL_SIG


def test_sender_without_personal_falls_back_to_company(db_session, admin_user):
    admin_user.signature = None
    db_session.flush()
    assert signature_for_sender(db_session, admin_user) == COMPANY_SIG


def test_whitespace_only_personal_signature_falls_back(db_session, admin_user):
    admin_user.signature = "   \n  "
    db_session.flush()
    assert signature_for_sender(db_session, admin_user) == COMPANY_SIG


def test_no_human_sender_resolves_to_company(db_session):
    assert signature_for_sender(db_session, None) == COMPANY_SIG
    assert company_signature(db_session) == COMPANY_SIG


# ===========================================================================
# 2. apply_signature (unit)
# ===========================================================================

def test_apply_appends_signature(db_session):
    out = apply_signature(db_session, "Body text.", PERSONAL_SIG)
    assert out == f"Body text.\n\n{PERSONAL_SIG}"


def test_apply_is_idempotent(db_session):
    once = apply_signature(db_session, "Body text.", PERSONAL_SIG)
    twice = apply_signature(db_session, once, PERSONAL_SIG)
    assert twice == once
    assert twice.count("Gus") == 1


def test_apply_strips_legacy_baked_signature(db_session):
    """A pre-018 draft body ending with the old global signature gets it
    stripped and replaced with the sender's."""
    legacy_body = f"Here is your answer.\n\n{LEGACY_SIG}"
    out = apply_signature(db_session, legacy_body, PERSONAL_SIG)
    assert "Jane M. Schilmoeller, CPA" not in out
    assert out == f"Here is your answer.\n\n{PERSONAL_SIG}"


def test_apply_replaces_company_block_with_personal(db_session):
    body = f"Here is your answer.\n\n{COMPANY_SIG}"
    out = apply_signature(db_session, body, PERSONAL_SIG)
    assert out == f"Here is your answer.\n\n{PERSONAL_SIG}"


def test_apply_never_touches_staff_typed_closings(db_session):
    """Only exact-suffix matches of KNOWN signature blocks are stripped — a
    hand-written closing that merely resembles one survives."""
    body = "Here is your answer.\n\nBest regards,\nGus from the office"
    out = apply_signature(db_session, body, PERSONAL_SIG)
    assert "Best regards,\nGus from the office" in out
    assert out.endswith(PERSONAL_SIG)


def test_apply_keeps_body_closing_and_single_signature(db_session):
    """New contract: the AI writes an editable closing line in the body. It is
    plain text (not a known signature block), so apply_signature keeps it and
    still appends exactly ONE signature — the name is not duplicated."""
    body = "Here is your answer.\n\nThanks so much,"
    out = apply_signature(db_session, body, PERSONAL_SIG)

    # Closing line survives verbatim in the body.
    assert "Here is your answer.\n\nThanks so much," in out
    # Exactly one signature appended; the signer's name appears once.
    assert out.endswith(PERSONAL_SIG)
    assert out.count("Gus") == 1
    # Re-applying is idempotent (no second signature).
    assert apply_signature(db_session, out, PERSONAL_SIG) == out


def test_apply_with_empty_signature_returns_body(db_session):
    ss.set_setting(db_session, ss.COMPANY_SIGNATURE, "")
    db_session.commit()
    out = apply_signature(db_session, "Body text.\n\n", "")
    assert out == "Body text."


# ===========================================================================
# 3. send_draft — sender's signature on the wire and in the thread
# ===========================================================================

def test_send_draft_appends_senders_personal_signature(
    logged_in_admin, admin_user, mock_email_provider, db_session
):
    admin_user.signature = PERSONAL_SIG
    db_session.commit()

    thread_id, draft_id, _ = _seed_thread_with_draft(
        draft_body="Dear client, here is your answer."
    )
    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 200, resp.text

    sent_body = mock_email_provider.sent_emails[-1]["body_text"]
    assert sent_body.endswith(PERSONAL_SIG)
    assert "Dear client, here is your answer." in sent_body


def test_send_draft_falls_back_to_company_signature(
    logged_in_admin, admin_user, mock_email_provider, db_session
):
    admin_user.signature = None
    db_session.commit()

    thread_id, draft_id, _ = _seed_thread_with_draft()
    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 200, resp.text

    assert mock_email_provider.sent_emails[-1]["body_text"].endswith(COMPANY_SIG)


def test_send_draft_strips_legacy_signature_from_old_drafts(
    logged_in_admin, admin_user, mock_email_provider, db_session
):
    """Transition: a draft generated pre-018 (legacy signature baked in) sends
    with the sender's signature instead — never both."""
    admin_user.signature = PERSONAL_SIG
    db_session.commit()

    thread_id, draft_id, _ = _seed_thread_with_draft(
        draft_body=f"Dear client, here is your answer.\n\n{LEGACY_SIG}"
    )
    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 200, resp.text

    sent_body = mock_email_provider.sent_emails[-1]["body_text"]
    assert sent_body.endswith(PERSONAL_SIG)
    assert "Jane M. Schilmoeller, CPA" not in sent_body


def test_send_draft_outbound_row_matches_what_was_sent(
    logged_in_admin, admin_user, mock_email_provider, db_session
):
    """The thread view renders the outbound EmailMessage — it must show the
    signed body, byte-identical to what the provider sent."""
    import uuid as _uuid
    from sqlalchemy import select
    from app.models.email import EmailMessage, MessageDirection

    admin_user.signature = PERSONAL_SIG
    db_session.commit()

    thread_id, draft_id, _ = _seed_thread_with_draft()
    resp = logged_in_admin.post(f"/api/v1/emails/{thread_id}/drafts/{draft_id}/send")
    assert resp.status_code == 200, resp.text

    outbound = db_session.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == _uuid.UUID(thread_id),
            EmailMessage.direction == MessageDirection.outbound,
        )
    ).scalar_one()
    assert outbound.body_text == mock_email_provider.sent_emails[-1]["body_text"]


# ===========================================================================
# 4. T1 auto-send — company signature, never a person's
# ===========================================================================

def test_auto_send_uses_company_signature(db_session, mock_email_provider):
    from tests.test_auto_send import (
        _add_inbound_message,
        _add_pending_draft,
        _enable_auto_send,
        _make_t1_thread,
    )
    from app.services.auto_send import maybe_auto_send

    _enable_auto_send(db_session)
    thread = _make_t1_thread(db_session)
    _add_inbound_message(db_session, thread)
    draft = _add_pending_draft(db_session, thread)
    db_session.commit()

    assert maybe_auto_send(db_session, thread_id=thread.id, draft_id=draft.id) is True

    sent_body = mock_email_provider.sent_emails[-1]["body_text"]
    assert sent_body.endswith(COMPANY_SIG)
    assert "Gus" not in sent_body


# ===========================================================================
# 5. /auth/me + PATCH /auth/me/signature
# ===========================================================================

def test_me_exposes_effective_signature_fallback(logged_in_admin, admin_user, db_session):
    admin_user.signature = None
    db_session.commit()

    me = logged_in_admin.get("/api/v1/auth/me").json()
    assert me["signature"] is None
    assert me["effective_signature"] == COMPANY_SIG


def test_patch_my_signature_roundtrip(logged_in_admin):
    resp = logged_in_admin.patch(
        "/api/v1/auth/me/signature", json={"signature": PERSONAL_SIG}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["signature"] == PERSONAL_SIG
    assert body["effective_signature"] == PERSONAL_SIG

    # Clearing falls back to the company block.
    resp = logged_in_admin.patch("/api/v1/auth/me/signature", json={"signature": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["signature"] is None
    assert body["effective_signature"] == COMPANY_SIG


def test_staff_can_set_their_own_signature(logged_in_staff):
    resp = logged_in_staff.patch(
        "/api/v1/auth/me/signature", json={"signature": "Cheers,\nStaffer"}
    )
    assert resp.status_code == 200
    assert resp.json()["effective_signature"] == "Cheers,\nStaffer"
