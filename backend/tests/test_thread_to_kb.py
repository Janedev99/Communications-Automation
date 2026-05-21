"""
Tests for POST /api/v1/emails/{thread_id}/add-to-knowledge-base.

Covers (from the 2026-05-21 client meeting):
  - Default title strips Re:/Fwd:/FW: prefixes
  - Default content is a Q&A block from latest inbound + outbound
  - Override title / category / tags via the request body
  - Audit row uses the distinct `knowledge.created_from_thread` action
  - 404 for missing thread
  - Threads with no outbound surface just the question (still useful)
  - Threads with no inbound (unusual) don't crash
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.email import (
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    KnowledgeEntry,
    MessageDirection,
)


def _make_thread(
    db: Session,
    *,
    subject: str = "Q3 audit findings",
    category: EmailCategory = EmailCategory.document_request,
) -> EmailThread:
    thread = EmailThread(
        id=uuid.uuid4(),
        subject=subject,
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name="Test Client",
        status=EmailStatus.sent,
        category=category,
    )
    db.add(thread)
    db.flush()
    return thread


def _add_message(
    db: Session,
    thread: EmailThread,
    *,
    direction: MessageDirection,
    body_text: str,
    received_at: datetime,
    sender: str = "client@example.com",
) -> EmailMessage:
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        message_id_header=f"<{uuid.uuid4()}@test>",
        sender=sender,
        recipient="firm@example.com",
        body_text=body_text,
        received_at=received_at,
        direction=direction,
        is_processed=True,
    )
    db.add(msg)
    db.flush()
    return msg


# ── Happy path ────────────────────────────────────────────────────────────────


def test_default_title_strips_reply_prefix(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session, subject="Re: Re: FW: Q3 audit findings")
    now = datetime.now(timezone.utc)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="What are the findings?", received_at=now - timedelta(hours=2))
    _add_message(db_session, thread, direction=MessageDirection.outbound,
                 body_text="The findings are X, Y, Z.", received_at=now - timedelta(hours=1))
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/add-to-knowledge-base", json={})

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Q3 audit findings"


def test_default_content_is_qa_block(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session)
    now = datetime.now(timezone.utc)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 sender="caroline@apex.com",
                 body_text="Can you send the K-1s?", received_at=now - timedelta(hours=2))
    _add_message(db_session, thread, direction=MessageDirection.outbound,
                 body_text="Attached — let me know if anything's unclear.",
                 received_at=now - timedelta(hours=1))
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/add-to-knowledge-base", json={})

    assert response.status_code == 201
    content = response.json()["content"]
    assert "Question" in content
    assert "caroline@apex.com" in content
    assert "Can you send the K-1s?" in content
    assert "Our response" in content
    assert "Attached — let me know" in content


def test_default_category_and_tags_come_from_thread(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session, category=EmailCategory.appointment)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="Q?", received_at=datetime.now(timezone.utc))
    _add_message(db_session, thread, direction=MessageDirection.outbound,
                 body_text="A.", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/add-to-knowledge-base", json={})

    assert response.status_code == 201
    payload = response.json()
    assert payload["category"] == "appointment"
    assert "from_email" in payload["tags"]
    assert "appointment" in payload["tags"]


def test_uses_latest_message_when_thread_has_multiple_exchanges(
    logged_in_admin, db_session, mock_email_provider
):
    """The KB entry should represent the most recent Q&A — not the
    first one. Multi-turn threads accumulate context; the final round
    is what represents the "settled answer" most usefully."""
    thread = _make_thread(db_session)
    now = datetime.now(timezone.utc)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="EARLY question", received_at=now - timedelta(days=2))
    _add_message(db_session, thread, direction=MessageDirection.outbound,
                 body_text="EARLY answer", received_at=now - timedelta(days=1, hours=23))
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="LATER follow-up", received_at=now - timedelta(hours=2))
    _add_message(db_session, thread, direction=MessageDirection.outbound,
                 body_text="LATER clarification", received_at=now - timedelta(hours=1))
    db_session.commit()

    response = logged_in_admin.post(f"/api/v1/emails/{thread.id}/add-to-knowledge-base", json={})

    assert response.status_code == 201
    content = response.json()["content"]
    assert "LATER follow-up" in content
    assert "LATER clarification" in content
    assert "EARLY question" not in content
    assert "EARLY answer" not in content


# ── Overrides ─────────────────────────────────────────────────────────────────


def test_title_override(logged_in_admin, db_session, mock_email_provider):
    thread = _make_thread(db_session, subject="Generic subject")
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="?", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/add-to-knowledge-base",
        json={"title": "Cleaner custom title"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Cleaner custom title"


def test_category_override(logged_in_admin, db_session, mock_email_provider):
    thread = _make_thread(db_session, category=EmailCategory.general_inquiry)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="?", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/add-to-knowledge-base",
        json={"category": "policy_template"},
    )

    assert response.status_code == 201
    assert response.json()["category"] == "policy_template"


def test_tags_override(logged_in_admin, db_session, mock_email_provider):
    thread = _make_thread(db_session, category=EmailCategory.urgent)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="?", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/add-to-knowledge-base",
        json={"tags": ["custom_tag", "another_tag"]},
    )

    assert response.status_code == 201
    tags = response.json()["tags"]
    assert tags == ["custom_tag", "another_tag"]
    # Defaults should NOT leak in when the user supplied an explicit list
    assert "from_email" not in tags


# ── Audit + DB persistence ────────────────────────────────────────────────────


def test_writes_distinct_audit_action(logged_in_admin, db_session, mock_email_provider):
    """The audit log distinguishes thread-derived KB entries from
    hand-authored ones via the action name — useful for reporting on
    "how often does this flow get used"."""
    thread = _make_thread(db_session)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="Question.", received_at=datetime.now(timezone.utc))
    _add_message(db_session, thread, direction=MessageDirection.outbound,
                 body_text="Answer.", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/add-to-knowledge-base",
        json={"title": "Custom"},
    )
    entry_id = response.json()["id"]

    db_session.expire_all()
    audit = db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "knowledge.created_from_thread",
            AuditLog.entity_id == entry_id,
        )
    ).scalar_one()
    assert audit.details["thread_id"] == str(thread.id)
    assert audit.details["title_was_overridden"] is True
    assert audit.details["category_was_overridden"] is False


def test_creates_persisted_kb_row(
    logged_in_admin, db_session, mock_email_provider
):
    thread = _make_thread(db_session)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="Q?", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/add-to-knowledge-base", json={}
    )
    entry_id = uuid.UUID(response.json()["id"])

    db_session.expire_all()
    row = db_session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
    ).scalar_one()
    assert row.is_active is True
    assert row.entry_type == "snippet"
    assert row.usage_count == 0


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_404_when_thread_missing(logged_in_admin, db_session, mock_email_provider):
    response = logged_in_admin.post(
        f"/api/v1/emails/{uuid.uuid4()}/add-to-knowledge-base", json={}
    )
    assert response.status_code == 404


def test_thread_with_no_outbound_still_succeeds(
    logged_in_admin, db_session, mock_email_provider
):
    """A thread that's been received but not yet replied to can still
    seed a KB entry — useful as "this is the kind of question we get"
    even before the firm has settled on a canonical answer."""
    thread = _make_thread(db_session)
    _add_message(db_session, thread, direction=MessageDirection.inbound,
                 body_text="Inbound only", received_at=datetime.now(timezone.utc))
    db_session.commit()

    response = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/add-to-knowledge-base", json={}
    )

    assert response.status_code == 201
    content = response.json()["content"]
    assert "Inbound only" in content
    assert "Our response" not in content
