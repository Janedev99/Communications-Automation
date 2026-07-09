"""Read-only mailbox structure endpoints (Iteration A of folder routing).

GET /mailbox/folders?parent=<id>&custom=<bool>  — one level of Outlook folders.

`custom=true` hides Outlook's built-in system folders and surfaces Jane's own
folders instead: at the top level it drops the well-known defaults and promotes
Inbox's children (where her per-client folders live), so the app shows the
folder tree she actually created. Read-only: this module never creates, moves,
or deletes a folder. A short in-process TTL cache (per parent+mode) avoids
re-hitting Graph on repeated expands.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.user import User
from app.services.email_provider import get_email_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mailbox", tags=["mailbox"])

_CACHE_TTL_SECONDS = 120
# cache key ("<mode>:<parent>") -> (expires_at_monotonic, folders)
_FOLDER_CACHE: dict[str, tuple[float, list[dict]]] = {}

# Outlook's built-in system folders (lowercased displayNames). Excluded from
# `custom=true` so only Jane's own folders show. Both "Junk Email" spellings
# appear on real mailboxes.
_DEFAULT_FOLDER_NAMES = {
    "archive", "conversation history", "deleted items", "drafts", "inbox",
    "junk email", "junk e-mail", "notes", "outbox", "rss feeds",
    "search folders", "sent items", "sync issues",
}


class MailFolderOut(BaseModel):
    id: str
    display_name: str
    child_folder_count: int
    total_item_count: int
    unread_item_count: int


class MailFoldersResponse(BaseModel):
    folders: list[MailFolderOut]


def _load_folders(provider, parent: str | None, custom: bool) -> list[dict]:
    """One level of folders. When `custom` and at the top level, drop the
    built-in system folders and promote Inbox's children (Jane's per-client
    folders) so the result is the folder tree she actually created."""
    if custom and parent is None:
        root = provider.list_mail_folders(parent_id=None)
        out = [f for f in root if f["display_name"].strip().lower() not in _DEFAULT_FOLDER_NAMES]
        inbox = next(
            (f for f in root if f["display_name"].strip().lower() == "inbox"), None
        )
        if inbox:
            out += [
                c for c in provider.list_mail_folders(parent_id=inbox["id"])
                if c["display_name"].strip().lower() not in _DEFAULT_FOLDER_NAMES
            ]
        return out
    folders = provider.list_mail_folders(parent_id=parent)
    if custom:
        folders = [
            f for f in folders
            if f["display_name"].strip().lower() not in _DEFAULT_FOLDER_NAMES
        ]
    return folders


@router.get("/folders", response_model=MailFoldersResponse)
def list_folders(
    parent: str | None = Query(default=None),
    custom: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
) -> Any:
    """One level of Outlook folders. `parent` omitted = top level;
    `custom=true` shows only Jane's own (non-default) folders."""
    key = f"{'custom' if custom else 'all'}:{parent or ''}"
    now = time.monotonic()
    cached = _FOLDER_CACHE.get(key)
    if cached and cached[0] > now:
        return {"folders": cached[1]}

    provider = get_email_provider()
    try:
        folders = _load_folders(provider, parent, custom)
    except Exception as exc:  # noqa: BLE001 — surface upstream failure as 502
        logger.warning("mailFolders list failed (parent=%s custom=%s): %s", parent, custom, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mailbox folder service.",
        ) from exc

    _FOLDER_CACHE[key] = (now + _CACHE_TTL_SECONDS, folders)
    return {"folders": folders}
