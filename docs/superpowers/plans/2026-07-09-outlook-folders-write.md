# Folder Routing Iteration B (write) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the app files a thread (auto-file on send, or manual Save/Move), reflect it in Outlook — find-or-create a client folder under Inbox and move the thread's inbound messages into it — gated behind a default-off feature flag.

**Architecture:** New provider write methods (`find_or_create_folder`, `move_message_to_folder`) mirroring the existing `move_message` pattern; a `folder_sync` service that guards on the flag + provider and never raises; wired into the existing `auto_folder` and manual-save filing points. Flag off ⇒ today's behavior (DB label only).

**Tech Stack:** Python/FastAPI/httpx/SQLAlchemy. Tests from `backend/` via `.\venv\Scripts\python.exe -m pytest`.

## Global Constraints

- **Feature flag `OUTLOOK_FOLDER_SYNC` (env), default `false`.** Off = zero mailbox writes; the service returns before any provider call.
- **HARD INVARIANT — never delete an Outlook folder.** Only create + move are implemented; a test asserts no `DELETE .../mailFolders` is issued.
- **Inbound messages only** are moved (outbound/sent stay in Sent Items).
- **Forward-only:** only new filing actions sync; no backfill; unfiling/"No folder" moves nothing and deletes nothing.
- **Folders live under Inbox** — `"inbox"` is a Graph well-known folder id (same family as the existing `deleteditems`/`junkemail` moves).
- **Fail safe:** the sync never raises — Graph failures are logged and swallowed so a send/save is never broken (same contract as today's `auto_folder`).
- Backend tests use `backend/venv`; run from `backend/`.

---

## File Structure

- **Modify** `backend/app/config.py` — add `outlook_folder_sync: bool = False`.
- **Modify** `backend/app/services/email_provider.py` — base no-op `find_or_create_folder` / `move_message_to_folder`; MSGraph overrides.
- **Create** `backend/app/services/folder_sync.py` — `sync_thread_to_outlook_folder`.
- **Modify** `backend/app/services/auto_folder.py` — call the sync after setting the label.
- **Modify** `backend/app/api/emails.py` — call the sync from the manual save paths (`save_thread` + the bulk `save` action).
- **Modify** `backend/.env.example` — document `OUTLOOK_FOLDER_SYNC`.
- **Create** `backend/tests/test_folder_sync.py` — provider write methods + service + wiring tests.

---

## Task 1: Provider write methods (create folder + move message)

**Files:**
- Modify: `backend/app/services/email_provider.py` (base no-ops after the read `list_mail_folders` base default ~line 289 area; MSGraph overrides near `move_message` ~line 735)
- Test: `backend/tests/test_folder_sync.py`

**Interfaces:**
- Produces: `EmailProvider.find_or_create_folder(self, name: str) -> str | None` and `EmailProvider.move_message_to_folder(self, internet_message_id: str, folder_id: str) -> None`. MSGraph: create under Inbox / move via `/move`. Base: no-op (`None`). **Create + move only — never DELETE.**

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_folder_sync.py`:

```python
"""Iteration B: write-side folder sync (create folder + move message).

Provider tests reuse a recording fake client to assert the exact Graph calls
and the HARD INVARIANT that no folder is ever deleted.
"""
from __future__ import annotations

from app.services.email_provider import MSGraphProvider, IMAPProvider


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingClient:
    def __init__(self, get_payloads=None, post_payloads=None):
        self._get = list(get_payloads or [])
        self._post = list(post_payloads or [])
        self.calls: list[tuple[str, str, dict | None]] = []

    def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, None))
        return _FakeResp(self._get.pop(0) if self._get else {"value": []})

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        return _FakeResp(self._post.pop(0) if self._post else {"id": "NEW"})

    def delete(self, *a, **k):
        self.calls.append(("DELETE", a[0] if a else "?", None))
        raise AssertionError("folder sync must never DELETE")

    def patch(self, *a, **k):
        self.calls.append(("PATCH", a[0] if a else "?", None))
        raise AssertionError("folder sync must never PATCH here")


def _graph(monkeypatch, client):
    from app.config import get_settings
    p = MSGraphProvider.__new__(MSGraphProvider)
    p._settings = get_settings()
    p._client = client
    monkeypatch.setattr(p, "_headers", lambda: {"Authorization": "Bearer test"})
    return p


