"""Iteration A: read-only Outlook folder listing.

Provider-level tests use a fake httpx-style client recording every request so
we can assert (a) correct URLs, (b) @odata.nextLink pagination, and (c) the
HARD INVARIANT that only GET is ever issued (never DELETE/POST/PATCH).
"""
from __future__ import annotations

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
