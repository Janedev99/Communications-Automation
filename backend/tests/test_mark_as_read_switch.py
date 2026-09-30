"""
MARK_AS_READ switch (FIX/mark-as-read-switch, 2026-09-30).

The firm's server copy and PRIME's Railway test copy both poll Jane's real
mailbox, and each fetches only UNREAD Inbox mail. Marking a message read after
ingest meant whichever copy polled first hid that email from the other, so a
test copy could keep mail from reaching the app Jane actually uses.
`MARK_AS_READ=false` lets a test copy read the mailbox without changing it.
The default stays True so the firm's copy behaves exactly as before.
"""
from __future__ import annotations

import app.services.email_intake as ei
from app.config import Settings
from tests.conftest import make_raw_email


def _one_email_poll(mock_email_provider, monkeypatch) -> list[str]:
    marked: list[str] = []
    raw = make_raw_email(message_id="<switch-test@example.com>")
    monkeypatch.setattr(mock_email_provider, "fetch_new_emails", lambda: [raw])
    monkeypatch.setattr(mock_email_provider, "mark_as_read", lambda mid: marked.append(mid))
    monkeypatch.setattr(ei, "process_single_email", lambda db, r: None)
    ei.poll_once()
    return marked


def test_default_is_to_mark_as_read():
    assert Settings.model_fields["mark_as_read"].default is True


def test_marks_as_read_when_switch_on(mock_email_provider, monkeypatch):
    monkeypatch.setattr(ei.settings, "mark_as_read", True)
    assert _one_email_poll(mock_email_provider, monkeypatch) == ["<switch-test@example.com>"]


def test_leaves_mail_unread_when_switch_off(mock_email_provider, monkeypatch):
    monkeypatch.setattr(ei.settings, "mark_as_read", False)
    assert _one_email_poll(mock_email_provider, monkeypatch) == []
