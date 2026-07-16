# First-Class Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn saved folders into first-class entities (a `saved_folders` registry table) so the app's folders and Jane's Outlook folders become one system — importable, nestable, deletable in-app (reflecting recoverably to Outlook), and usable as save targets.

**Architecture:** A new `saved_folders` registry table stores folder identity, hierarchy (`parent_id`), origin (`source`), and the Graph id/item-count. Emails keep referencing folders by **name** (existing `saved_folder` string), so all current save/move/filter/sync code paths are untouched. New endpoints manage the registry; import/sync bridge to Microsoft Graph reusing the folder-sync methods shipped this week; folder delete reflects to Outlook via Graph's recoverable move-to-Deleted-Items, gated by `OUTLOOK_FOLDER_SYNC` and always user-confirmed.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, pytest (backend); Next.js 14 App Router, React, SWR, Tailwind, TypeScript (frontend); Microsoft Graph via `MSGraphProvider`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-10-first-class-folders-design.md`. Every task implicitly includes its invariants.
- **Folder deletion is always user-confirmed and recoverable** — Graph `DELETE /mailFolders/{id}` (move to Deleted Items), never a permanent purge.
- Reflecting delete to Outlook happens **only** when `settings.outlook_folder_sync` is true AND the folder has an `outlook_folder_id`; otherwise in-app only.
- **Import, Sync, and Create never delete anything** in Outlook.
- Emails keep pointing at folders by **name**; do not migrate `email_threads.saved_folder` / `email_messages.saved_folder` to a foreign key.
- Folder names are **case-insensitively unique** app-wide.
- Backend column style mirrors `app/models/email.py`: `UUID(as_uuid=True)`, `DateTime(timezone=True)`, `Mapped[...]`.
- Migration id `021`, `down_revision = "020"`.
- Provider methods live in `app/services/email_provider.py`; base `EmailProvider` gets no-op defaults, `MSGraphProvider` the real impl (mirror existing `find_or_create_folder`).
- Run backend tests with `backend/venv/Scripts/python.exe -m pytest`.
- Frontend "tests" are `npx tsc --noEmit` (from `frontend/`) plus the stated manual/Playwright check — this repo has no JS unit runner.
- Dual-repo push (origin fans out to schillerCPA + Janedev99); branch `FEAT/first-class-folders` off `development`.

---

## File Structure

- `backend/app/models/email.py` — **modify**: add `SavedFolderRow` model (registry table).
- `backend/alembic/versions/021_saved_folders_registry.py` — **create**: table + backfill.
- `backend/app/schemas/email.py` — **modify**: extend `SavedFolder`; add `CreateFolderRequest`, `FolderSyncResult`, `FolderImportResult`.
- `backend/app/services/email_provider.py` — **modify**: `delete_folder` on base + MSGraph.
- `backend/app/services/folder_import.py` — **create**: recursive import + push service.
- `backend/app/api/emails.py` — **modify**: extend list + delete; add create, import, sync endpoints.
- `backend/tests/test_folders_registry.py` — **create**: model/endpoint tests.
- `backend/tests/test_folder_import.py` — **create**: import/sync/provider-delete tests.
- `frontend/src/lib/types.ts` — **modify**: extend `SavedFolder`.
- `frontend/src/hooks/use-emails.ts` — **modify**: `createFolder`, `deleteSavedFolder` (exists), `importOutlookFolders`, `syncFoldersToOutlook`; `useSavedFolders` unchanged endpoint.
- `frontend/src/app/(dashboard)/saved/page.tsx` — **modify**: registry-driven rail tree + subfolder create.
- `frontend/src/components/emails/folder-delete-dialog.tsx` — **create**: confirm + Outlook-impact warning.
- `frontend/src/components/emails/save-thread-dialog.tsx` — **modify**: searchable folder-tree targets.
- `frontend/src/app/(dashboard)/settings/**` — **modify**: Folders section with Import / Sync buttons.

---

## Task 1: `saved_folders` model + migration 021

**Files:**
- Modify: `backend/app/models/email.py` (add model after `EmailMessage`)
- Create: `backend/alembic/versions/021_saved_folders_registry.py`
- Test: `backend/tests/test_folders_registry.py`

**Interfaces:**
- Produces: `SavedFolderRow` ORM model with columns `id: uuid.UUID`, `name: str`, `parent_id: uuid.UUID | None`, `source: str` (`"app"`/`"outlook"`), `outlook_folder_id: str | None`, `outlook_item_count: int | None`, `created_at: datetime`. Table `saved_folders`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_folders_registry.py
from __future__ import annotations
import uuid
from app.models.email import SavedFolderRow


def test_saved_folder_row_columns():
    row = SavedFolderRow(name="Acme Corp", source="app")
    assert row.name == "Acme Corp"
    assert row.source == "app"
    assert row.parent_id is None
    assert row.outlook_folder_id is None
    assert row.outlook_item_count is None


