"""One-time (re-runnable) import of Outlook folders into the saved_folders
registry, and a push that creates app folders in Outlook. Never deletes."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.mailbox import _DEFAULT_FOLDER_NAMES
from app.config import get_settings
from app.models.email import SavedFolderRow
from app.services.email_provider import get_email_provider

logger = logging.getLogger(__name__)

_MAX_DEPTH = 6


def _top_level_custom_folders(provider) -> list[dict]:
    """Mirror /mailbox/folders?custom=true's top-level behavior (see
    app.api.mailbox._load_folders): drop Outlook's built-in system folders
    and promote Inbox's children, since Jane's per-client folders sometimes
    live as siblings of Inbox and sometimes as children of it. Without this,
    a plain top-level walk would import Inbox/Drafts/Sent Items/etc. as if
    they were Jane's own folders."""
    try:
        root = provider.list_mail_folders(parent_id=None)
    except Exception as exc:  # noqa: BLE001 — best effort per folder
        logger.warning("folder import: list failed under %s: %s", None, exc)
        return []
    out = [f for f in root if f["display_name"].strip().lower() not in _DEFAULT_FOLDER_NAMES]
    inbox = next((f for f in root if f["display_name"].strip().lower() == "inbox"), None)
    if inbox:
        try:
            children = provider.list_mail_folders(parent_id=inbox["id"])
        except Exception as exc:  # noqa: BLE001 — best effort per folder
            logger.warning("folder import: list failed under %s: %s", inbox["id"], exc)
            children = []
        out += [
            c for c in children
            if c["display_name"].strip().lower() not in _DEFAULT_FOLDER_NAMES
        ]
    return out


def import_outlook_folders(db: Session) -> dict:
    """Recursively read custom Outlook folders and upsert registry rows by name
    (case-insensitive). Sets source='outlook', outlook_folder_id, item count, and
    parent_id from the Outlook tree. Idempotent. No-op unless provider is MSGraph.

    Only the top level is filtered against Outlook's built-in defaults (Inbox,
    Drafts, Sent Items, ...) — mirroring the read-only /mailbox/folders custom
    view. Anything below that level is a folder Jane created herself, so its
    name is never excluded."""
    settings = get_settings()
    if settings.email_provider.lower() != "msgraph":
        return {"imported": 0, "updated": 0, "total": 0}
    provider = get_email_provider()

    existing = {r.name.lower(): r for r in db.execute(select(SavedFolderRow)).scalars().all()}
    imported = updated = 0

    def walk(parent_graph_id: str | None, parent_row_id, depth: int) -> None:
        nonlocal imported, updated
        if depth > _MAX_DEPTH:
            logger.warning("folder import: depth cap %s hit under %s", _MAX_DEPTH, parent_graph_id)
            return
        if depth == 0:
            folders = _top_level_custom_folders(provider)
        else:
            try:
                folders = provider.list_mail_folders(parent_id=parent_graph_id)
            except Exception as exc:  # noqa: BLE001 — best effort per folder
                logger.warning("folder import: list failed under %s: %s", parent_graph_id, exc)
                return
        for f in folders:
            name = f["display_name"].strip()
            row = existing.get(name.lower())
            if row is None:
                row = SavedFolderRow(name=name, source="outlook",
                                     outlook_folder_id=f["id"],
                                     outlook_item_count=f.get("total_item_count"),
                                     parent_id=parent_row_id)
                db.add(row)
                db.flush()  # assign row.id for children
                existing[name.lower()] = row
                imported += 1
            else:
                row.source = "outlook"
                row.outlook_folder_id = f["id"]
                row.outlook_item_count = f.get("total_item_count")
                row.parent_id = parent_row_id
                updated += 1
            if f.get("child_folder_count", 0) > 0:
                walk(f["id"], row.id, depth + 1)

    walk(None, None, 0)
    db.flush()
    return {"imported": imported, "updated": updated, "total": imported + updated}


def sync_folders_to_outlook(db: Session) -> dict:
    """Create each registry folder in Outlook (find-or-create at root) and store
    the returned Graph id. Additive only — never deletes. No-op unless MSGraph."""
    settings = get_settings()
    if settings.email_provider.lower() != "msgraph":
        return {"created": 0, "existing": 0, "total": 0}
    provider = get_email_provider()

    rows = db.execute(select(SavedFolderRow)).scalars().all()
    created = existing = 0
    for r in rows:
        had_id = bool(r.outlook_folder_id)
        try:
            fid = provider.find_or_create_folder(r.name)
        except Exception as exc:  # noqa: BLE001 — best effort per folder
            logger.warning("folder sync failed for %s: %s", r.name, exc)
            continue
        if fid:
            r.outlook_folder_id = fid
            existing += 1 if had_id else 0
            created += 0 if had_id else 1
    db.flush()
    return {"created": created, "existing": existing, "total": len(rows)}