def test_find_or_create_returns_existing_id_without_post(monkeypatch):
    client = _RecordingClient(get_payloads=[
        {"value": [{"id": "F1", "displayName": "Caroline Apex",
                    "childFolderCount": 0, "totalItemCount": 0, "unreadItemCount": 0}]}
    ])
    p = _graph(monkeypatch, client)
    # Case-insensitive match — no folder is created.
    assert p.find_or_create_folder("caroline apex") == "F1"
    assert all(m != "POST" for m, _, _ in client.calls)


def test_find_or_create_creates_when_absent(monkeypatch):
    client = _RecordingClient(
        get_payloads=[{"value": []}],
        post_payloads=[{"id": "NEW1"}],
    )
    p = _graph(monkeypatch, client)
    assert p.find_or_create_folder("Doug Conquest") == "NEW1"
    post = [c for c in client.calls if c[0] == "POST"][0]
    assert "/mailFolders/inbox/childFolders" in post[1]
    assert post[2] == {"displayName": "Doug Conquest"}


def test_move_message_posts_move(monkeypatch):
    client = _RecordingClient(get_payloads=[{"value": [{"id": "GRAPHID"}]}])
    p = _graph(monkeypatch, client)
    p.move_message_to_folder("<abc@x.com>", "F1")
    post = [c for c in client.calls if c[0] == "POST"][0]
    assert "/messages/GRAPHID/move" in post[1]
    assert post[2] == {"destinationId": "F1"}


def test_move_message_noop_when_unresolvable(monkeypatch):
    # Resolver GET returns no match -> no POST, no raise.
    client = _RecordingClient(get_payloads=[{"value": []}])
    p = _graph(monkeypatch, client)
    p.move_message_to_folder("<missing@x.com>", "F1")
    assert all(m != "POST" for m, _, _ in client.calls)


def test_write_methods_never_delete(monkeypatch):
    client = _RecordingClient(get_payloads=[{"value": []}], post_payloads=[{"id": "N"}])
    p = _graph(monkeypatch, client)
    p.find_or_create_folder("X")
    client2 = _RecordingClient(get_payloads=[{"value": [{"id": "G"}]}])
    p2 = _graph(monkeypatch, client2)
    p2.move_message_to_folder("<a@x.com>", "N")
    assert all(m != "DELETE" for m, _, _ in client.calls + client2.calls)


def test_base_provider_write_methods_are_noops():
    p = IMAPProvider.__new__(IMAPProvider)
    assert p.find_or_create_folder("X") is None
    assert p.move_message_to_folder("<a@x.com>", "F1") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_folder_sync.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'find_or_create_folder'`.

- [ ] **Step 3: Add base no-ops**

In `backend/app/services/email_provider.py`, inside `class EmailProvider`, right after the base `list_mail_folders` default added in Iteration A, add:

```python
    def find_or_create_folder(self, name: str) -> str | None:
        """Return the id of a folder named `name` under Inbox, creating it if
        absent. Base no-op (non-Graph providers don't sync). Never deletes."""
        return None

    def move_message_to_folder(self, internet_message_id: str, folder_id: str) -> None:
        """Move a message into an arbitrary folder. Base no-op."""
        return None
```

- [ ] **Step 4: Add MSGraph overrides**

In `class MSGraphProvider`, after `move_message` (~line 735), add:

```python
    def find_or_create_folder(self, name: str) -> str | None:
        """Find an Inbox child folder named `name` (case-insensitive) or create
        it under Inbox. READ + create only — never deletes."""
        target = (name or "").strip()
        if not target:
            return None
        for f in self.list_mail_folders(parent_id="inbox"):
            if f["display_name"].strip().lower() == target.lower():
                return f["id"]
        mailbox = self._settings.msgraph_mailbox
        resp = self._client.post(
            f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders/inbox/childFolders",
            headers=self._headers(),
            json={"displayName": target},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def move_message_to_folder(self, internet_message_id: str, folder_id: str) -> None:
        """Move a message (by stored internetMessageId) into `folder_id`.
        No-op if the message can't be resolved (already moved/deleted)."""
        graph_id = self._resolve_graph_message_id(internet_message_id)
        if graph_id is None:
            logger.info(
                "MSGraph move_message_to_folder: %s not found — skipping",
                internet_message_id,
            )
            return
        mailbox = self._settings.msgraph_mailbox
        resp = self._client.post(
            f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}/move",
            headers=self._headers(),
            json={"destinationId": folder_id},
        )
        resp.raise_for_status()
        logger.info("MSGraph: moved message %s to folder %s", internet_message_id, folder_id)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_folder_sync.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/email_provider.py backend/tests/test_folder_sync.py