def test_saved_folder_row_tablename():
    assert SavedFolderRow.__tablename__ == "saved_folders"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py -q` (cwd `backend`)
Expected: FAIL — `ImportError: cannot import name 'SavedFolderRow'`.

- [ ] **Step 3: Add the model**

Add to `backend/app/models/email.py` after the `EmailMessage` class:

```python
class SavedFolderRow(Base):
    """Registry of saved folders (first-class). Emails still reference a folder
    by NAME (email_threads.saved_folder); this table lets empty folders exist,
    carry hierarchy (parent_id), and record Outlook origin + item count."""
    __tablename__ = "saved_folders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("saved_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # "app" = created in-app; "outlook" = imported from the mailbox.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="app")
    outlook_folder_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outlook_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 4: Run the model test — expect PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/021_saved_folders_registry.py`:

```python
"""saved_folders registry (first-class folders)

Revision ID: 021
Revises: 020
Create Date: 2026-07-10

Adds the saved_folders registry table and backfills it with the distinct
saved_folder labels currently in use on saved threads/messages (source='app',
top-level), so the existing folder rail does not regress on first deploy.
"""
import uuid
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_folders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True),
                  sa.ForeignKey("saved_folders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="app"),
        sa.Column("outlook_folder_id", sa.String(length=512), nullable=True),
        sa.Column("outlook_item_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_saved_folders_name", "saved_folders", ["name"], unique=True)
    op.create_index("ix_saved_folders_parent_id", "saved_folders", ["parent_id"])

    # Backfill: one row per distinct non-null saved_folder label in use.
    conn = op.get_bind()
    names = set()
    for tbl in ("email_threads", "email_messages"):
        rows = conn.execute(sa.text(
            f"SELECT DISTINCT saved_folder FROM {tbl} "
            f"WHERE is_saved = true AND saved_folder IS NOT NULL"
        )).fetchall()
        names.update(r[0] for r in rows if r[0])
    for name in names:
        conn.execute(
            sa.text("INSERT INTO saved_folders (id, name, source) "
                    "VALUES (:id, :name, 'app')"),
            {"id": str(uuid.uuid4()), "name": name},
        )


def downgrade() -> None:
    op.drop_index("ix_saved_folders_parent_id", table_name="saved_folders")
    op.drop_index("ix_saved_folders_name", table_name="saved_folders")
    op.drop_table("saved_folders")
```

- [ ] **Step 6: Verify migration applies on a scratch SQLite DB**

Run (cwd `backend`):
```bash
backend/venv/Scripts/python.exe -c "import sqlalchemy as sa; from app.database import Base; import app.models.email; e=sa.create_engine('sqlite://'); Base.metadata.create_all(e); print('saved_folders' in sa.inspect(e).get_table_names())"
```
Expected: prints `True`. (The test DB builds schema from metadata; migration parity is verified by prod deploy. Do NOT run alembic against the prod `DATABASE_URL`.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/email.py backend/alembic/versions/021_saved_folders_registry.py backend/tests/test_folders_registry.py
git commit -m "feat(backend): saved_folders registry model + migration 021 (backfill)"
```

---

## Task 2: Schemas for folder registry

**Files:**
- Modify: `backend/app/schemas/email.py` (extend `SavedFolder` at line 358; add new models nearby)
- Test: `backend/tests/test_folders_registry.py`

**Interfaces:**
- Produces: `SavedFolder` gains `id: uuid.UUID | None`, `parent_id: uuid.UUID | None`, `source: str | None`, `outlook_item_count: int | None`. New `CreateFolderRequest{ name: str, parent_id: uuid.UUID | None }`, `FolderImportResult{ imported: int, updated: int, total: int }`, `FolderSyncResult{ created: int, existing: int, total: int }`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_folders_registry.py
def test_folder_schemas_exist():
    from app.schemas.email import (
        CreateFolderRequest, FolderImportResult, FolderSyncResult, SavedFolder,
    )
    req = CreateFolderRequest(name="X")
    assert req.parent_id is None
    sf = SavedFolder(name="X", count=0, thread_count=0, message_count=0)
    assert sf.source is None and sf.outlook_item_count is None
    assert FolderImportResult(imported=1, updated=2, total=3).total == 3
    assert FolderSyncResult(created=1, existing=2, total=3).created == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py::test_folder_schemas_exist -q`
Expected: FAIL — `ImportError` for `CreateFolderRequest`.

- [ ] **Step 3: Extend the schemas**

In `backend/app/schemas/email.py`, extend `SavedFolder` (line ~358) to add fields, and add the new models after it:

```python
class SavedFolder(BaseModel):
    """Entry returned by GET /emails/saved/folders."""
    id: uuid.UUID | None = None
    name: str | None = Field(
        default=None,
        description="Folder name. Null indicates the unsorted/unfiled saved bucket.",
    )
    parent_id: uuid.UUID | None = None
    source: str | None = None  # "app" | "outlook" | None (unfiled bucket)
    outlook_item_count: int | None = None
    count: int
    thread_count: int = 0
    message_count: int = 0


class CreateFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: uuid.UUID | None = None


class FolderImportResult(BaseModel):
    imported: int
    updated: int
    total: int


class FolderSyncResult(BaseModel):
    created: int
    existing: int
    total: int
```

(Keep the existing `thread_count`/`message_count` fields — if they already exist below line 365, leave them; the block above shows the intended final shape.)

- [ ] **Step 4: Run to verify PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py::test_folder_schemas_exist -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/email.py backend/tests/test_folders_registry.py
git commit -m "feat(backend): folder registry schemas (create/import/sync + extended SavedFolder)"
```

---

## Task 3: List endpoint — registry + counts + defensive union

**Files:**
- Modify: `backend/app/api/emails.py` (`list_saved_folders`, line ~1424)
- Test: `backend/tests/test_folders_registry.py`

**Interfaces:**
- Consumes: `SavedFolderRow` (Task 1), extended `SavedFolder` (Task 2).
- Produces: `GET /api/v1/emails/saved/folders` returns registry rows (with `id`/`parent_id`/`source`/`outlook_item_count`) merged with in-app counts by name, plus the unfiled bucket and any legacy label-only folders.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_folders_registry.py
from app.models.email import (
    EmailThread, EmailCategory, EmailStatus, SavedFolderRow,
)
import uuid as _uuid


def test_list_folders_merges_registry_and_counts(logged_in_admin, db_session):
    # A registry folder with no saved items -> appears with count 0.
    empty = SavedFolderRow(name="Empty Client", source="outlook",
                           outlook_folder_id="OF1", outlook_item_count=147)
    db_session.add(empty)
    # A saved thread filed under a registry-less legacy label -> still surfaces.
    t = EmailThread(id=_uuid.uuid4(), client_email="c@x.com", subject="s",
                    category=EmailCategory.general_inquiry, status=EmailStatus.categorized,
                    is_saved=True, saved_folder="Legacy Label")
    db_session.add(t)
    db_session.commit()

    resp = logged_in_admin.get("/api/v1/emails/saved/folders")
    assert resp.status_code == 200, resp.text
    by_name = {f["name"]: f for f in resp.json()}
    assert by_name["Empty Client"]["count"] == 0
    assert by_name["Empty Client"]["source"] == "outlook"
    assert by_name["Empty Client"]["outlook_item_count"] == 147
    assert by_name["Legacy Label"]["count"] == 1  # defensive union
    assert by_name["Legacy Label"]["source"] == "app"
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py::test_list_folders_merges_registry_and_counts -q`
Expected: FAIL — `Empty Client` missing (current endpoint only lists label-derived folders) or KeyError.

- [ ] **Step 3: Rewrite `list_saved_folders`**

Replace the body of `list_saved_folders` in `backend/app/api/emails.py` (keep the decorator + signature) with:

```python
    # In-app counts by folder name (threads + messages).
    thread_rows = db.execute(
        select(EmailThread.saved_folder.label("folder"),
               func.count(EmailThread.id).label("count"))
        .where(EmailThread.is_saved == True)  # noqa: E712
        .group_by(EmailThread.saved_folder)
    ).all()
    message_rows = db.execute(
        select(EmailMessage.saved_folder.label("folder"),
               func.count(EmailMessage.id).label("count"))
        .where(EmailMessage.is_saved == True)  # noqa: E712
        .group_by(EmailMessage.saved_folder)
    ).all()

    counts: dict[str | None, dict[str, int]] = {}
    for row in thread_rows:
        counts.setdefault(row.folder, {"threads": 0, "messages": 0})["threads"] += row.count
    for row in message_rows:
        counts.setdefault(row.folder, {"threads": 0, "messages": 0})["messages"] += row.count

    registry = db.execute(select(SavedFolderRow)).scalars().all()
    reg_names = {r.name for r in registry}

    out: list[SavedFolder] = []
    # Unfiled bucket first (never a registry row).
    if None in counts:
        c = counts[None]
        out.append(SavedFolder(name=None, count=c["threads"] + c["messages"],
                               thread_count=c["threads"], message_count=c["messages"]))
    # Registry folders (empty ones included).
    for r in sorted(registry, key=lambda r: r.name.lower()):
        c = counts.get(r.name, {"threads": 0, "messages": 0})
        out.append(SavedFolder(
            id=r.id, name=r.name, parent_id=r.parent_id, source=r.source,
            outlook_item_count=r.outlook_item_count,
            count=c["threads"] + c["messages"],
            thread_count=c["threads"], message_count=c["messages"],
        ))
    # Defensive union: labels in use but not in the registry.
    for name, c in sorted(((n, c) for n, c in counts.items()
                           if n is not None and n not in reg_names),
                          key=lambda kv: kv[0].lower()):
        out.append(SavedFolder(name=name, source="app",
                               count=c["threads"] + c["messages"],
                               thread_count=c["threads"], message_count=c["messages"]))
    return out
```

Ensure `SavedFolderRow` is imported at the top of `emails.py` (add to the `from app.models.email import (...)` block).

- [ ] **Step 4: Run to verify PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/emails.py backend/tests/test_folders_registry.py
git commit -m "feat(backend): saved/folders lists registry + counts + legacy-label union"
```

---

## Task 4: Create-folder endpoint

**Files:**
- Modify: `backend/app/api/emails.py` (add `POST /saved/folders`)
- Test: `backend/tests/test_folders_registry.py`

**Interfaces:**
- Consumes: `CreateFolderRequest` (Task 2), `SavedFolderRow` (Task 1).
- Produces: `POST /api/v1/emails/saved/folders` → 201 `SavedFolder`; 409 on case-insensitive duplicate name.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_folders_registry.py
def test_create_folder_and_subfolder_and_conflict(logged_in_admin, db_session):
    r1 = logged_in_admin.post("/api/v1/emails/saved/folders", json={"name": "Parent"})
    assert r1.status_code == 201, r1.text
    parent_id = r1.json()["id"]

    r2 = logged_in_admin.post("/api/v1/emails/saved/folders",
                              json={"name": "Child", "parent_id": parent_id})
    assert r2.status_code == 201, r2.text
    assert r2.json()["parent_id"] == parent_id

    # Case-insensitive duplicate -> 409.
    r3 = logged_in_admin.post("/api/v1/emails/saved/folders", json={"name": "parent"})
    assert r3.status_code == 409, r3.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py::test_create_folder_and_subfolder_and_conflict -q`
Expected: FAIL — 404/405 (route not defined).

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/emails.py`, add above `list_saved_folders` (import `CreateFolderRequest` from schemas, `func` already imported):

```python
@router.post("/saved/folders", response_model=SavedFolder,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_csrf)])
def create_saved_folder(
    body: CreateFolderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedFolder:
    """Create a first-class folder (optionally nested under parent_id)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty.")
    exists = db.execute(
        select(SavedFolderRow).where(func.lower(SavedFolderRow.name) == name.lower())
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f'A folder named "{name}" already exists.')
    row = SavedFolderRow(name=name, parent_id=body.parent_id, source="app")
    db.add(row)
    db.flush()
    return SavedFolder(id=row.id, name=row.name, parent_id=row.parent_id,
                       source=row.source, outlook_item_count=None,
                       count=0, thread_count=0, message_count=0)
```

- [ ] **Step 4: Run to verify PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py::test_create_folder_and_subfolder_and_conflict -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/emails.py backend/tests/test_folders_registry.py
git commit -m "feat(backend): POST /saved/folders create (with parent_id, case-insensitive 409)"
```

---

## Task 5: Provider `delete_folder`

**Files:**
- Modify: `backend/app/services/email_provider.py` (base `EmailProvider` + `MSGraphProvider`)
- Test: `backend/tests/test_folder_import.py`

**Interfaces:**
- Produces: `EmailProvider.delete_folder(folder_id: str) -> None` (base no-op); `MSGraphProvider.delete_folder` issues `DELETE /users/{mailbox}/mailFolders/{folder_id}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_folder_import.py
from __future__ import annotations
from app.services.email_provider import MSGraphProvider, IMAPProvider


class _FakeResp:
    status_code = 204
    def raise_for_status(self): return None
    def json(self): return {}


class _RecordingClient:
    def __init__(self): self.calls = []
    def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url)); return _FakeResp()
    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url)); return _FakeResp()
    def delete(self, url, headers=None):
        self.calls.append(("DELETE", url)); return _FakeResp()


