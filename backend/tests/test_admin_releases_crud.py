"""Tests for admin CRUD endpoints: /api/v1/admin/releases.

Auth pattern: mirrors test_releases_dismiss.py — uses _make_authenticated_client()
with create_session() + generate_csrf_token().

DB is shared in-memory SQLite (StaticPool); data accumulates across tests.
Use distinct emails (crud-*@crud-test.com) to avoid collisions.
All published releases are backdated to datetime(2020, 1, 1, tzinfo=timezone.utc)
so they don't pollute the "latest unread" logic in other test files.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus
from app.models.user import User, UserRole
from app.services.auth import create_session, create_user, generate_csrf_token


# =============================================================================
# Helpers
# =============================================================================

def _make_user(*, email: str, role: UserRole = UserRole.staff) -> User:
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="CRUD Test User",
            password="TestPass123!",
            role=role,
        )
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


def _make_draft_release(*, created_by: User, title: str = "CRUD Draft Release") -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body="## draft body",
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


def _make_published_release(*, created_by: User, title: str = "CRUD Published Release") -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body="## published body",
            status=ReleaseStatus.published,
            created_by_id=created_by.id,
            # Backdate so it never appears as "latest" for other test modules
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


def _get_release(release_id) -> Release | None:
    db = _db_mod.SessionLocal()
    try:
        return db.query(Release).filter_by(id=release_id).one_or_none()
    finally:
        db.close()


# =============================================================================
# Tests
# =============================================================================

def test_list_returns_drafts_and_published(app_instance):
    """Admin GET /admin/releases returns both drafts and published, ordered created_at DESC.

    Ordering is verified by inserting one release with a backdated created_at and
    one with a future-ish timestamp, then asserting the newer one ranks first.
    Using distinct created_at values avoids non-determinism from same-millisecond
    inserts in the shared StaticPool SQLite DB.
    """
    from datetime import timedelta

    admin = _make_user(email="crud-admin-list@crud-test.com", role=UserRole.admin)

    # Insert the "older" release first with an explicit past created_at
    db = _db_mod.SessionLocal()
    try:
        older_rel = Release(
            title="CRUD List Older Draft",
            body="## older",
            status=ReleaseStatus.draft,
            created_by_id=admin.id,
            published_at=None,
        )
        older_rel.created_at = datetime(2021, 6, 1, tzinfo=timezone.utc)
        db.add(older_rel)
        db.commit()
        db.refresh(older_rel)
        older_id = older_rel.id
    finally:
        db.close()

    # Insert the "newer" release with a later created_at
    db = _db_mod.SessionLocal()
    try:
        newer_rel = Release(
            title="CRUD List Newer Published",
            body="## newer",
            status=ReleaseStatus.published,
            created_by_id=admin.id,
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        newer_rel.created_at = datetime(2022, 6, 1, tzinfo=timezone.utc)
        db.add(newer_rel)
        db.commit()
        db.refresh(newer_rel)
        newer_id = newer_rel.id
    finally:
        db.close()

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.get("/api/v1/admin/releases")

    assert res.status_code == 200
    data = res.json()

    ids_in_response = [r["id"] for r in data]
    assert str(older_id) in ids_in_response
    assert str(newer_id) in ids_in_response

    # Newer (created 2022) should appear before older (created 2021) in DESC order
    newer_idx = ids_in_response.index(str(newer_id))
    older_idx = ids_in_response.index(str(older_id))
    assert newer_idx < older_idx


def test_list_forbidden_for_staff(app_instance):
    """Staff user (non-admin) gets 403 on GET /admin/releases."""
    staff = _make_user(email="crud-staff-list@crud-test.com", role=UserRole.staff)

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.get("/api/v1/admin/releases")

    assert res.status_code == 403


def test_create_draft_returns_201_and_admin_response(app_instance):
    """POST /admin/releases creates a draft; response has status=draft and created_by.email."""
    admin = _make_user(email="crud-admin-create@crud-test.com", role=UserRole.admin)

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.post(
        "/api/v1/admin/releases",
        json={
            "title": "New Draft Release",
            "body": "## Content here",
            "generated_from": None,
            "commit_sha_at_release": None,
        },
    )

    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "draft"
    assert data["title"] == "New Draft Release"
    assert data["created_by"]["email"] == admin.email
    assert data["published_at"] is None
    assert "id" in data


def test_patch_draft_works(app_instance):
    """PATCH /admin/releases/{id} on a draft updates title/body; returns 200 with updated data."""
    admin = _make_user(email="crud-admin-patch@crud-test.com", role=UserRole.admin)
    draft = _make_draft_release(created_by=admin, title="Original Title")

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.patch(
        f"/api/v1/admin/releases/{draft.id}",
        json={"title": "Updated Title", "body": "## Updated body"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Updated Title"
    assert data["body"] == "## Updated body"

    # Verify persisted in DB
    updated = _get_release(draft.id)
    assert updated is not None
    assert updated.title == "Updated Title"


def test_patch_published_returns_409(app_instance):
    """PATCH on a published release returns 409 (immutable)."""
    admin = _make_user(email="crud-admin-patch-pub@crud-test.com", role=UserRole.admin)
    published = _make_published_release(created_by=admin, title="Immutable Release")

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.patch(
        f"/api/v1/admin/releases/{published.id}",
        json={"title": "Attempt to change"},
    )

    assert res.status_code == 409


def test_delete_draft_works(app_instance):
    """DELETE /admin/releases/{id} on a draft returns 204; row is gone from DB."""
    admin = _make_user(email="crud-admin-delete@crud-test.com", role=UserRole.admin)
    draft = _make_draft_release(created_by=admin, title="Draft To Delete")
    draft_id = draft.id

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.delete(f"/api/v1/admin/releases/{draft_id}")

    assert res.status_code == 204

    # Row should be gone
    gone = _get_release(draft_id)
    assert gone is None


def test_delete_published_returns_409(app_instance):
    """DELETE on a published release returns 409; row still exists."""
    admin = _make_user(email="crud-admin-del-pub@crud-test.com", role=UserRole.admin)
    published = _make_published_release(created_by=admin, title="Published Not Deletable")

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.delete(f"/api/v1/admin/releases/{published.id}")

    assert res.status_code == 409

    # Row should still exist
    still_there = _get_release(published.id)
    assert still_there is not None


# =============================================================================
# Bonus tests
# =============================================================================

def test_patch_404_on_nonexistent(app_instance):
    """PATCH on a random UUID that doesn't exist returns 404."""
    admin = _make_user(email="crud-admin-404p@crud-test.com", role=UserRole.admin)

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.patch(
        f"/api/v1/admin/releases/{uuid.uuid4()}",
        json={"title": "Ghost"},
    )

    assert res.status_code == 404


def test_delete_404_on_nonexistent(app_instance):
    """DELETE on a random UUID that doesn't exist returns 404."""
    admin = _make_user(email="crud-admin-404d@crud-test.com", role=UserRole.admin)

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.delete(f"/api/v1/admin/releases/{uuid.uuid4()}")

    assert res.status_code == 404


def test_create_requires_auth(client):
    """Unauthenticated POST returns 401 or 403 (CSRF fires first for unauthenticated client)."""
    res = client.post(
        "/api/v1/admin/releases",
        json={"title": "Unauthorized", "body": "## body"},
    )
    assert res.status_code in (401, 403)


def test_patch_requires_auth(client):
    """Unauthenticated PATCH returns 401 or 403."""
    res = client.patch(
        f"/api/v1/admin/releases/{uuid.uuid4()}",
        json={"title": "Unauthorized"},
    )
    assert res.status_code in (401, 403)


def test_delete_requires_auth(client):
    """Unauthenticated DELETE returns 401 or 403."""
    res = client.delete(f"/api/v1/admin/releases/{uuid.uuid4()}")
    assert res.status_code in (401, 403)