git commit -m "feat(backend): provider find_or_create_folder + move_message_to_folder (create/move only)"
```

---

## Task 2: Config flag + `folder_sync` service

**Files:**
- Modify: `backend/app/config.py` (add flag near `shadow_mode` ~line 126)
- Modify: `backend/.env.example` (document the flag)
- Create: `backend/app/services/folder_sync.py`
- Test: `backend/tests/test_folder_sync.py` (append)

**Interfaces:**
- Consumes: `get_settings().outlook_folder_sync`, `get_settings().email_provider`, `get_email_provider()`, provider `find_or_create_folder` / `move_message_to_folder`, `EmailThread.messages`, `MessageDirection.inbound`, `EmailMessage.message_id_header`.
- Produces: `folder_sync.sync_thread_to_outlook_folder(db, *, thread, folder_name, actor_id=None, request_ip=None) -> None`. Never raises.

- [ ] **Step 1: Add the config flag**

In `backend/app/config.py`, after `shadow_mode: bool = False` (~line 126), add:

```python

    # ── Outlook folder sync (folder routing iteration B) ──────────────────────
    # When True, filing a thread in the app (auto-file on send, or manual
    # Save/Move) also creates a real Outlook folder under Inbox and moves the
    # thread's inbound messages into it. Default False = DB label only, no
    # mailbox writes. Enable only after a supervised live test.
    outlook_folder_sync: bool = False
```

In `backend/.env.example`, near the other feature flags (e.g. `SHADOW_MODE`), add:

```
# Reflect in-app folder filing into the real Outlook mailbox (create folder +
# move inbound messages). Default off; enable after a supervised live test.
OUTLOOK_FOLDER_SYNC=false
```

- [ ] **Step 2: Write the failing service tests**

Append to `backend/tests/test_folder_sync.py`:

```python
# ── Service tests ─────────────────────────────────────────────────────────────
import uuid
from datetime import datetime, timezone

from app.models.email import EmailMessage, EmailThread, EmailCategory, EmailStatus, MessageDirection


class _FakeProvider:
    def __init__(self):
        self.created: list[str] = []
        self.moved: list[tuple[str, str]] = []

    def find_or_create_folder(self, name):
        self.created.append(name)
        return "FID"

    def move_message_to_folder(self, internet_message_id, folder_id):
        self.moved.append((internet_message_id, folder_id))


def _thread_with_messages(db):
    thread = EmailThread(
        id=uuid.uuid4(), client_email="c@x.com", client_name="Client X",
        subject="Hi", category=EmailCategory.general_inquiry,
        status=EmailStatus.categorized,
    )
    inbound = EmailMessage(
        id=uuid.uuid4(), thread_id=thread.id, direction=MessageDirection.inbound,
        sender="c@x.com", recipient="jane@schilcpa.com", body_text="hi",
        message_id_header="<in@x.com>", received_at=datetime.now(timezone.utc),
    )
    outbound = EmailMessage(
        id=uuid.uuid4(), thread_id=thread.id, direction=MessageDirection.outbound,
        sender="jane@schilcpa.com", recipient="c@x.com", body_text="re",
        message_id_header="<out@x.com>", received_at=datetime.now(timezone.utc),
    )
    db.add_all([thread, inbound, outbound])
    db.commit()
    db.refresh(thread)
    return thread


def _patch(monkeypatch, *, flag, provider_name="msgraph", provider=None):
    import app.services.folder_sync as fs
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "outlook_folder_sync", flag, raising=False)
    monkeypatch.setattr(s, "email_provider", provider_name, raising=False)
    monkeypatch.setattr(fs, "get_settings", lambda: s)
    if provider is not None:
        monkeypatch.setattr(fs, "get_email_provider", lambda: provider)
    return fs


def test_sync_noop_when_flag_off(db_session, monkeypatch):
    prov = _FakeProvider()
    fs = _patch(monkeypatch, flag=False, provider=prov)
    thread = _thread_with_messages(db_session)
    fs.sync_thread_to_outlook_folder(db_session, thread=thread, folder_name="Client X")
    assert prov.created == [] and prov.moved == []


