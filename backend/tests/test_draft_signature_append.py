"""
Tests for deterministic signature handling in draft generation.

Regression context: when Jane configured a signature, some drafts "didn't use
it" — the system prompt's content-driven SIGN-OFF/BRANDING rule competed with
(and sometimes won over) the user-prompt instruction to use the configured
signature, and even when it didn't, the LLM wouldn't reliably reproduce a
multi-line contact block verbatim.

The fix makes code, not the prompt, own the closing when a signature is set:
  - the system prompt is told to write NO closing of its own (branding rule
    suppressed),
  - the configured signature is appended verbatim after generation,
  - a `not in` guard prevents a double signature if the model echoes it.

These tests exercise the real generate() path with a mocked Anthropic client
(the test conftest pins LLM_PROVIDER=anthropic).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
)
from app.services import system_settings as ss


@pytest.fixture(autouse=True)
def _isolate_signature(db_session):
    """The conftest DB shares one in-memory connection with no per-test rollback,
    so a committed signature would leak across tests. Reset DRAFT_SIGNATURE to
    empty (falsy → branding path) before and after each test for order-independent
    isolation, and so this module can't taint draft-generation tests elsewhere.
    """
    ss.set_setting(db_session, ss.DRAFT_SIGNATURE, "")
    db_session.commit()
    yield
    ss.set_setting(db_session, ss.DRAFT_SIGNATURE, "")
    db_session.commit()

# A realistic multi-line signature (the shape an LLM mangles): salutation, name,
# title, firm, and a contact block with punctuation/spacing the model loves to
# "tidy up".
SIG = (
    "Thanks so much,\n\n"
    "Jane\n\n"
    "Jane M. Schilmoeller, CPA\n"
    "Business Growth and Profitability Advisor\n\n"
    "Schilmoeller & Schoenfield, PC\n"
    "Office:  (713) 527-9281 Ext 1"
)


def _build_thread(db):
    thread = EmailThread(
        id=uuid.uuid4(),
        client_email="tony@ferreiralaw.com",
        client_name="Tony Ferreira",
        subject="Quick question",
        category=EmailCategory.general_inquiry,
        status=EmailStatus.categorized,
        ai_summary="Client has a question about next steps.",
        suggested_reply_tone="professional",
    )
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        direction=MessageDirection.inbound,
        sender="tony@ferreiralaw.com",
        recipient="jane@schilcpa.com",
        body_text="Hi Jane, just wondering about the next steps?",
        message_id_header=f"<{uuid.uuid4().hex}@test>",
        received_at=datetime.now(timezone.utc),
    )
    db.add_all([thread, msg])
    db.commit()
    return thread


def _run_generate(db, mock_anthropic, llm_text):
    """Drive generate() with a canned LLM body and return (draft, system_prompt)."""
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=llm_text)],
        usage=MagicMock(input_tokens=200, output_tokens=60),
    )
    # Rebuild the LLM + generator singletons so the freshly-mocked client is used.
    from app.services import llm_client as _llm_module
    _llm_module.reset_llm_client()
    from app.services import draft_generator as _draft_module
    _draft_module._draft_generator = None

    thread = _build_thread(db)
    from app.services.draft_generator import get_draft_generator
    draft = get_draft_generator().generate(db, thread)
    db.commit()

    system_prompt = mock_anthropic.messages.create.call_args.kwargs["system"]
    return draft, system_prompt


def test_signature_appended_when_model_omits_it(db_session, mock_anthropic):
    """With a signature configured, the draft ends with it verbatim even when the
    model writes its own (different) sign-off and omits the signature."""
    ss.set_setting(db_session, ss.DRAFT_SIGNATURE, SIG)
    db_session.commit()

    draft, system_prompt = _run_generate(
        db_session,
        mock_anthropic,
        "Dear Tony, thank you for reaching out — we'll review your situation and "
        "follow up shortly. Best regards, Schiller CPA team.",
    )

    # Signature present, verbatim, exactly once, at the end.
    assert draft.body_text.rstrip().endswith(SIG)
    assert draft.body_text.count("Jane M. Schilmoeller, CPA") == 1
    assert "Office:  (713) 527-9281 Ext 1" in draft.body_text

    # System prompt suppressed the competing branding rule and told the model to
    # write no closing of its own.
    assert "Do NOT write any closing" in system_prompt
    assert "SIGN-OFF / BRANDING (decide from the conversation content)" not in system_prompt


def test_signature_not_duplicated_when_model_echoes_it(db_session, mock_anthropic):
    """If the model already ended with the exact signature, we don't append a
    second copy."""
    ss.set_setting(db_session, ss.DRAFT_SIGNATURE, SIG)
    db_session.commit()

    draft, _ = _run_generate(
        db_session,
        mock_anthropic,
        f"Dear Tony, happy to help — we'll be in touch soon.\n\n{SIG}",
    )

    assert draft.body_text.count("Jane M. Schilmoeller, CPA") == 1
    assert draft.body_text.rstrip().endswith(SIG)


def test_no_signature_keeps_branding_rule_and_does_not_append(db_session, mock_anthropic):
    """With no signature configured, the branding rule stays in the system prompt
    and nothing is appended to the model's output."""
    # No draft_signature row in the test DB → branding path.
    draft, system_prompt = _run_generate(
        db_session,
        mock_anthropic,
        "Dear Tony, thanks for reaching out — we'll follow up shortly. "
        "Best regards, Jane.",
    )

    # Branding rule present; no append happened.
    assert "SIGN-OFF / BRANDING (decide from the conversation content)" in system_prompt
    assert "Point Profit" in system_prompt
    assert "Jane M. Schilmoeller, CPA" not in draft.body_text
    assert "Dear Tony" in draft.body_text