def _graph(monkeypatch, client):
    from app.config import get_settings
    p = MSGraphProvider.__new__(MSGraphProvider)
    p._settings = get_settings()
    p._client = client
    monkeypatch.setattr(p, "_headers", lambda: {"Authorization": "Bearer test"})
    return p


def test_delete_folder_issues_graph_delete(monkeypatch):
    client = _RecordingClient()
    p = _graph(monkeypatch, client)
    p.delete_folder("FID123")
    assert client.calls == [("DELETE", f"{p.GRAPH_BASE}/users/{p._settings.msgraph_mailbox}/mailFolders/FID123")]


def test_delete_folder_base_noop():
    p = IMAPProvider.__new__(IMAPProvider)
    assert p.delete_folder("FID") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folder_import.py -q`
Expected: FAIL — `AttributeError: delete_folder`.

- [ ] **Step 3: Implement `delete_folder`**

In `backend/app/services/email_provider.py`, add to the base `EmailProvider` next to the other folder no-ops:

```python
    def delete_folder(self, folder_id: str) -> None:
        """Delete a mail folder (recoverable move to Deleted Items). Base no-op."""
        return None
```

And in `MSGraphProvider`, right after `find_or_create_folder`:

```python
    def delete_folder(self, folder_id: str) -> None:
        """Delete a mail folder via Graph. Graph moves the folder (and its
        contents) to Deleted Items — recoverable, NOT a permanent purge. This is
        the only method that deletes a folder; import/sync/find-or-create never do."""
        mailbox = self._settings.msgraph_mailbox
        resp = self._client.delete(
            f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders/{folder_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        logger.info("MSGraph: deleted (moved to Deleted Items) folder %s", folder_id)
```

- [ ] **Step 4: Run to verify PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folder_import.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/email_provider.py backend/tests/test_folder_import.py
git commit -m "feat(backend): provider delete_folder (Graph recoverable folder delete)"
```

---

## Task 6: Delete endpoint — cascade + reflect to Outlook

**Files:**
- Modify: `backend/app/api/emails.py` (`delete_saved_folder`, line ~1487)
- Test: `backend/tests/test_folders_registry.py`

**Interfaces:**
- Consumes: `SavedFolderRow`, `settings.outlook_folder_sync`, `get_email_provider()`, `provider.delete_folder` (Task 5).
- Produces: `DELETE /api/v1/emails/saved/folders/{folder_name}` deletes the registry row + descendants, unfiles items, and (flag on + `outlook_folder_id`) calls `provider.delete_folder`; always 204.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_folders_registry.py
def _mk_folder(db, name, parent_id=None, outlook_id=None):
    row = SavedFolderRow(name=name, parent_id=parent_id, source="app",
                         outlook_folder_id=outlook_id)
    db.add(row); db.commit(); db.refresh(row); return row


def test_delete_folder_removes_row_and_descendants_and_unfiles(logged_in_admin, db_session, monkeypatch):
    import app.api.emails as emails_api
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "outlook_folder_sync", False, raising=False)
    parent = _mk_folder(db_session, "P")
    child = _mk_folder(db_session, "C", parent_id=parent.id)
    t = EmailThread(id=_uuid.uuid4(), client_email="c@x.com", subject="s",
                    category=EmailCategory.general_inquiry, status=EmailStatus.categorized,
                    is_saved=True, saved_folder="P")
    db_session.add(t); db_session.commit()

    called = []
    class _Prov:
        def delete_folder(self, fid): called.append(fid)
    monkeypatch.setattr(emails_api, "get_email_provider", lambda: _Prov())

    resp = logged_in_admin.delete("/api/v1/emails/saved/folders/P")
    assert resp.status_code == 204, resp.text
    # registry row + child gone; item unfiled; NO graph delete (flag off).
    assert db_session.get(SavedFolderRow, parent.id) is None
    assert db_session.get(SavedFolderRow, child.id) is None
    db_session.refresh(t)
    assert t.saved_folder is None and t.is_saved is True
    assert called == []


def test_delete_folder_reflects_to_outlook_when_flag_on(logged_in_admin, db_session, monkeypatch):
    import app.api.emails as emails_api
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "outlook_folder_sync", True, raising=False)
    monkeypatch.setattr(s, "email_provider", "msgraph", raising=False)
    f = _mk_folder(db_session, "SyncMe", outlook_id="OF9")

    called = []
    class _Prov:
        def delete_folder(self, fid): called.append(fid)
    monkeypatch.setattr(emails_api, "get_email_provider", lambda: _Prov())

    resp = logged_in_admin.delete("/api/v1/emails/saved/folders/SyncMe")
    assert resp.status_code == 204, resp.text
    assert called == ["OF9"]  # reflected to Outlook
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py -k delete_folder -q`
Expected: FAIL — descendants not removed / `delete_folder` not called.

- [ ] **Step 3: Extend `delete_saved_folder`**

In `backend/app/api/emails.py`, after the existing unfile logic (after `messages_unfiled = ...` and before `db.flush()`), insert registry + Outlook handling. Full replacement of the function body from the empty-name guard onward:

```python
    if not folder_name.strip():
        raise HTTPException(status_code=422, detail="Folder name cannot be empty.")

    now = datetime.now(timezone.utc)

    # Collect this folder + all descendants from the registry (recursive).
    rows = db.execute(select(SavedFolderRow)).scalars().all()
    by_parent: dict[uuid.UUID | None, list[SavedFolderRow]] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)
    root = next((r for r in rows if r.name.lower() == folder_name.lower()), None)

    to_delete: list[SavedFolderRow] = []
    if root is not None:
        stack = [root]
        while stack:
            cur = stack.pop()
            to_delete.append(cur)
            stack.extend(by_parent.get(cur.id, []))

    names_to_unfile = {folder_name} | {r.name for r in to_delete}

    # Reflect deletion to Outlook (recoverable) when enabled and synced.
    settings = get_settings()
    if settings.outlook_folder_sync and settings.email_provider.lower() == "msgraph":
        provider = get_email_provider()
        for r in to_delete:
            if r.outlook_folder_id:
                try:
                    provider.delete_folder(r.outlook_folder_id)
                except Exception as exc:  # noqa: BLE001 — never block the in-app delete
                    logger.warning("Outlook folder delete failed for %s: %s", r.name, exc)

    # Unfile every saved item under any of the affected names.
    threads_unfiled = db.execute(
        update(EmailThread)
        .where(EmailThread.is_saved == True,  # noqa: E712
               EmailThread.saved_folder.in_(names_to_unfile))
        .values(saved_folder=None, updated_at=now)
    ).rowcount or 0
    messages_unfiled = db.execute(
        update(EmailMessage)
        .where(EmailMessage.is_saved == True,  # noqa: E712
               EmailMessage.saved_folder.in_(names_to_unfile))
        .values(saved_folder=None)
    ).rowcount or 0

    # Drop the registry rows (children first isn't required — collected set).
    for r in to_delete:
        db.delete(r)

    db.flush()

    log_action(
        db,
        action="email.folder_deleted",
        entity_type="saved_folder",
        entity_id=folder_name[:64],
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"folder": folder_name,
                 "descendants": [r.name for r in to_delete if r.name != folder_name],
                 "threads_unfiled": threads_unfiled,
                 "messages_unfiled": messages_unfiled},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Ensure `get_settings`, `get_email_provider`, `logger`, and `uuid` are imported in `emails.py` (add any missing).

