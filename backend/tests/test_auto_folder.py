"""
Tests for app.services.auto_folder — the post-send "save to a client
folder" hook called from both the manual send path (drafts.py) and the
T1 auto-send path (services/auto_send.py).

Behavioural contract (from the 2026-05-21 client meeting):
  - Runs only after a SUCCESSFUL send.
  - Folder name resolves: client_name → client_email → "Unsorted".
  - Idempotent over `is_saved` — does NOT override an existing save,
    whether user-chosen or from a prior auto-save.
  - Writes a `thread.auto_saved` audit row when a save happens.
  - Errors are swallowed (logged + returned as False) — must never
    poison the send transaction it rides alongside.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.email import EmailCategory, EmailStatus, EmailThread
from app.services.auto_folder import (
    _resolve_client_folder_name,
    auto_save_to_client_folder,
)


def _make_thread(
    db: Session,
    *,
    client_name: str | None = "Test Client",
    client_email: str | None = None,
    is_saved: bool = False,
    saved_folder: str | None = None,
) -> EmailThread:
    thread = EmailThread(
        id=uuid.uuid4(),
        subject=f"AutoFolder {uuid.uuid4().hex[:6]}",
        client_email=client_email or f"client-{uuid.uuid4().hex[:6]}@example.com",
        client_name=client_name,
        status=EmailStatus.categorized,
        category=EmailCategory.general_inquiry,
        is_saved=is_saved,
        saved_folder=saved_folder,
    )
    db.add(thread)
    db.flush()
    return thread


# ── Folder-name resolution ────────────────────────────────────────────────────


def test_resolve_prefers_client_name(db_session: Session):
    thread = _make_thread(db_session, client_name="Caroline Apex",
                          client_email="caroline@apex.com")
    assert _resolve_client_folder_name(thread) == "Caroline Apex"


def test_resolve_falls_back_to_email_when_name_missing(db_session: Session):
    thread = _make_thread(db_session, client_name=None,
                          client_email="doug@conquest.com")
    assert _resolve_client_folder_name(thread) == "doug@conquest.com"


def test_resolve_falls_back_to_email_when_name_blank(db_session: Session):
    thread = _make_thread(db_session, client_name="   ",
                          client_email="someone@example.com")
    assert _resolve_client_folder_name(thread) == "someone@example.com"


def test_resolve_falls_back_to_unsorted_when_all_empty(db_session: Session):
    thread = _make_thread(db_session, client_name=None, client_email="")
    # Manually clear the email since the factory always provides one
    thread.client_email = ""
    assert _resolve_client_folder_name(thread) == "Unsorted"


# ── auto_save_to_client_folder ───────────────────────────────────────────────


def test_auto_save_files_unsaved_thread_to_client_folder(
    db_session: Session, admin_user
):
    thread = _make_thread(db_session, client_name="Jenna Pike")
    db_session.flush()

    saved = auto_save_to_client_folder(
        db_session,
        thread=thread,
        actor_id=admin_user.id,
        request_ip="1.2.3.4",
    )

    assert saved is True
    assert thread.is_saved is True
    assert thread.saved_folder == "Jenna Pike"
    assert thread.saved_at is not None
    assert thread.saved_by_id == admin_user.id


def test_auto_save_writes_audit_row(db_session: Session, admin_user):
    thread = _make_thread(db_session, client_name="Marcus Lee")
    db_session.flush()

    auto_save_to_client_folder(
        db_session,
        thread=thread,
        actor_id=admin_user.id,
        request_ip="1.2.3.4",
    )

    audit = db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == str(thread.id),
            AuditLog.action == "thread.auto_saved",
        )
    ).scalar_one()
    assert audit.details["folder"] == "Marcus Lee"
    assert audit.details["trigger"] == "send"
    assert audit.user_id == admin_user.id


def test_auto_save_respects_existing_save(db_session: Session, admin_user):
    """Never override a thread that's already saved — the user (or a
    prior auto-save) made a choice and we shouldn't silently re-file it."""
    thread = _make_thread(
        db_session,
        client_name="Bridget Tao",
        is_saved=True,
        saved_folder="Q3 Audits",  # user-chosen folder
    )
    db_session.flush()

    saved = auto_save_to_client_folder(
        db_session,
        thread=thread,
        actor_id=admin_user.id,
        request_ip="1.2.3.4",
    )

    assert saved is False
    assert thread.saved_folder == "Q3 Audits", (
        "User-chosen folder must survive an auto-save attempt"
    )


def test_auto_save_works_with_no_actor(db_session: Session):
    """T1 auto-send has no human actor — auto_save must accept None
    for actor_id and persist the row without a saved_by_id."""
    thread = _make_thread(db_session, client_name="Auto-sent Client")
    db_session.flush()

    saved = auto_save_to_client_folder(
        db_session,
        thread=thread,
        actor_id=None,
        request_ip=None,
    )

    assert saved is True
    assert thread.saved_by_id is None
    assert thread.is_saved is True
    assert thread.saved_folder == "Auto-sent Client"


def test_auto_save_returns_false_and_swallows_on_error(
    db_session: Session, admin_user, mocker
):
    """A save-side exception must never poison the send transaction.
    The function logs and returns False instead of propagating."""
    thread = _make_thread(db_session, client_name="Risky Client")
    db_session.flush()

    # Force log_action to blow up — simulates an audit row insert failure.
    mocker.patch(
        "app.services.auto_folder.log_action",
        side_effect=RuntimeError("audit write failed"),
    )

    # Must not raise.
    saved = auto_save_to_client_folder(
        db_session,
        thread=thread,
        actor_id=admin_user.id,
        request_ip="1.2.3.4",
    )

    assert saved is False
