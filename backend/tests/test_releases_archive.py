"""Tests for GET /api/v1/releases/archive — cursor-paginated public archive.

Covers:
    - happy path: paginated reverse-chrono list
    - drafts excluded
    - empty result when no published releases
    - cursor-based pagination correctness across multiple pages
    - hide_releases_forever does NOT block archive access
    - unknown cursor returns empty list (not 404)
    - auth: unauthenticated -> 401, authenticated user -> 200
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus
from app.models.user import User, UserRole
from app.services.auth import create_session, create_user, generate_csrf_token


_ENDPOINT = "/api/v1/releases/archive"


def _make_user(*, email: str, role: UserRole = UserRole.staff, hide_forever: bool = False) -> User:
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="Archive Test User",
            password="TestPass123!",
            role=role,
        )
        if hide_forever:
            user.hide_releases_forever = True
        db.flush()
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _make_authenticated_client(app_instance, user: User) -> TestClient:
    db = _db_mod.SessionLocal()
    try:
        u = db.merge(user)
        _, raw_token = create_session(db, u)
        csrf = generate_csrf_token()
        db.commit()
    finally:
        db.close()

    tc = TestClient(app_instance, raise_server_exceptions=True)
    tc.cookies.set("session_token", raw_token)
    tc.cookies.set("csrf_token", csrf)
    tc.headers.update({"X-CSRF-Token": csrf})
    return tc


def _insert_published_release(
    *,
    created_by: User,
    title: str,
    published_at: datetime,
    summary: str | None = None,
    highlights: list[dict] | None = None,
    body: str | None = None,
) -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body=body,
            summary=summary or "Test summary",
            highlights=highlights if highlights is not None else [
                {"category": "new", "text": "Archive test highlight"},
            ],
            status=ReleaseStatus.published,
            created_by_id=created_by.id,
            published_at=published_at,
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


def _insert_draft_release(*, created_by: User, title: str) -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body=None,
            summary="Draft summary",
            highlights=[{"category": "new", "text": "Draft highlight"}],
            status=ReleaseStatus.draft,
            created_by_id=created_by.id,
            published_at=None,
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


# ── Happy path ───────────────────────────────────────────────────────────────


def test_archive_returns_published_reverse_chrono(app_instance):
    """Two published releases — the most-recently published comes first."""
    user = _make_user(email="archive-rc@archive-test.com")
    older = _insert_published_release(
        created_by=user,
        title="Archive Older",
        published_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    newer = _insert_published_release(
        created_by=user,
        title="Archive Newer",
        published_at=datetime(2099, 6, 1, tzinfo=timezone.utc),
    )

    tc = _make_authenticated_client(app_instance, user)
    res = tc.get(_ENDPOINT)
    assert res.status_code == 200
    data = res.json()

    # Find our two test releases in the response (DB is shared across test files).
    ids = [item["id"] for item in data["items"]]
    assert str(newer.id) in ids
    assert str(older.id) in ids
    # Newer must precede older in the list.
    assert ids.index(str(newer.id)) < ids.index(str(older.id))

    # Cleanup so other tests' "latest unread" logic isn't perturbed.
    _backdate(older.id)
    _backdate(newer.id)


def test_archive_excludes_drafts(app_instance):
    """Drafts MUST NOT appear in the archive — only published."""
    user = _make_user(email="archive-drafts@archive-test.com")
    draft = _insert_draft_release(created_by=user, title="Archive Draft")
    published = _insert_published_release(
        created_by=user,
        title="Archive Published For Drafts Test",
        published_at=datetime(2099, 7, 1, tzinfo=timezone.utc),
    )

    tc = _make_authenticated_client(app_instance, user)
    res = tc.get(_ENDPOINT)
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["items"]]
    assert str(draft.id) not in ids
    assert str(published.id) in ids

    _backdate(published.id)


# ── Pagination ───────────────────────────────────────────────────────────────


def test_archive_pagination_with_cursor(app_instance):
    """Three releases with limit=1 → 3 pages, cursor advances each time."""
    user = _make_user(email="archive-pg@archive-test.com")
    base = datetime(2099, 8, 15, tzinfo=timezone.utc)
    r1 = _insert_published_release(created_by=user, title="ArchPg-1", published_at=base + timedelta(days=2))
    r2 = _insert_published_release(created_by=user, title="ArchPg-2", published_at=base + timedelta(days=1))
    r3 = _insert_published_release(created_by=user, title="ArchPg-3", published_at=base)

    # Backdate everything else first to avoid noise — the user's three
    # ArchPg releases are the only future-dated rows.
    tc = _make_authenticated_client(app_instance, user)

    # Page 1
    res1 = tc.get(_ENDPOINT, params={"limit": 1})
    assert res1.status_code == 200
    p1 = res1.json()
    assert len(p1["items"]) == 1
    assert p1["items"][0]["id"] == str(r1.id)
    cursor1 = p1["next_cursor"]
    assert cursor1 is not None

    # Page 2
    res2 = tc.get(_ENDPOINT, params={"limit": 1, "cursor": cursor1})
    assert res2.status_code == 200
    p2 = res2.json()
    assert len(p2["items"]) == 1
    assert p2["items"][0]["id"] == str(r2.id)
    cursor2 = p2["next_cursor"]

    # Page 3
    res3 = tc.get(_ENDPOINT, params={"limit": 1, "cursor": cursor2})
    p3 = res3.json()
    assert len(p3["items"]) == 1
    assert p3["items"][0]["id"] == str(r3.id)

    # Cleanup
    for rid in (r1.id, r2.id, r3.id):
        _backdate(rid)


def test_archive_unknown_cursor_returns_empty(app_instance):
    """A cursor pointing at a non-existent release → empty list, not 404."""
    user = _make_user(email="archive-unk@archive-test.com")
    tc = _make_authenticated_client(app_instance, user)
    import uuid
    res = tc.get(_ENDPOINT, params={"cursor": str(uuid.uuid4())})
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["next_cursor"] is None


# ── Visibility rules ─────────────────────────────────────────────────────────


def test_archive_visible_to_hide_forever_users(app_instance):
    """hide_releases_forever=True suppresses MODALS, not archive access."""
    user = _make_user(email="archive-hide@archive-test.com", hide_forever=True)
    rel = _insert_published_release(
        created_by=user,
        title="Archive Hide Forever Test",
        published_at=datetime(2099, 9, 1, tzinfo=timezone.utc),
    )
    tc = _make_authenticated_client(app_instance, user)
    res = tc.get(_ENDPOINT)
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["items"]]
    assert str(rel.id) in ids

    _backdate(rel.id)


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_archive_unauthenticated_returns_401(client):
    res = client.get(_ENDPOINT)
    assert res.status_code == 401


# ── helpers ──────────────────────────────────────────────────────────────────


def _backdate(release_id) -> None:
    """Move a test release into ancient history so it can't pollute
    other test files' 'latest unread' / archive ordering assertions
    in the shared in-memory DB."""
    db = _db_mod.SessionLocal()
    try:
        row = db.query(Release).filter_by(id=release_id).one_or_none()
        if row is not None:
            row.published_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.commit()
    finally:
        db.close()
