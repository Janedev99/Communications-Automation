"""Backward-compat tests for releases that pre-date the structured shape.

Releases with body-only (no summary, no highlights) must continue to be
served by /releases/latest-unread and the admin list, with the new
fields exposed as null/[]. Frontend renderers fall back to the legacy
markdown body in that case (handled by ReleaseNoteCard, not this layer).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus
from app.models.user import User, UserRole
from app.services.auth import create_session, create_user, generate_csrf_token


def _make_user(*, email: str, role: UserRole = UserRole.staff) -> User:
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="Legacy Compat Tester",
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


def _insert_legacy_release(*, created_by: User, body: str, published_at: datetime) -> Release:
    """Simulate a release row that pre-dates the structured-shape migration:
    body is set, summary/highlights are null/empty (matching the migration backfill).
    """
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title="Legacy Release",
            body=body,
            summary=None,
            highlights=[],
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


def test_legacy_release_served_via_latest_unread(app_instance):
    """A pre-migration release (body only, no summary/highlights) is still served
    via /releases/latest-unread with body populated and summary=null, highlights=[]."""
    user = _make_user(email="legacy-1@compat.com")
    legacy = _insert_legacy_release(
        created_by=user,
        body="## What's New\n\n- Some legacy bullet point\n- Another one",
        # Use a far-future date to ensure this wins the "latest" race against
        # other test data accumulated in the shared SQLite DB.
        published_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
    )

    tc = _make_authenticated_client(app_instance, user)
    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    data = res.json()
    assert data is not None, "Expected the legacy release to be returned"
    assert data["id"] == str(legacy.id)
    assert data["body"] is not None
    assert "Some legacy bullet point" in data["body"]
    assert data["summary"] is None
    assert data["highlights"] == []

    # Cleanup: backdate so we don't pollute downstream tests in the shared DB.
    db = _db_mod.SessionLocal()
    try:
        row = db.query(Release).filter_by(id=legacy.id).one()
        row.published_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    finally:
        db.close()


def test_legacy_release_appears_in_admin_list(app_instance):
    """Legacy releases also surface via the admin list endpoint with body/null/[] shape."""
    admin = _make_user(email="legacy-admin-1@compat.com", role=UserRole.admin)
    legacy = _insert_legacy_release(
        created_by=admin,
        body="## Legacy admin body",
        published_at=datetime(2020, 6, 1, tzinfo=timezone.utc),
    )

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.get("/api/v1/admin/releases")
    assert res.status_code == 200

    found = next((r for r in res.json() if r["id"] == str(legacy.id)), None)
    assert found is not None
    assert found["body"] == "## Legacy admin body"
    assert found["summary"] is None
    assert found["highlights"] == []
