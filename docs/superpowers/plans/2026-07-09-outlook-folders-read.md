# Outlook Folders (read-only) — Iteration A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Jane's real Outlook folder tree inside the portal (read-only), so she sees her actual mailbox structure reflected in the app.

**Architecture:** A new read-only `list_mail_folders` method on the email provider (Graph GET, lazy one-level-per-call, paginated) feeds a new authenticated endpoint `GET /api/v1/mailbox/folders?parent=<id>` (short TTL cache). The Saved page gains a lazy-expanding Outlook folder tree with a search filter. No mailbox writes of any kind.

**Tech Stack:** Python/FastAPI/httpx/SQLAlchemy backend (`backend/`, tests via `backend/venv/Scripts/python.exe -m pytest`); Next.js 14 / React / SWR / Tailwind / Base UI frontend.

## Global Constraints

- **HARD INVARIANT — never delete an Outlook folder.** No code issues `DELETE .../mailFolders`. This iteration is read-only: provider issues only GET. A test asserts this.
- Read-only: no folder creation, no message moves, no viewing a folder's messages (all deferred to Iteration B or later).
- Provider-agnostic: non-Graph providers (IMAP) return `[]` — the feature degrades to empty, never errors.
- Lazy: one folder level per request (`parent` omitted = top level); the client fetches children only on expand. Jane's Inbox has 427 children — never fetch all at once.
- Backend tests use `backend/venv` (system Python lacks deps). Run from `backend/`.
- Confirmed live: the Graph app registration has `Mail.ReadWrite` — no new Azure consent needed.

---

## File Structure

- **Modify** `backend/app/services/email_provider.py`
  - Add non-abstract `EmailProvider.list_mail_folders(self, parent_id=None) -> list[dict]` returning `[]` (base default; IMAP + others inherit).
  - Override `MSGraphProvider.list_mail_folders` — Graph GET, pagination, mapping.
- **Create** `backend/app/api/mailbox.py` — router `/mailbox`, `GET /folders`, TTL cache, Pydantic response models.
- **Modify** `backend/app/main.py` — register the mailbox router under `/api/v1`.
- **Create** `backend/tests/test_mailbox_folders.py` — provider + endpoint + no-delete tests.
- **Modify** `frontend/src/lib/types.ts` — `OutlookFolder` type.
- **Modify** `frontend/src/hooks/use-emails.ts` (or a new `use-mailbox.ts`) — `useOutlookFolders(parentId?)` SWR hook.
- **Create** `frontend/src/components/emails/outlook-folder-tree.tsx` — lazy tree + search.
- **Modify** `frontend/src/app/(dashboard)/saved/page.tsx` — add an "Outlook folders" section.

---

## Task 1: Provider `list_mail_folders` (read-only Graph list)

**Files:**
- Modify: `backend/app/services/email_provider.py` (add base method after `fetch_attachment`'s sibling defaults ~line 289 area; add MSGraph override near the other MSGraph methods, e.g. after `_resolve_graph_message_id`)
- Test: `backend/tests/test_mailbox_folders.py`

**Interfaces:**
- Produces: `EmailProvider.list_mail_folders(self, parent_id: str | None = None) -> list[dict]`. Each dict: `{"id": str, "display_name": str, "child_folder_count": int, "total_item_count": int, "unread_item_count": int}`. Base returns `[]`; MSGraph returns real folders. **Only GET is ever issued.**

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_mailbox_folders.py`:

```python
"""Iteration A: read-only Outlook folder listing.

Provider-level tests use a fake httpx-style client recording every request so
we can assert (a) correct URLs, (b) @odata.nextLink pagination, and (c) the
HARD INVARIANT that only GET is ever issued (never DELETE/POST/PATCH).
"""
from __future__ import annotations

import pytest

from app.services.email_provider import MSGraphProvider, IMAPProvider


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingClient:
    """Records (method, url) for every call; returns queued GET payloads."""
    def __init__(self, get_payloads):
        self._get_payloads = list(get_payloads)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url))
        return _FakeResp(self._get_payloads.pop(0))

    def post(self, *a, **k):
        self.calls.append(("POST", a[0] if a else "?"))
        raise AssertionError("folder listing must never POST")

    def delete(self, *a, **k):
        self.calls.append(("DELETE", a[0] if a else "?"))
        raise AssertionError("folder listing must never DELETE")

    def patch(self, *a, **k):
        self.calls.append(("PATCH", a[0] if a else "?"))
        raise AssertionError("folder listing must never PATCH")


