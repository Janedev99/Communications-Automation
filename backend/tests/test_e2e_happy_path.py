"""
End-to-end happy path test.

Exercises the full workflow from login → email intake → categorization →
draft generation → draft approval → send, using:
  - A real FastAPI TestClient (no mocked HTTP layer)
  - A mocked Anthropic SDK (no real Claude calls)
  - A RecordingEmailProvider (no real email sending)
  - The shared SQLite in-memory test database
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ===========================================================================
# E2E happy path
# ===========================================================================

def test_login_to_send_happy_path(mock_email_provider):
    """
    Full workflow:
      1. Seed an admin user
      2. Login → get session + CSRF cookies
      3. Directly call process_single_email to simulate polling
      4. GET /api/v1/emails → thread appears in list
      5. POST /api/v1/emails/{id}/generate-draft → draft created
      6. PUT /api/v1/emails/{thread_id}/drafts/{draft_id} → edit body
      7. POST .../approve → draft approved
      8. POST .../send → success, provider called once

    All Claude calls are mocked.
    """
    import app.database as _db_mod
    from app.main import create_app
    from app.database import get_db as _original_get_db
    from app.models.user import User, UserRole
    from app.services.auth import create_user, create_session, generate_csrf_token
    from sqlalchemy import select
    from tests.conftest import _TestSession, make_raw_email

    # ── Seed admin user ──────────────────────────────────────────────────────
    suffix = str(uuid.uuid4())[:8]
    admin_email = f"e2e-admin-{suffix}@example.com"
    admin_password = "E2EPass123!"

    db = _TestSession()
    try:
        admin = create_user(
            db,
            email=admin_email,
            name="E2E Admin",
            password=admin_password,
            role=UserRole.admin,
        )
        db.commit()
        admin_id = admin.id
    finally:
        db.close()

    # ── Build app with test DB override ─────────────────────────────────────
    _app = create_app()

    def _get_test_db():
        session = _TestSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    _app.dependency_overrides[_original_get_db] = _get_test_db
    tc = TestClient(_app, raise_server_exceptions=True)

    # ── Step 1: Login ────────────────────────────────────────────────────────
    login_resp = tc.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": admin_password},
    )
    assert login_resp.status_code == 200, login_resp.text
    session_token = login_resp.cookies["session_token"]
    csrf_token = login_resp.cookies["csrf_token"]

    tc.cookies.set("session_token", session_token)
    tc.cookies.set("csrf_token", csrf_token)
    tc.headers.update({"X-CSRF-Token": csrf_token})

    # ── Step 2: Seed an inbound email via process_single_email ───────────────
    inbound_mid = f"<e2e-{uuid.uuid4()}@example.com>"
    raw = make_raw_email(
        message_id=inbound_mid,
        subject="Question about my tax return",
        sender=f"e2e-client-{uuid.uuid4()}@gmail.com",
        body_text="Hi, I wanted to ask about the status of my 2023 return.",
    )

    from app.models.email import EmailCategory
    from app.schemas.email import CategorizationResult

    canned_cat = CategorizationResult(
        category=EmailCategory.status_update,
        confidence=0.92,
        escalation_needed=False,
        escalation_reasons=[],
        summary="Client is asking about the status of their 2023 tax return.",
        suggested_reply_tone="professional",
    )
    mock_cat = MagicMock()
    mock_cat.categorize.return_value = canned_cat

    db = _TestSession()
    try:
        with patch("app.services.email_intake.get_categorizer", return_value=mock_cat), \
             patch("app.services.email_intake.get_escalation_engine") as mock_esc_fac:
            mock_engine = MagicMock()
            mock_engine.process.return_value = None
            mock_esc_fac.return_value = mock_engine

            from app.services.email_intake import process_single_email
            thread_id = process_single_email(db, raw)
        db.commit()
    finally:
        db.close()

    assert thread_id is None  # draft_auto_generate=false in test env → returns None

    # Retrieve actual thread ID from DB
    db = _TestSession()
    try:
        from app.models.email import EmailMessage, EmailThread
        msg = db.execute(
            select(EmailMessage).where(EmailMessage.message_id_header == inbound_mid)
        ).scalar_one()
        actual_thread_id = str(msg.thread_id)
    finally:
        db.close()

    # ── Step 3: GET /emails → thread appears ─────────────────────────────────
    list_resp = tc.get("/api/v1/emails")
    assert list_resp.status_code == 200
    data = list_resp.json()
    thread_ids = [t["id"] for t in data.get("items", [])]
    assert actual_thread_id in thread_ids, (
        f"Thread {actual_thread_id} not found in email list"
    )

    # ── Step 4: POST generate-draft (mock Claude draft response) ─────────────
    draft_body = "Dear client, thank you for your inquiry about your 2023 return. We will review your file and follow up shortly.\n\nBest regards,\nSchiller CPA"

    mock_draft_response = MagicMock()
    mock_draft_response.content = [MagicMock(text=draft_body)]
    mock_draft_response.usage = MagicMock(input_tokens=200, output_tokens=80)
    mock_draft_response.model = "claude-sonnet-4-5"

    # Patch target moved when the LLM provider abstraction landed: the SDK
    # is imported lazily by AnthropicLLMClient inside llm_client.py, not by
    # draft_generator any more. Mocking anthropic.Anthropic globally still
    # gives us full control of `messages.create`.
    with patch("anthropic.Anthropic") as mock_anthro_cls, \
         patch("app.services.draft_generator.get_knowledge_service") as mock_ks, \
         patch("app.services.draft_generator.get_notification_service") as mock_ns, \
         patch("app.utils.rate_limit.check_ai_rate_limit"), \
         patch("app.utils.rate_limit.record_ai_call"):
        mock_client = MagicMock()
        mock_anthro_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_draft_response
        mock_ks.return_value = MagicMock()
        mock_ks.return_value.get_entries_for_thread.return_value = []
        mock_ns.return_value = MagicMock()

        # Clear both singletons so they rebuild against the patched SDK.
        import app.services.draft_generator as _dg_module
        from app.services import llm_client as _llm_module
        original_gen = _dg_module._draft_generator
        _dg_module._draft_generator = None
        _llm_module.reset_llm_client()

        gen_resp = tc.post(f"/api/v1/emails/{actual_thread_id}/generate-draft")

        _dg_module._draft_generator = original_gen
        _llm_module.reset_llm_client()

    assert gen_resp.status_code == 201, gen_resp.text
    draft = gen_resp.json()
    draft_id = draft["id"]
    assert draft["status"] == "pending"

    # ── Step 5: PUT edit draft body ───────────────────────────────────────────
    edited_body = draft_body + "\n\nEdited by staff."
    edit_resp = tc.put(
        f"/api/v1/emails/{actual_thread_id}/drafts/{draft_id}",
        json={"body_text": edited_body},
    )
    assert edit_resp.status_code == 200, edit_resp.text

    # ── Step 6: POST approve ──────────────────────────────────────────────────
    approve_resp = tc.post(
        f"/api/v1/emails/{actual_thread_id}/drafts/{draft_id}/approve"
    )
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["status"] == "approved"

    # ── Step 7: POST send ─────────────────────────────────────────────────────
    send_resp = tc.post(
        f"/api/v1/emails/{actual_thread_id}/drafts/{draft_id}/send"
    )
    assert send_resp.status_code == 200, send_resp.text
    assert send_resp.json()["status"] == "sent"

    # Provider was called exactly once
    assert len(mock_email_provider.sent_emails) == 1, (
        "Email provider must be called exactly once"
    )
    sent = mock_email_provider.sent_emails[0]
    assert "Question about my tax return" in sent["subject"]

    # ── Step 8: Thread status is 'sent' ──────────────────────────────────────
    thread_resp = tc.get(f"/api/v1/emails/{actual_thread_id}")
    assert thread_resp.status_code == 200
    assert thread_resp.json()["status"] == "sent"
