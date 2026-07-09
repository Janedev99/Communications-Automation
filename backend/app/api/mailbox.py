"""Read-only mailbox structure endpoints (Iteration A of folder routing).

GET /mailbox/folders?parent=<id>  — one level of Outlook folders (lazy).

Read-only: this module never creates, moves, or deletes a folder. A short
in-process TTL cache (per parent) avoids re-hitting Graph on repeated expands.
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
# parent-key ("" for root) -> (expires_at_monotonic, folders)
_FOLDER_CACHE: dict[str, tuple[float, list[dict]]] = {}


class MailFolderOut(BaseModel):
    id: str
    display_name: str
    child_folder_count: int
    total_item_count: int
    unread_item_count: int


class MailFoldersResponse(BaseModel):
    folders: list[MailFolderOut]


@router.get("/folders", response_model=MailFoldersResponse)
def list_folders(
    parent: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> Any:
    """One level of Outlook folders. `parent` omitted = top level."""
    key = parent or ""
    now = time.monotonic()
    cached = _FOLDER_CACHE.get(key)
    if cached and cached[0] > now:
        return {"folders": cached[1]}

    provider = get_email_provider()
    try:
        folders = provider.list_mail_folders(parent_id=parent)
    except Exception as exc:  # noqa: BLE001 — surface upstream failure as 502
        logger.warning("mailFolders list failed (parent=%s): %s", parent, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mailbox folder service.",
        ) from exc

    _FOLDER_CACHE[key] = (now + _CACHE_TTL_SECONDS, folders)
    return {"folders": folders}