def _graph_provider(monkeypatch, client):
    from app.config import get_settings
    p = MSGraphProvider.__new__(MSGraphProvider)  # skip __init__/network
    p._settings = get_settings()
    p._client = client
    # _headers uses a cached token; stub it so no token call happens.
    monkeypatch.setattr(p, "_headers", lambda: {"Authorization": "Bearer test"})
    return p


def test_list_root_folders_maps_fields(monkeypatch):
    client = _RecordingClient([
        {"value": [
            {"id": "AAA", "displayName": "Inbox", "childFolderCount": 427,
             "totalItemCount": 682, "unreadItemCount": 12},
        ]}
    ])
    p = _graph_provider(monkeypatch, client)
    folders = p.list_mail_folders()
    assert folders == [{
        "id": "AAA", "display_name": "Inbox", "child_folder_count": 427,
        "total_item_count": 682, "unread_item_count": 12,
    }]
    # Root uses /mailFolders (not childFolders); GET only.
    assert client.calls[0][0] == "GET"
    assert "/mailFolders" in client.calls[0][1]
    assert "childFolders" not in client.calls[0][1]


def test_list_child_folders_uses_parent_path(monkeypatch):
    client = _RecordingClient([{"value": []}])
    p = _graph_provider(monkeypatch, client)
    p.list_mail_folders(parent_id="AAA")
    assert "/mailFolders/AAA/childFolders" in client.calls[0][1]


def test_pagination_follows_nextlink(monkeypatch):
    client = _RecordingClient([
        {"value": [{"id": "1", "displayName": "A", "childFolderCount": 0,
                    "totalItemCount": 0, "unreadItemCount": 0}],
         "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page-2"},
        {"value": [{"id": "2", "displayName": "B", "childFolderCount": 0,
                    "totalItemCount": 0, "unreadItemCount": 0}]},
    ])
    p = _graph_provider(monkeypatch, client)
    folders = p.list_mail_folders()
    assert [f["id"] for f in folders] == ["1", "2"]
    assert client.calls[1] == ("GET", "https://graph.microsoft.com/v1.0/next-page-2")


def test_only_get_is_issued(monkeypatch):
    client = _RecordingClient([{"value": []}])
    p = _graph_provider(monkeypatch, client)
    p.list_mail_folders()
    assert all(m == "GET" for m, _ in client.calls)


def test_non_graph_provider_returns_empty():
    # IMAP (and the base default) never talk to Graph — return [].
    p = IMAPProvider.__new__(IMAPProvider)
    assert p.list_mail_folders() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_mailbox_folders.py -q`
Expected: FAIL — `AttributeError: 'MSGraphProvider' object has no attribute 'list_mail_folders'` (and same for IMAP).

- [ ] **Step 3: Add the base default (read-only, returns [])**

In `backend/app/services/email_provider.py`, inside `class EmailProvider`, after the existing non-abstract `fetch_inline_attachment` default (~line 289), add:

```python
    def list_mail_folders(self, parent_id: str | None = None) -> list[dict]:
        """
        List one level of mail folders (read-only). ``parent_id=None`` = top
        level; otherwise the children of that folder. Returns dicts:
        ``{id, display_name, child_folder_count, total_item_count,
        unread_item_count}``.

        Default is an empty list so non-Graph providers (IMAP, etc.) degrade
        cleanly — the folder feature simply shows nothing. Read-only: no
        implementation may create, move, or DELETE a folder.
        """
        return []