- [ ] **Step 4: Run to verify PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folders_registry.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/emails.py backend/tests/test_folders_registry.py
git commit -m "feat(backend): folder delete cascades registry + unfiles + reflects to Outlook (flag-gated, recoverable)"
```

---

## Task 7: Import + Sync service and endpoints

**Files:**
- Create: `backend/app/services/folder_import.py`
- Modify: `backend/app/api/emails.py` (add import + sync endpoints)
- Test: `backend/tests/test_folder_import.py`

**Interfaces:**
- Consumes: `SavedFolderRow`, `get_email_provider()`, `provider.list_mail_folders(parent_id)`, `provider.find_or_create_folder(name)`.
- Produces: `import_outlook_folders(db) -> dict{imported,updated,total}`; `sync_folders_to_outlook(db) -> dict{created,existing,total}`; endpoints `POST /api/v1/emails/saved/folders/import-from-outlook` and `POST /api/v1/emails/saved/folders/sync-to-outlook`.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_folder_import.py
import uuid
from app.models.email import SavedFolderRow


def _cfg(monkeypatch, provider_name="msgraph"):
    import app.services.folder_import as fi
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "email_provider", provider_name, raising=False)
    monkeypatch.setattr(fi, "get_settings", lambda: s)
    return fi


def test_import_upserts_and_is_idempotent(db_session, monkeypatch):
    fi = _cfg(monkeypatch)

    def _f(fid, name, children=0, count=0):
        return {"id": fid, "display_name": name, "child_folder_count": children,
                "total_item_count": count, "unread_item_count": 0}

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            if parent_id is None:
                return [_f("P1", "Client A", 1, 5)]
            if parent_id == "P1":
                return [_f("C1", "2024 Returns", 0, 3)]
            return []
    monkeypatch.setattr(fi, "get_email_provider", lambda: _Prov())

    r1 = fi.import_outlook_folders(db_session)
    assert r1["imported"] == 2 and r1["total"] == 2
    parent = db_session.execute(
        __import__("sqlalchemy").select(SavedFolderRow).where(SavedFolderRow.name == "Client A")
    ).scalar_one()
    child = db_session.execute(
        __import__("sqlalchemy").select(SavedFolderRow).where(SavedFolderRow.name == "2024 Returns")
    ).scalar_one()
    assert parent.source == "outlook" and parent.outlook_item_count == 5
    assert child.parent_id == parent.id

    r2 = fi.import_outlook_folders(db_session)
    assert r2["imported"] == 0 and r2["updated"] == 2  # idempotent, updates in place


def test_import_noop_when_not_msgraph(db_session, monkeypatch):
    fi = _cfg(monkeypatch, provider_name="imap")
    assert fi.import_outlook_folders(db_session) == {"imported": 0, "updated": 0, "total": 0}


def test_sync_creates_and_stores_id(db_session, monkeypatch):
    fi = _cfg(monkeypatch)
    db_session.add(SavedFolderRow(name="Push Me", source="app")); db_session.commit()

    class _Prov:
        def find_or_create_folder(self, name): return "NEWID"
    monkeypatch.setattr(fi, "get_email_provider", lambda: _Prov())

    res = fi.sync_folders_to_outlook(db_session)
    assert res["total"] >= 1
    row = db_session.execute(
        __import__("sqlalchemy").select(SavedFolderRow).where(SavedFolderRow.name == "Push Me")
    ).scalar_one()
    assert row.outlook_folder_id == "NEWID"
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folder_import.py -q`
Expected: FAIL — `No module named app.services.folder_import`.

