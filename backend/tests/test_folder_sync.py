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