```

- [ ] **Step 4: Add the MSGraph override**

In `class MSGraphProvider`, after `_resolve_graph_message_id` (~line 460), add:

```python
    def list_mail_folders(self, parent_id: str | None = None) -> list[dict]:
        """List one level of Outlook mail folders (READ-ONLY — GET only).

        Follows @odata.nextLink pagination. parent_id=None -> top-level
        /mailFolders; otherwise /mailFolders/{parent_id}/childFolders.
        """
        mailbox = self._settings.msgraph_mailbox
        if parent_id:
            url: str | None = (
                f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders/{parent_id}/childFolders"
            )
        else:
            url = f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders"
        params = {
            "$select": "id,displayName,childFolderCount,totalItemCount,unreadItemCount",
            "$top": 100,
        }
        out: list[dict] = []
        while url:
            resp = self._client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            body = resp.json()
            for f in body.get("value", []):
                out.append({
                    "id": f["id"],
                    "display_name": f.get("displayName") or "(unnamed)",
                    "child_folder_count": f.get("childFolderCount") or 0,
                    "total_item_count": f.get("totalItemCount") or 0,
                    "unread_item_count": f.get("unreadItemCount") or 0,
                })
            # nextLink is a fully-formed URL and already carries the query;
            # drop params so we don't double-append them.
            url = body.get("@odata.nextLink")
            params = None
        return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_mailbox_folders.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/email_provider.py backend/tests/test_mailbox_folders.py
git commit -m "feat(backend): read-only list_mail_folders on email provider"
```

---

## Task 2: Endpoint `GET /api/v1/mailbox/folders`

**Files:**
- Create: `backend/app/api/mailbox.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/test_mailbox_folders.py` (append endpoint tests)

**Interfaces:**
- Consumes: `get_email_provider()` → `.list_mail_folders(parent_id)`; `get_current_user` auth dep.
- Produces: `GET /api/v1/mailbox/folders?parent=<id>` → `{"folders": [{id, display_name, child_folder_count, total_item_count, unread_item_count}, ...]}`. 401/403 unauth; 502 on Graph error; `{"folders": []}` when provider isn't Graph.

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/test_mailbox_folders.py`:

```python
# ── Endpoint tests ────────────────────────────────────────────────────────────

def test_folders_endpoint_requires_auth(client):
    resp = client.get("/api/v1/mailbox/folders")
    assert resp.status_code in (401, 403), resp.text


def test_folders_endpoint_returns_shape(logged_in_admin, monkeypatch):
    import app.api.mailbox as mailbox_api
    mailbox_api._FOLDER_CACHE.clear()

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            return [{"id": "AAA", "display_name": "Inbox", "child_folder_count": 427,
                     "total_item_count": 682, "unread_item_count": 12}]
    monkeypatch.setattr(mailbox_api, "get_email_provider", lambda: _Prov())

    resp = logged_in_admin.get("/api/v1/mailbox/folders")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["folders"][0]["display_name"] == "Inbox"
    assert data["folders"][0]["child_folder_count"] == 427


def test_folders_endpoint_passes_parent(logged_in_admin, monkeypatch):
    import app.api.mailbox as mailbox_api
    mailbox_api._FOLDER_CACHE.clear()
    seen = {}

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            seen["parent"] = parent_id
            return []
    monkeypatch.setattr(mailbox_api, "get_email_provider", lambda: _Prov())

    logged_in_admin.get("/api/v1/mailbox/folders?parent=XYZ")
    assert seen["parent"] == "XYZ"


def test_folders_endpoint_graph_error_returns_502(logged_in_admin, monkeypatch):
    import app.api.mailbox as mailbox_api
    mailbox_api._FOLDER_CACHE.clear()

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            raise RuntimeError("graph down")
    monkeypatch.setattr(mailbox_api, "get_email_provider", lambda: _Prov())

    resp = logged_in_admin.get("/api/v1/mailbox/folders")
    assert resp.status_code == 502, resp.text
```

> Implementer note: use whatever auth fixtures this repo already provides — `client` (unauthenticated) and `logged_in_admin` (authenticated) are used across `test_drafts_send.py` / `test_per_user_signatures.py`. Match their names exactly.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_mailbox_folders.py -q`
Expected: FAIL — `mailbox` module/route does not exist (404 / import error).

- [ ] **Step 3: Create the router**

Create `backend/app/api/mailbox.py`:

```python
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
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, next to the other `app.include_router(... prefix="/api/v1")` lines (~250-264), add an import for `mailbox` alongside the sibling routers and:

```python
    app.include_router(mailbox.router, prefix="/api/v1")
```

(Match the existing import style — the routers are imported as `from app.api import auth, emails, ...`; add `mailbox` to that list.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_mailbox_folders.py -q`
Expected: PASS (all provider + endpoint tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/mailbox.py backend/app/main.py backend/tests/test_mailbox_folders.py
git commit -m "feat(backend): GET /api/v1/mailbox/folders — lazy Outlook folder listing"
```

---

## Task 3: Frontend — Outlook folder tree on the Saved page

**Files:**
- Modify: `frontend/src/lib/types.ts` (add `OutlookFolder`)
- Modify: `frontend/src/hooks/use-emails.ts` (add `useOutlookFolders`)
- Create: `frontend/src/components/emails/outlook-folder-tree.tsx`
- Modify: `frontend/src/app/(dashboard)/saved/page.tsx` (render the tree in a new section)

**Interfaces:**
- Consumes: `GET /api/v1/mailbox/folders?parent=<id>` via SWR (`swrFetcher`, `useSWR`).
- Produces: `useOutlookFolders(parentId?: string)` → `{ folders: OutlookFolder[], isLoading, isError }`; `<OutlookFolderTree />`.

- [ ] **Step 1: Add the type**

In `frontend/src/lib/types.ts`, add:

```ts
export interface OutlookFolder {
  id: string;
  display_name: string;
  child_folder_count: number;
  total_item_count: number;
  unread_item_count: number;
}
```

- [ ] **Step 2: Add the hook**

In `frontend/src/hooks/use-emails.ts`, add (import `OutlookFolder` in the existing type import block):

```ts
/** One level of Outlook folders. Omit parentId for the top level; pass a
 *  folder id to fetch its children (lazy expand). */
export function useOutlookFolders(parentId?: string) {
  const key = parentId
    ? `/api/v1/mailbox/folders?parent=${encodeURIComponent(parentId)}`
    : "/api/v1/mailbox/folders";
  const { data, error, isLoading } = useSWR<{ folders: OutlookFolder[] }>(
    key,
    swrFetcher,
  );
  return { folders: data?.folders ?? [], isLoading, isError: !!error };
}
```

- [ ] **Step 3: Create the tree component**

Create `frontend/src/components/emails/outlook-folder-tree.tsx`:

```tsx
"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Folder, FolderOpen, Loader2 } from "lucide-react";
import { useOutlookFolders } from "@/hooks/use-emails";
import { cn } from "@/lib/utils";
import type { OutlookFolder } from "@/lib/types";

/**
 * Read-only, lazy-expanding view of the mailbox's real Outlook folders.
 * Each node fetches its children only when expanded (the Inbox alone has
 * hundreds), and a search box filters the currently-loaded nodes by name.
 * Nothing here mutates the mailbox.
 */
export function OutlookFolderTree() {
  const [query, setQuery] = useState("");
  const { folders, isLoading, isError } = useOutlookFolders();

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h3 className="text-sm font-semibold text-foreground">Outlook folders</h3>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter loaded folders…"
          className="h-7 w-40 rounded-md border border-border bg-card px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />
      </div>
      {isError ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Couldn&apos;t load Outlook folders. Check the mailbox connection.
        </p>
      ) : isLoading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading folders…
        </p>
      ) : folders.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          No Outlook folders found.
        </p>
      ) : (
        <ul className="space-y-0.5">
          {folders.map((f) => (
            <FolderNode key={f.id} folder={f} depth={0} filter={query.trim().toLowerCase()} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FolderNode({
  folder,
  depth,
  filter,
}: {
  folder: OutlookFolder;
  depth: number;
  filter: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = folder.child_folder_count > 0;
  // Fetch children only once expanded (lazy).
  const { folders: children, isLoading } = useOutlookFolders(
    expanded ? folder.id : undefined,
  );

  const matches = !filter || folder.display_name.toLowerCase().includes(filter);
  const visibleChildren = useMemo(
    () => children.filter((c) => !filter || c.display_name.toLowerCase().includes(filter)),
    [children, filter],
  );
  // Hide a non-matching leaf while filtering; keep parents so matches stay reachable.
  if (filter && !matches && (!expanded || visibleChildren.length === 0)) return null;

  return (
    <li>
      <div
        className="flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-accent/50 transition-colors"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          onClick={() => hasChildren && setExpanded((v) => !v)}
          className={cn(
            "flex items-center justify-center w-4 h-4 shrink-0 text-muted-foreground",
            !hasChildren && "invisible",
          )}
          aria-label={expanded ? "Collapse" : "Expand"}
          aria-expanded={hasChildren ? expanded : undefined}
        >
          <ChevronRight className={cn("w-3.5 h-3.5 transition-transform", expanded && "rotate-90")} />
        </button>
        {expanded ? (
          <FolderOpen className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" strokeWidth={1.75} />
        ) : (
          <Folder className="w-4 h-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
        )}
        <span className="flex-1 truncate text-sm text-foreground">{folder.display_name}</span>
        {folder.unread_item_count > 0 && (
          <span className="text-[10px] font-semibold text-primary tabular-nums">
            {folder.unread_item_count}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground tabular-nums">
          {folder.total_item_count}
        </span>
      </div>
      {expanded && (
        isLoading ? (
          <p
            className="flex items-center gap-2 text-xs text-muted-foreground py-1"
            style={{ paddingLeft: `${depth * 16 + 32}px` }}
          >
            <Loader2 className="w-3 h-3 animate-spin" /> Loading…
          </p>
        ) : (
          <ul className="space-y-0.5">
            {visibleChildren.map((c) => (
              <FolderNode key={c.id} folder={c} depth={depth + 1} filter={filter} />
            ))}
          </ul>
        )
      )}
    </li>
  );
}
```

- [ ] **Step 4: Render it on the Saved page**

In `frontend/src/app/(dashboard)/saved/page.tsx`, import the component near the other component imports:

```tsx
import { OutlookFolderTree } from "@/components/emails/outlook-folder-tree";
```

Then render it below the existing Saved content. Inside the top-level `return`'s outer `<div>`, after the `grid` block closes (after the `</div>` that ends the `grid grid-cols-1 lg:grid-cols-[220px_1fr]` container, before the ConfirmDialog), add:

```tsx
      {/* Jane's real Outlook folder structure (read-only). Separate from the
          app's own saved folders above — this reflects the actual mailbox. */}
      <div className="mt-6">
        <OutlookFolderTree />
      </div>
```

- [ ] **Step 5: Verify types + build**

Run: `cd frontend && npx tsc --noEmit`
Expected: `TSC CLEAN` (no errors).

Run: `cd frontend && npx next lint`
Expected: only the pre-existing `draft-panel.tsx:152` exhaustive-deps warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/hooks/use-emails.ts frontend/src/components/emails/outlook-folder-tree.tsx "frontend/src/app/(dashboard)/saved/page.tsx"
git commit -m "feat(frontend): read-only Outlook folder tree on the Saved page"
```

---

## Final Verification (after all tasks)

- [ ] **Full backend suite:** `cd backend && .\venv\Scripts\python.exe -m pytest tests/ -q` — all pass (no regressions vs the ~448 baseline + the new mailbox tests).
- [ ] **Frontend build:** `cd frontend && npm run build` — succeeds (stop the dev server first; it locks `.next`).
- [ ] **Live read smoke (safe, read-only):** start backend + frontend, open Saved → confirm the "Outlook folders" tree lists top-level folders (Inbox, Sent, etc.), expanding Inbox lazily loads its 427 children, the filter box narrows loaded nodes, counts show. No write occurs.
- [ ] **No-delete invariant:** confirmed by the provider test (`test_only_get_is_issued`) — the code issues only GET.
- [ ] Hand back for user smoke + merge decision. Do NOT merge to `development` without the user's go-ahead. Master only on explicit approval.