- [ ] **Step 3: Write the service**

Create `backend/app/services/folder_import.py`:

```python
"""One-time (re-runnable) import of Outlook folders into the saved_folders
registry, and a push that creates app folders in Outlook. Never deletes."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email import SavedFolderRow
from app.services.email_provider import get_email_provider

logger = logging.getLogger(__name__)

_MAX_DEPTH = 6


def import_outlook_folders(db: Session) -> dict:
    """Recursively read custom Outlook folders and upsert registry rows by name
    (case-insensitive). Sets source='outlook', outlook_folder_id, item count, and
    parent_id from the Outlook tree. Idempotent. No-op unless provider is MSGraph."""
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
        for f in provider.list_mail_folders(parent_id=parent_graph_id):
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
```

- [ ] **Step 4: Add the endpoints**

In `backend/app/api/emails.py` (import `folder_import`, `FolderImportResult`, `FolderSyncResult`):

```python
@router.post("/saved/folders/import-from-outlook", response_model=FolderImportResult,
             dependencies=[Depends(require_csrf)])
def import_folders_from_outlook(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FolderImportResult:
    """One-time (re-runnable) import of all custom Outlook folders."""
    return FolderImportResult(**folder_import.import_outlook_folders(db))


@router.post("/saved/folders/sync-to-outlook", response_model=FolderSyncResult,
             dependencies=[Depends(require_csrf)])
def sync_folders_to_outlook_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FolderSyncResult:
    """Create app folders in Outlook (additive; never deletes)."""
    return FolderSyncResult(**folder_import.sync_folders_to_outlook(db))
```