def test_sync_noop_when_not_msgraph(db_session, monkeypatch):
    prov = _FakeProvider()
    fs = _patch(monkeypatch, flag=True, provider_name="imap", provider=prov)
    thread = _thread_with_messages(db_session)
    fs.sync_thread_to_outlook_folder(db_session, thread=thread, folder_name="Client X")
    assert prov.created == [] and prov.moved == []


def test_sync_creates_and_moves_inbound_only(db_session, monkeypatch):
    prov = _FakeProvider()
    fs = _patch(monkeypatch, flag=True, provider=prov)
    thread = _thread_with_messages(db_session)
    fs.sync_thread_to_outlook_folder(db_session, thread=thread, folder_name="Client X")
    assert prov.created == ["Client X"]
    # Only the inbound message is moved — outbound stays in Sent Items.
    assert prov.moved == [("<in@x.com>", "FID")]


def test_sync_swallows_provider_error(db_session, monkeypatch):
    class _Boom(_FakeProvider):
        def find_or_create_folder(self, name):
            raise RuntimeError("graph down")
    fs = _patch(monkeypatch, flag=True, provider=_Boom())
    thread = _thread_with_messages(db_session)
    # Must not raise — the send/save that triggered it must survive.
    fs.sync_thread_to_outlook_folder(db_session, thread=thread, folder_name="Client X")
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_folder_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.folder_sync'`.

- [ ] **Step 4: Create the service**

Create `backend/app/services/folder_sync.py`:

```python
"""Reflect in-app thread filing into the real Outlook mailbox (iteration B).

Feature-flagged (OUTLOOK_FOLDER_SYNC, default off). On the existing filing
triggers, create a client folder under Inbox and move the thread's INBOUND
messages into it. Never raises — a filing sync must not break the send/save
that triggered it. Never deletes anything.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email import EmailThread, MessageDirection
from app.services.email_provider import get_email_provider
from app.utils.audit import log_action

logger = logging.getLogger(__name__)


def sync_thread_to_outlook_folder(
    db: Session,
    *,
    thread: EmailThread,
    folder_name: str | None,
    actor_id: uuid.UUID | None = None,
    request_ip: str | None = None,
) -> None:
    """Create the client folder under Inbox (if needed) and move the thread's
    inbound messages into it. No-op unless the flag is on and the provider is
    MSGraph. Logs and swallows all failures."""
    settings = get_settings()
    if not settings.outlook_folder_sync:
        return
    if settings.email_provider.lower() != "msgraph":
        return
    name = (folder_name or "").strip()
    if not name:
        return

    try:
        provider = get_email_provider()
        folder_id = provider.find_or_create_folder(name)
        if not folder_id:
            return
        moved = 0
        for msg in thread.messages:
            if msg.direction == MessageDirection.inbound and msg.message_id_header:
                provider.move_message_to_folder(msg.message_id_header, folder_id)
                moved += 1
        log_action(
            db,
            action="thread.outlook_folder_synced",
            entity_type="email_thread",
            entity_id=str(thread.id),
            user_id=actor_id,
            ip_address=request_ip,
            details={"folder": name, "moved": moved},
        )
    except Exception as exc:  # noqa: BLE001 — never break the triggering send/save
        logger.warning(
            "outlook folder sync failed for thread=%s folder=%r: %s",
            getattr(thread, "id", "?"), name, exc,
        )
```

> Implementer note: confirm `EmailMessage.message_id_header` is the attribute holding the stored internetMessageId (it is — the same field `move_message`/`mark_as_read` resolve from). Confirm `thread.messages` is the ordered relationship (used already in `thread-detail`/generation).

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_folder_sync.py -q`
Expected: PASS (all provider + service tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/.env.example backend/app/services/folder_sync.py backend/tests/test_folder_sync.py
git commit -m "feat(backend): OUTLOOK_FOLDER_SYNC flag + folder_sync service (inbound-only, fail-safe)"
```

---

## Task 3: Wire the sync into the filing triggers

**Files:**
- Modify: `backend/app/services/auto_folder.py` (inside `auto_save_to_client_folder`, after the label + audit)
- Modify: `backend/app/api/emails.py` (`save_thread` ~line 1347; and the bulk `save` action ~line 366-371)
- Test: `backend/tests/test_folder_sync.py` (append wiring tests)

**Interfaces:**
- Consumes: `folder_sync.sync_thread_to_outlook_folder`.

- [ ] **Step 1: Write the failing wiring tests**

Append to `backend/tests/test_folder_sync.py`:

