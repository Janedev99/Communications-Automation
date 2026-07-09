"""
Tests for POST /api/v1/emails/compose/draft — the AI "write this email for me"
path of the Compose flow.

The endpoint asks the LLM to write a brand-new outbound email from a free-text
instruction and returns an editable {subject, body}. Nothing is sent or
persisted — the user reviews/edits, then sends via /compose.

We drive the mocked Anthropic client (the test env pins LLM_PROVIDER=anthropic)
and rebuild the draft-generator singleton so the freshly-mocked client is used,
mirroring the established pattern in test_draft_signature_append.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock

DRAFT_URL = "/api/v1/emails/compose/draft"


def _arm_llm(mock_anthropic, text: str) -> None:
    """Point the mocked LLM at a canned completion and rebuild the singletons."""
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=text)],
        usage=MagicMock(input_tokens=120, output_tokens=80),
    )
    from app.services import llm_client as _llm_module
    _llm_module.reset_llm_client()
    from app.services import draft_generator as _draft_module
    _draft_module._draft_generator = None


def test_compose_draft_returns_subject_and_body(logged_in_admin, mock_anthropic):
    _arm_llm(
        mock_anthropic,
        '{"subject": "Your 2024 1099s", "body": "Hi Sam, could you send over your '
        '2024 1099 forms by Friday so we can finalize your return?"}',
    )
    resp = logged_in_admin.post(
        DRAFT_URL,
        json={
            "instruction": "Ask Sam to send his 2024 1099s by Friday.",
            "recipient": "sam@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subject"] == "Your 2024 1099s"
    assert "1099" in data["body"]
    # The signature is NOT baked into the AI body — /compose appends it at send.
    assert "Schilmoeller" not in data["body"]


def test_compose_draft_tolerates_non_json_output(logged_in_admin, mock_anthropic):
    # If the model ignores the JSON instruction, the whole text becomes the body
    # and we fall back to the supplied subject hint.
    _arm_llm(mock_anthropic, "Hi Sam, just checking in on your documents.")
    resp = logged_in_admin.post(
        DRAFT_URL,
        json={
            "instruction": "Check in with Sam.",
            "subject_hint": "Checking in",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subject"] == "Checking in"
    assert data["body"] == "Hi Sam, just checking in on your documents."


def test_compose_draft_strips_code_fences(logged_in_admin, mock_anthropic):
    _arm_llm(
        mock_anthropic,
        '```json\n{"subject": "Reminder", "body": "Your payment is due Monday."}\n```',
    )
    resp = logged_in_admin.post(
        DRAFT_URL, json={"instruction": "Remind them payment is due Monday."}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subject"] == "Reminder"
    assert data["body"] == "Your payment is due Monday."


def test_compose_draft_requires_instruction(logged_in_admin, mock_anthropic):
    resp = logged_in_admin.post(DRAFT_URL, json={"instruction": "   "})
    # Pydantic min_length=1 rejects whitespace-only? No — whitespace passes
    # min_length, so the generator raises ValueError → 409. Either way it must
    # not be a 200.
    assert resp.status_code in (409, 422), resp.text


def test_compose_draft_requires_auth(client, mock_anthropic):
    resp = client.post(DRAFT_URL, json={"instruction": "Write something."})
    assert resp.status_code in (401, 403), resp.text


def test_compose_prompt_instructs_a_closing(logged_in_admin, mock_anthropic):
    """Compose drafts now end with an editable tone-appropriate closing line,
    still without a name/title/signature (appended at send)."""
    _arm_llm(mock_anthropic, '{"subject": "Hi", "body": "Hi Sam, quick note."}')
    resp = logged_in_admin.post(
        DRAFT_URL,
        json={"instruction": "Send Sam a quick note.", "recipient": "sam@example.com"},
    )
    assert resp.status_code == 200, resp.text

    system_prompt = mock_anthropic.messages.create.call_args.kwargs["system"]
    assert "closing line" in system_prompt
    assert "Do NOT write a name, title, or signature" in system_prompt
    assert "Do NOT write any closing" not in system_prompt