Add `from app.services import folder_import` (or `import app.services.folder_import as folder_import`) to the imports.

- [ ] **Step 5: Run to verify PASS**

Run: `backend/venv/Scripts/python.exe -m pytest tests/test_folder_import.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/folder_import.py backend/app/api/emails.py backend/tests/test_folder_import.py
git commit -m "feat(backend): import-from-outlook + sync-to-outlook folder endpoints"
```

---

## Task 8: Frontend types + hooks

**Files:**
- Modify: `frontend/src/lib/types.ts` (`SavedFolder`, line ~158)
- Modify: `frontend/src/hooks/use-emails.ts`
- Test: `npx tsc --noEmit`

**Interfaces:**
- Produces: `SavedFolder` gains `id?: string`, `parent_id?: string | null`, `source?: "app" | "outlook" | null`, `outlook_item_count?: number | null`. New async fns `createFolder(body)`, `importOutlookFolders()`, `syncFoldersToOutlook()`. `deleteSavedFolder` already exists.

- [ ] **Step 1: Extend the type**

In `frontend/src/lib/types.ts`, update `SavedFolder` (line ~158):

```typescript
export interface SavedFolder {
  id?: string;
  name: string | null;
  parent_id?: string | null;
  source?: "app" | "outlook" | null;
  outlook_item_count?: number | null;
  count: number;
  thread_count: number;
  message_count: number;
}
```

- [ ] **Step 2: Add the hooks**

In `frontend/src/hooks/use-emails.ts`, add near the other folder helpers:

```typescript
export function createFolder(body: { name: string; parent_id?: string | null }): Promise<SavedFolder> {
  return api.post<SavedFolder>("/api/v1/emails/saved/folders", body);
}

export interface FolderImportResult { imported: number; updated: number; total: number }
export interface FolderSyncResult { created: number; existing: number; total: number }

export function importOutlookFolders(): Promise<FolderImportResult> {
  return api.post<FolderImportResult>("/api/v1/emails/saved/folders/import-from-outlook", {});
}
export function syncFoldersToOutlook(): Promise<FolderSyncResult> {
  return api.post<FolderSyncResult>("/api/v1/emails/saved/folders/sync-to-outlook", {});
}
```

Import `SavedFolder` in the file if not already imported.

- [ ] **Step 3: Typecheck**

Run (cwd `frontend`): `npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/hooks/use-emails.ts
git commit -m "feat(frontend): folder registry types + create/import/sync hooks"
```

---

## Task 9: Registry-driven rail tree + subfolder create

**Files:**
- Modify: `frontend/src/app/(dashboard)/saved/page.tsx`
- Test: `npx tsc --noEmit` + Playwright manual check

**Interfaces:**
- Consumes: `useSavedFolders()` (now returns `parent_id`/`source`/`outlook_item_count`), `createFolder` (Task 8).
- Produces: a rail that renders `namedFolders` as a tree by `parent_id`, each row with the compact style, an active-filter click, a hover delete icon (wired in Task 10), and a hover "+" to create a subfolder via `createFolder({name, parent_id})`, then `mutateFolders()`.

- [ ] **Step 1: Build the tree from flat folders**

In `saved/page.tsx`, replace the flat `namedFolders.map(...)` render inside the unified Folders block with a recursive tree. Add a helper above the component:

```typescript
interface FolderNodeData { folder: SavedFolder; children: FolderNodeData[] }

function buildFolderTree(folders: SavedFolder[]): FolderNodeData[] {
  const byId = new Map<string, FolderNodeData>();
  folders.forEach((f) => { if (f.id) byId.set(f.id, { folder: f, children: [] }); });
  const roots: FolderNodeData[] = [];
  folders.forEach((f) => {
    if (!f.id) return;
    const node = byId.get(f.id)!;
    const parent = f.parent_id ? byId.get(f.parent_id) : undefined;
    if (parent) parent.children.push(node); else roots.push(node);
  });
  return roots;
}
```

- [ ] **Step 2: Render the tree recursively**

Replace the `namedFolders.filter(...).map(...)` block with a `<FolderTreeRow>` recursion (depth indent mirrors the retired OutlookFolderTree: `paddingLeft: depth*12`). Each row uses the compact `FolderRailItem` styling, calls `setActiveFolder(f.name)`, shows `count`, exposes delete + "+subfolder" on hover. Filtering: when `folderQuery` is set, show a node if it or any descendant matches. Retire `<OutlookFolderTree/>` import/usage on this page.

