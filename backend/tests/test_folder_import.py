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