```python
# ── Wiring tests ──────────────────────────────────────────────────────────────

def test_auto_folder_invokes_sync(db_session, monkeypatch):
    import app.services.auto_folder as af
    recorded = {}
    monkeypatch.setattr(
        af, "sync_thread_to_outlook_folder",
        lambda db, **kw: recorded.update(kw),
    )
    thread = _thread_with_messages(db_session)
    thread.is_saved = False
    af.auto_save_to_client_folder(db_session, thread=thread, actor_id=None, request_ip=None)
    assert recorded.get("folder_name") == "Client X"  # resolves from client_name


def test_save_thread_endpoint_invokes_sync(logged_in_admin, db_session, monkeypatch):
    import app.api.emails as emails_api
    calls = []
    monkeypatch.setattr(
        emails_api, "sync_thread_to_outlook_folder",
        lambda db, **kw: calls.append(kw),
    )
    thread = _thread_with_messages(db_session)
    resp = logged_in_admin.post(
        f"/api/v1/emails/{thread.id}/save",
        json={"folder": "Manual Folder", "note": None},
    )
    assert resp.status_code == 200, resp.text
    assert calls and calls[0]["folder_name"] == "Manual Folder"
```

> Implementer note: match the `save_thread` request body to its Pydantic model (the fields the existing endpoint reads — `folder`, `note`). Check the model in `emails.py` near the `save_thread` route and adjust the JSON if field names differ.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_folder_sync.py -q`
Expected: FAIL — sync not yet called from `auto_folder` / `save_thread`.

- [ ] **Step 3: Wire `auto_folder`**

In `backend/app/services/auto_folder.py`, add the import at top:

```python
from app.services.folder_sync import sync_thread_to_outlook_folder
```

Inside `auto_save_to_client_folder`, after the existing `log_action(...)` for `thread.auto_saved` and before `return True` (still inside the `try`), add:

```python
        sync_thread_to_outlook_folder(
            db, thread=thread, folder_name=folder_name,
            actor_id=actor_id, request_ip=request_ip,
        )
```

(The sync itself never raises; it also sits inside the existing `try/except` here as a second layer.)

- [ ] **Step 4: Wire the manual save paths**

In `backend/app/api/emails.py`, add the import near the other service imports:

```python
from app.services.folder_sync import sync_thread_to_outlook_folder
```

In `save_thread`, after `db.refresh(thread)` (just before `return EmailThreadResponse.from_thread(thread)`, ~line 1362), add:

```python
    sync_thread_to_outlook_folder(
        db, thread=thread, folder_name=folder,
        actor_id=current_user.id, request_ip=get_client_ip(request),
    )
```

In the bulk `save` action branch (~line 366-371), after the block that sets `thread.saved_folder = body.params.folder or None` and its audit, add (using that scope's `thread`, `current_user`, `request`):

```python
                sync_thread_to_outlook_folder(
                    db, thread=thread, folder_name=body.params.folder,
                    actor_id=current_user.id, request_ip=get_client_ip(request),
                )
```

> Implementer note: verify `get_client_ip(request)` is the helper already used in `save_thread`'s `log_action` (it is). Keep the call after the label is set + flushed so a filing that fails to persist doesn't trigger a mailbox move.

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_folder_sync.py -q`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/auto_folder.py backend/app/api/emails.py backend/tests/test_folder_sync.py
git commit -m "feat(backend): wire folder_sync into auto-file + manual save"
```

---

## Final Verification (after all tasks)

- [ ] **Full backend suite:** `cd backend && .\venv\Scripts\python.exe -m pytest tests/ -q` — all pass (baseline + new). Flag defaults off, so no existing test changes behavior.
- [ ] **Flag-off inertness:** confirm `test_sync_noop_when_flag_off` passes — with the flag off, no provider calls happen (this is what ships to prod initially).
- [ ] **No-delete invariant:** confirmed by `test_write_methods_never_delete`.
- [ ] **Gated live smoke (user-driven, do NOT run unprompted):** only with the user's explicit go — set `OUTLOOK_FOLDER_SYNC=true` locally, file a test thread, confirm a folder appears under Inbox and the inbound message moved. Prefer a disposable test thread/folder on the mailbox first. Never delete anything to "clean up."
- [ ] Hand back for user smoke + merge decision. Do NOT merge to `development` without the user's go-ahead; master only on explicit approval. Leave the flag OFF in all committed config.