```tsx
function FolderTreeRow({
  node, depth, activeFolder, filter, onSelect, onDelete, onAddChild,
}: {
  node: FolderNodeData; depth: number; activeFolder: string;
  filter: string; onSelect: (name: string) => void;
  onDelete: (f: SavedFolder) => void; onAddChild: (parent: SavedFolder) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const f = node.folder;
  const nameMatch = !filter || (f.name ?? "").toLowerCase().includes(filter);
  const descMatch = node.children.some((c) => subtreeMatches(c, filter));
  if (filter && !nameMatch && !descMatch) return null;
  return (
    <div>
      <div className="group/row relative flex items-center rounded-md hover:bg-accent"
           style={{ paddingLeft: `${depth * 12}px` }}>
        <button type="button"
          onClick={() => node.children.length && setExpanded((v) => !v)}
          className={cn("flex items-center justify-center w-4 h-6 shrink-0",
                        !node.children.length && "invisible")}
          aria-label={expanded ? "Collapse" : "Expand"}>
          <ChevronRight className={cn("w-3 h-3 transition-transform", expanded && "rotate-90")} />
        </button>
        <button type="button" onClick={() => f.name && onSelect(f.name)}
          className={cn("flex-1 flex items-center gap-1.5 py-1 pr-2 text-sm text-left min-w-0",
                        activeFolder === f.name ? "text-foreground font-medium" : "text-muted-foreground")}>
          <Folder className="w-3.5 h-3.5 shrink-0" strokeWidth={1.75} />
          <span className="flex-1 truncate">{f.name}</span>
          <span className="text-[10px] tabular-nums text-muted-foreground">{f.count}</span>
        </button>
        <button type="button" onClick={() => onAddChild(f)}
          className="shrink-0 p-0.5 opacity-0 group-hover/row:opacity-100 text-muted-foreground/60 hover:text-foreground"
          title="New subfolder"><Plus className="w-3 h-3" /></button>
        <button type="button" onClick={() => onDelete(f)}
          className="shrink-0 mr-1 p-0.5 opacity-0 group-hover/row:opacity-100 text-muted-foreground/60 hover:text-destructive"
          title="Delete folder"><Trash2 className="w-3 h-3" /></button>
      </div>
      {expanded && node.children.map((c) => (
        <FolderTreeRow key={c.folder.id} node={c} depth={depth + 1} activeFolder={activeFolder}
          filter={filter} onSelect={onSelect} onDelete={onDelete} onAddChild={onAddChild} />
      ))}
    </div>
  );
}

function subtreeMatches(node: FolderNodeData, filter: string): boolean {
  if (!filter) return true;
  if ((node.folder.name ?? "").toLowerCase().includes(filter)) return true;
  return node.children.some((c) => subtreeMatches(c, filter));
}
```

Wire `onAddChild` to a small prompt-or-inline create that calls `createFolder({ name, parent_id: parent.id })` then `mutateFolders()`; `onDelete` opens the Task 10 dialog. Import `ChevronRight`, `Plus` from `lucide-react`.

- [ ] **Step 3: Typecheck**

Run (cwd `frontend`): `npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 4: Manual check**

Start dev servers; on `/saved`, confirm folders render as a tree, subfolders indent/expand, the filter box narrows the tree, clicking a folder filters the saved list, and a "+" creates a subfolder that appears nested.

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(dashboard)/saved/page.tsx"
git commit -m "feat(frontend): registry-driven folder tree in Saved rail + subfolder create"
```

---

## Task 10: Folder delete confirm dialog (with Outlook-impact warning)

**Files:**
- Create: `frontend/src/components/emails/folder-delete-dialog.tsx`
- Modify: `frontend/src/app/(dashboard)/saved/page.tsx` (wire it)
- Test: `npx tsc --noEmit` + manual

**Interfaces:**
- Consumes: `deleteSavedFolder(name)` (existing hook), `SavedFolder.outlook_item_count`.
- Produces: `<FolderDeleteDialog folder onClose onDeleted />` — confirm dialog; when `outlook_item_count > 0` shows the recoverable-move warning; on confirm calls `deleteSavedFolder(folder.name)`, toasts, `onDeleted()`.

- [ ] **Step 1: Create the dialog**

```tsx
"use client";
import { useState } from "react";
import { deleteSavedFolder } from "@/hooks/use-emails";
import type { SavedFolder } from "@/lib/types";
import { toast } from "@/components/ui/use-toast"; // match existing toast import in the repo

export function FolderDeleteDialog({
  folder, onClose, onDeleted,
}: { folder: SavedFolder; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const n = folder.outlook_item_count ?? 0;
  async function confirm() {
    if (!folder.name) return;
    setBusy(true);
    try {
      await deleteSavedFolder(folder.name);
      toast({ title: `Deleted "${folder.name}"` });
      onDeleted();
    } catch (e) {
      toast({ title: "Couldn't delete folder", variant: "destructive" });
    } finally {
      setBusy(false);
      onClose();
    }
  }
  return (
    <ConfirmShell title={`Delete "${folder.name}"?`} onClose={onClose}>
      <p>This removes the folder from the app. Items filed here stay saved and move to "No folder".</p>
      {n > 0 && (
        <p className="mt-2 text-amber-600">
          This will also move {n} email{n === 1 ? "" : "s"} in Outlook to Deleted Items
          (recoverable).
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} disabled={busy}>Cancel</button>
        <button onClick={confirm} disabled={busy} className="text-destructive">
          {busy ? "Deleting…" : "Delete"}
        </button>
      </div>
    </ConfirmShell>
  );
}
```

Use the repo's existing dialog primitive (mirror `save-thread-dialog.tsx` / the `<DeleteDialog>` pattern) instead of the placeholder `ConfirmShell` — match the app's Base UI dialog + button classes so styling is consistent.

- [ ] **Step 2: Wire into the page**

