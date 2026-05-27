"""
Promotional category + draft-gating (FEAT/promotional-category).

Covers:
  - The automated-sender fast path classifies obvious bulk mail as promotional
    without an LLM call (saves AI credits); normal senders fall through.
  - `promotional` is a real prompt category so the LLM can pick it for
    content-based promo (e.g. recommendations@…).
  - Draft gating: promotional → no draft; T1 still drafts (shadow only gates
    auto-send); escalated / T3 / auto-generate-off → no draft.
"""
from app.models.email import CategorizationSource, EmailCategory, ThreadTier
from app.services.categorizer import (
    CATEGORY_DESCRIPTIONS,
    _automated_sender_result,
    _calendar_invite_result,
)
from app.services.email_intake import _should_generate_draft


# ── automated-sender heuristic ────────────────────────────────────────────────

def test_automated_senders_classified_promotional_without_llm():
    for sender in [
        "LinkedIn <notifications-noreply@linkedin.com>",
        "no-reply@example.com",
        "Acme Marketing <marketing@acme.com>",
        "newsletter@brand.io",
        "donotreply@bank.com",
        "Mailer Daemon <mailer-daemon@mail.com>",
    ]:
        res = _automated_sender_result(sender)
        assert res is not None, f"expected promotional for {sender!r}"
        assert res.category == EmailCategory.promotional
        assert res.escalation_needed is False
        assert res.source == CategorizationSource.rules_fallback


def test_normal_senders_fall_through_to_llm():
    # These must NOT be caught by the heuristic — they go to the LLM (which has
    # the promotional category available for content-based promo like Pinterest).
    for sender in [
        "Sara Murphy <sara@pointprofit.com>",
        "recommendations@discover.pinterest.com",
        "john.doe@gmail.com",
        "Jane <jane@schilcpa.com>",
    ]:
        assert _automated_sender_result(sender) is None, f"{sender!r} should fall through"


def test_promotional_is_a_prompt_category():
    assert EmailCategory.promotional in CATEGORY_DESCRIPTIONS


# ── calendar-invite heuristic (false-positive fix) ────────────────────────────

def test_calendar_invites_classified_appointment_without_llm():
    for subject in [
        "Invitation: Coaching Group Call @ Tue Jun 3",
        "Updated invitation: [Prime Inner Circle] Coaching",
        "Canceled event: Quarterly review",
        "Accepted: Tax planning call",
        "Re: Updated invitation: Strategy session",
    ]:
        res = _calendar_invite_result(subject)
        assert res is not None, f"expected appointment for {subject!r}"
        assert res.category == EmailCategory.appointment
        assert res.escalation_needed is False
        assert res.source == CategorizationSource.rules_fallback


def test_non_invites_fall_through_calendar_heuristic():
    for subject in [
        "Account Renewal Confirmation",
        "Schilmoeller & Schoenfield, PC - Renewal Proposal",
        "Quick question about my return",
        "Your invoice is ready",  # not an invitation despite 'invo...'
    ]:
        assert _calendar_invite_result(subject) is None, f"{subject!r} should fall through"


def test_calendar_invite_routes_to_appointment_before_promotional(mock_anthropic):
    """An invite from a notification address must become appointment (not
    promotional via the automated-sender heuristic) and must not hit the LLM."""
    from app.services.categorizer import get_categorizer

    svc = get_categorizer()
    result = svc.categorize(
        sender="calendar-notification@google.com",
        subject="Updated invitation: Coaching Group Call @ Tue",
        body="This event has been updated.",
    )
    assert result.category == EmailCategory.appointment
    mock_anthropic.messages.create.assert_not_called()


def test_promotional_description_has_carveouts():
    desc = CATEGORY_DESCRIPTIONS[EmailCategory.promotional]
    # Calendar invitations and named-human proposals are explicitly NOT promotional.
    assert "calendar" in desc.lower() and "appointment" in desc.lower()
    assert "proposal" in desc.lower()


# ── draft gating ──────────────────────────────────────────────────────────────

def test_promotional_threads_get_no_draft():
    assert (
        _should_generate_draft(
            escalated=False,
            tier=ThreadTier.t2_review,
            category=EmailCategory.promotional,
            draft_auto_generate=True,
        )
        is False
    )


def test_t1_threads_get_a_draft_even_in_shadow_mode():
    # The helper has no shadow_mode input on purpose — drafts always generate
    # for review; auto-send is gated separately. A T1 thread gets a draft.
    assert (
        _should_generate_draft(
            escalated=False,
            tier=ThreadTier.t1_auto,
            category=EmailCategory.general_inquiry,
            draft_auto_generate=True,
        )
        is True
    )


def test_escalated_t3_and_disabled_get_no_draft():
    assert not _should_generate_draft(
        escalated=True, tier=ThreadTier.t2_review,
        category=EmailCategory.general_inquiry, draft_auto_generate=True,
    )
    assert not _should_generate_draft(
        escalated=False, tier=ThreadTier.t3_escalate,
        category=EmailCategory.general_inquiry, draft_auto_generate=True,
    )
    assert not _should_generate_draft(
        escalated=False, tier=ThreadTier.t2_review,
        category=EmailCategory.general_inquiry, draft_auto_generate=False,
    )
