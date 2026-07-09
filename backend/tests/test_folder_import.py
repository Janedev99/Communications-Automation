from __future__ import annotations
from sqlalchemy import select

from app.services.email_provider import MSGraphProvider, IMAPProvider
from app.models.email import SavedFolderRow


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
        select(SavedFolderRow).where(SavedFolderRow.name == "Client A")
    ).scalar_one()
    child = db_session.execute(
        select(SavedFolderRow).where(SavedFolderRow.name == "2024 Returns")
    ).scalar_one()
    assert parent.source == "outlook" and parent.outlook_item_count == 5
    assert child.parent_id == parent.id

    r2 = fi.import_outlook_folders(db_session)
    assert r2["imported"] == 0 and r2["updated"] == 2  # idempotent, updates in place


def test_import_excludes_builtin_top_level_but_keeps_inbox_children(db_session, monkeypatch):
    """Mirrors /mailbox/folders?custom=true: built-in defaults (Inbox, Sent
    Items, ...) never become registry rows at the top level, but a custom
    folder living under Inbox (a common spot for Jane's per-client folders)
    is imported as if it were a root folder. A plain custom root folder is
    also imported."""
    fi = _cfg(monkeypatch)

    def _f(fid, name, children=0, count=0):
        return {"id": fid, "display_name": name, "child_folder_count": children,
                "total_item_count": count, "unread_item_count": 0}

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            if parent_id is None:
                return [
                    _f("INBOX_ID", "Inbox", 1, 0),
                    _f("SENT_ID", "Sent Items", 0, 0),
                    _f("ROOT_ID", "Root Custom", 0, 0),
                ]
            if parent_id == "INBOX_ID":
                return [_f("ICHILD_ID", "Inbox Custom Child", 0, 0)]
            return []
    monkeypatch.setattr(fi, "get_email_provider", lambda: _Prov())

    result = fi.import_outlook_folders(db_session)
    assert result["imported"] == 2  # Root Custom + Inbox Custom Child only

    names = {r.name for r in db_session.execute(select(SavedFolderRow)).scalars().all()}
    assert "Root Custom" in names
    assert "Inbox Custom Child" in names
    assert "Inbox" not in names
    assert "Sent Items" not in names

    promoted = db_session.execute(
        select(SavedFolderRow).where(SavedFolderRow.name == "Inbox Custom Child")
    ).scalar_one()
    assert promoted.parent_id is None  # Inbox children are promoted to top level


def test_import_is_best_effort_per_level(db_session, monkeypatch):
    """A Graph failure while listing one folder's children must not abort the
    whole import (get_db would otherwise roll back the session and the caller
    gets a 500, per the design doc's Error handling section). The top-level
    custom folder that was already upserted before the failure must survive,
    and the call must return partial success rather than raising."""
    fi = _cfg(monkeypatch)

    def _f(fid, name, children=0, count=0):
        return {"id": fid, "display_name": name, "child_folder_count": children,
                "total_item_count": count, "unread_item_count": 0}

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            if parent_id is None:
                return [_f("R1", "Resilient Client", 1, 1)]
            if parent_id == "R1":
                raise RuntimeError("Graph 503")
            return []
    monkeypatch.setattr(fi, "get_email_provider", lambda: _Prov())

    result = fi.import_outlook_folders(db_session)
    assert result["imported"] >= 1

    row = db_session.execute(
        select(SavedFolderRow).where(SavedFolderRow.name == "Resilient Client")
    ).scalar_one()
    assert row.outlook_folder_id == "R1"


def test_import_top_level_list_failure_returns_empty(db_session, monkeypatch):
    """If even the root-level Graph call fails, the whole import is a no-op
    best-effort result — it must not raise or corrupt the registry."""
    fi = _cfg(monkeypatch)

    class _Prov:
        def list_mail_folders(self, parent_id=None):
            raise RuntimeError("Graph down")
    monkeypatch.setattr(fi, "get_email_provider", lambda: _Prov())

    result = fi.import_outlook_folders(db_session)
    assert result == {"imported": 0, "updated": 0, "total": 0}


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
        select(SavedFolderRow).where(SavedFolderRow.name == "Push Me")
    ).scalar_one()
    assert row.outlook_folder_id == "NEWID"