In `saved/page.tsx`, add `const [pendingFolderDelete, setPendingFolderDelete] = useState<SavedFolder | null>(null)`, pass `onDelete={setPendingFolderDelete}` to `FolderTreeRow`, and render `{pendingFolderDelete && <FolderDeleteDialog folder={pendingFolderDelete} onClose={() => setPendingFolderDelete(null)} onDeleted={() => { mutateFolders(); if (activeFolder === pendingFolderDelete.name) setActiveFolder(ALL_FOLDERS); }} />}`.

- [ ] **Step 3: Typecheck + manual**

Run (cwd `frontend`): `npx tsc --noEmit` (exit 0). Manual: deleting a folder shows the confirm; a folder with an Outlook count shows the amber warning; confirming removes it and unfiles items.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/emails/folder-delete-dialog.tsx "frontend/src/app/(dashboard)/saved/page.tsx"
git commit -m "feat(frontend): folder delete confirm dialog with Outlook-impact warning"
```

---

## Task 11: Save/Move dialog — searchable folder-tree targets

**Files:**
- Modify: `frontend/src/components/emails/save-thread-dialog.tsx`
- Test: `npx tsc --noEmit` + manual

**Interfaces:**
- Consumes: `useSavedFolders()` (full registry), existing `saveThread`/`saveMessage`.
- Produces: the folder picker lists the full registry (all folders including imported Outlook ones) with a search box; selecting one files by `name` as today.

- [ ] **Step 1: Add search + full list**

In `save-thread-dialog.tsx`, where the folder options render, add a search `<input>` bound to local `query` state and filter the `useSavedFolders()` list by name (case-insensitive). Keep "No folder" and "New folder…". Since the list can be large (hundreds after import), cap the visible rows with scroll (`max-h-64 overflow-y-auto`).

- [ ] **Step 2: Typecheck + manual**

Run (cwd `frontend`): `npx tsc --noEmit` (exit 0). Manual: open "Save this thread", type in the search, confirm an imported Outlook folder is selectable and saving files the thread under it (visible on the rail).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/emails/save-thread-dialog.tsx
git commit -m "feat(frontend): searchable full-registry folder picker in Save/Move dialog"
```

---

## Task 12: Settings → Folders section (Import / Sync buttons)

**Files:**
- Modify: `frontend/src/app/(dashboard)/settings/**` (the settings page; add a Folders section)
- Test: `npx tsc --noEmit` + manual

**Interfaces:**
- Consumes: `importOutlookFolders()`, `syncFoldersToOutlook()` (Task 8).
- Produces: two buttons with result toasts and copy stating neither deletes anything in Outlook.

- [ ] **Step 1: Add the section**

In the settings page, add a "Folders" card with two buttons:

```tsx
async function onImport() {
  const r = await importOutlookFolders();
  toast({ title: `Imported ${r.imported} folders`, description: `${r.updated} updated` });
  // mutate the saved-folders SWR key if the settings page shows it
}
async function onSync() {
  const r = await syncFoldersToOutlook();
  toast({ title: `Synced to Outlook`, description: `${r.created} created, ${r.existing} already there` });
}
```

Buttons: "Import from Outlook" (`onImport`), "Sync to Outlook" (`onSync`), each with a busy state. Helper text: "Import pulls your Outlook folders into the app. Sync creates your app folders in Outlook. Neither ever deletes anything in Outlook."

- [ ] **Step 2: Typecheck + manual**

Run (cwd `frontend`): `npx tsc --noEmit` (exit 0). Manual: click Import → folders appear on the Saved rail; click Sync → toast reports created/existing.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/(dashboard)/settings"
git commit -m "feat(frontend): Settings Folders section — Import from / Sync to Outlook"
```

---

## Task 13: Full-suite regression + retire live OutlookFolderTree

**Files:**
- Modify: `frontend/src/components/emails/outlook-folder-tree.tsx` (delete if now unused) 
- Test: full backend suite + `npx tsc --noEmit`

- [ ] **Step 1: Confirm no remaining imports of the live tree**

Run: `grep -rn "OutlookFolderTree\|useOutlookFolders" frontend/src` — if only the (now-unused) component file and hook remain, delete `outlook-folder-tree.tsx` and remove `useOutlookFolders` if nothing else uses it. (The registry now supplies folders; the live read-through is retired.)

- [ ] **Step 2: Backend full suite**

Run (cwd `backend`): `backend/venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 3: Frontend typecheck + build**

Run (cwd `frontend`): `npx tsc --noEmit && npm run build`
Expected: exit 0 (stop the dev server first if `.next` is locked).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: retire live OutlookFolderTree (registry supplies folders); full-suite green"
```

---

## Self-Review

**Spec coverage:**
- Data model / migration 021 + backfill → Task 1. ✔
- Schemas → Task 2. ✔
- List (registry + counts + union + `outlook_item_count`) → Task 3. ✔
- Create (with parent, 409) → Task 4. ✔
- Provider `delete_folder` → Task 5. ✔
- Delete (cascade + unfile + Outlook reflect, flag-gated, recoverable) → Task 6. ✔
- Import (recursive, idempotent, item count, parent linkage, non-MSGraph no-op) + Sync (store id, create-only) → Task 7. ✔
- Frontend types/hooks → Task 8; rail tree + subfolder → Task 9; delete dialog + warning → Task 10; save-dialog targets → Task 11; Settings buttons → Task 12; retire live tree + regression → Task 13. ✔
- Invariants (import/sync/create never delete; delete confirmed + recoverable + flag-gated) → asserted in Tasks 5–7. ✔
- Out of scope (email two-way delete, same-named subfolders, Outlook counts as source of truth) → not built. ✔

**Placeholder scan:** `ConfirmShell`/toast import in Tasks 10/12 explicitly instruct mirroring the repo's existing dialog/toast primitives (named, not vague). No TBD/TODO.

**Type consistency:** `SavedFolderRow` fields, `SavedFolder` extra fields, `import_outlook_folders`/`sync_folders_to_outlook` return dicts (`imported/updated/total`, `created/existing/total`), and `provider.delete_folder(folder_id)` are used consistently across backend tasks and mirrored in the frontend hook result interfaces.
