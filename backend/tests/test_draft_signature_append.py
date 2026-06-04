"""
Tests for signature handling in draft GENERATION (per-user signatures, 018).

History: pre-018, the global `draft_signature` was appended verbatim at
generation time. Since 018 the signature belongs to whoever SENDS — and the
sender is unknown while the background poller generates — so generation must
produce a signature-LESS body and the system prompt must always tell the
model to write no closing of its own. The send-time half (sender resolution,
company fallback, legacy strip) is covered in test_per_user_signatures.py.

These tests exercise the real generate() path with a mocked Anthropic client
(the test conftest pins LLM_PROVIDER=anthropic).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
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


def test_generation_never_appends_a_signature(db_session, mock_anthropic):
    """The generated body is exactly what the model wrote — no signature block
    is appended at generation time (the sender is unknown until send)."""
    llm_text = (
        "Dear Tony, thank you for reaching out — we'll review your situation and "
        "follow up shortly."
    )
    draft, _ = _run_generate(db_session, mock_anthropic, llm_text)

    assert draft.body_text == llm_text
    assert "Schilmoeller & Schoenfield" not in draft.body_text


def test_system_prompt_always_forbids_model_closings(db_session, mock_anthropic):
    """The no-closing rule is unconditional now — there is no branding branch."""
    _, system_prompt = _run_generate(
        db_session,
        mock_anthropic,
        "Dear Tony, thanks for reaching out — we'll follow up shortly.",
    )

    assert "Do NOT write any closing" in system_prompt
    assert "appended automatically when the email is sent" in system_prompt
    # The retired content-driven branding rule must be gone.
    assert "SIGN-OFF / BRANDING (decide from the conversation content)" not in system_prompt


def test_user_prompt_signoff_instruction_is_sender_neutral(db_session, mock_anthropic):
    """The per-draft instruction references 'the sender', not Jane — drafts can
    be sent by any staff member."""
    _run_generate(
        db_session,
        mock_anthropic,
        "Dear Tony, thanks for reaching out — we'll follow up shortly.",
    )
    user_prompt = "".join(
        str(m.get("content", ""))
        for m in (mock_anthropic.messages.create.call_args.kwargs.get("messages") or [])
    )
    assert "The sender's signature is appended" in user_prompt
