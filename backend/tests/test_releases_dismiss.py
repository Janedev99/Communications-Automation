"""Tests for PUT /api/v1/releases/{release_id}/dismissal.

Auth pattern: same as test_releases_latest_unread.py — uses
_make_authenticated_client() with create_session() + generate_csrf_token().

DB is shared in-memory SQLite (StaticPool); data accumulates across tests.
Use distinct emails (dis*@dismiss-test.com) to avoid collisions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus, UserReleaseDismissal
from app.models.user import User, UserRole
from app.services.auth import create_user, create_session, generate_csrf_token


# =============================================================================
# Helpers (mirror the pattern from test_releases_latest_unread.py)
# =============================================================================

def _make_user(*, email: str, role: UserRole = UserRole.staff) -> User:
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="Dismiss Test User",
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


def _make_published_release(*, created_by: User, title: str = "Dismissal Test Release") -> Release:
    db = _db_mod.SessionLocal()
    try:
        # Use a fixed past date so these releases never appear as "latest"
        # for tests in other modules that check the latest-unread endpoint.
        # The shared in-memory DB accumulates data across tests, so we must
        # not pollute other tests' "newest release" logic.
        rel = Release(
            title=title,
            body="## body",
            status=ReleaseStatus.published,
            created_by_id=created_by.id,
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


def _make_draft_release(*, created_by: User, title: str = "Draft For Dismissal Test") -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body="## draft",
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


def _get_dismissal(*, user_id, release_id) -> UserReleaseDismissal | None:
    db = _db_mod.SessionLocal()
    try:
        return (
            db.query(UserReleaseDismissal)
            .filter_by(user_id=user_id, release_id=release_id)
            .one_or_none()
        )
    finally:
        db.close()


def _count_dismissals(*, user_id, release_id) -> int:
    db = _db_mod.SessionLocal()
    try:
        return (
            db.query(UserReleaseDismissal)
            .filter_by(user_id=user_id, release_id=release_id)
            .count()
        )
    finally:
        db.close()


# =============================================================================
# Tests
# =============================================================================

def test_dismiss_creates_row(app_instance):
    """Published release, user PUTs dont_show_again=True → 204; row persisted."""
    admin = _make_user(email="dis-admin1@dismiss-test.com", role=UserRole.admin)
    staff = _make_user(email="dis-staff1@dismiss-test.com")
    release = _make_published_release(created_by=admin, title="Dismiss Creates Row")

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.put(
        f"/api/v1/releases/{release.id}/dismissal",
        json={"dont_show_again": True},
    )

    assert res.status_code == 204
    row = _get_dismissal(user_id=staff.id, release_id=release.id)
    assert row is not None
    assert row.dont_show_again is True


def test_dismiss_is_idempotent(app_instance):
    """Calling PUT twice with different bodies: only ONE row; latest value wins."""
    admin = _make_user(email="dis-admin2@dismiss-test.com", role=UserRole.admin)
    staff = _make_user(email="dis-staff2@dismiss-test.com")
    release = _make_published_release(created_by=admin, title="Dismiss Idempotent")

    tc = _make_authenticated_client(app_instance, staff)

    # First call: dont_show_again=True
    res1 = tc.put(
        f"/api/v1/releases/{release.id}/dismissal",
        json={"dont_show_again": True},
    )
    assert res1.status_code == 204

    # Second call: dont_show_again=False (latest value should win)
    res2 = tc.put(
        f"/api/v1/releases/{release.id}/dismissal",
        json={"dont_show_again": False},
    )
    assert res2.status_code == 204

    # Must be exactly ONE row, not two
    count = _count_dismissals(user_id=staff.id, release_id=release.id)
    assert count == 1

    # Latest value (False) must win
    row = _get_dismissal(user_id=staff.id, release_id=release.id)
    assert row is not None
    assert row.dont_show_again is False


def test_dismiss_404_on_draft(app_instance):
    """Dismissing a draft release → 404; no dismissal row created."""
    admin = _make_user(email="dis-admin3@dismiss-test.com", role=UserRole.admin)
    staff = _make_user(email="dis-staff3@dismiss-test.com")
    draft = _make_draft_release(created_by=admin, title="Draft Not Dismissible")

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.put(
        f"/api/v1/releases/{draft.id}/dismissal",
        json={"dont_show_again": True},
    )

    assert res.status_code == 404
    count = _count_dismissals(user_id=staff.id, release_id=draft.id)
    assert count == 0


def test_dismiss_404_on_nonexistent(app_instance):
    """Random UUID that doesn't exist → 404."""
    staff = _make_user(email="dis-staff4@dismiss-test.com")

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.put(
        f"/api/v1/releases/{uuid.uuid4()}/dismissal",
        json={"dont_show_again": True},
    )

    assert res.status_code == 404


def test_dismiss_scoped_to_current_user(app_instance):
    """User A dismisses; user B has no row for that release."""
    admin = _make_user(email="dis-admin5@dismiss-test.com", role=UserRole.admin)
    user_a = _make_user(email="dis-usera@dismiss-test.com")
    user_b = _make_user(email="dis-userb@dismiss-test.com")
    release = _make_published_release(created_by=admin, title="Dismiss Scoped")

    tc_a = _make_authenticated_client(app_instance, user_a)
    res = tc_a.put(
        f"/api/v1/releases/{release.id}/dismissal",
        json={"dont_show_again": True},
    )
    assert res.status_code == 204

    # User A has a row
    row_a = _get_dismissal(user_id=user_a.id, release_id=release.id)
    assert row_a is not None

    # User B has no row
    row_b = _get_dismissal(user_id=user_b.id, release_id=release.id)
    assert row_b is None


def test_dismiss_requires_auth(client):
    """Unauthenticated request → 401 or 403.

    CSRF dependency fires before the session check, so an unauthenticated
    client (no cookies at all) receives 403 (missing CSRF cookie) rather
    than 401. Both statuses confirm the endpoint is protected.
    """
    res = client.put(
        f"/api/v1/releases/{uuid.uuid4()}/dismissal",
        json={"dont_show_again": True},
    )
    assert res.status_code in (401, 403)
