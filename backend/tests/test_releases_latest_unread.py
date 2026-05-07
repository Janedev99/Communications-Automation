"""Tests for GET /api/v1/releases/latest-unread.

Auth pattern: this project uses pre-authenticated TestClient instances built
from create_session() + cookie injection. Tests that need a custom user
(e.g. hide_releases_forever=True) call the same helper pattern used in
test_auth.py::test_admin_cannot_delete_self.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus, UserReleaseDismissal
from app.models.user import User, UserRole
from app.services.auth import create_user, create_session, generate_csrf_token


# =============================================================================
# Helpers
# =============================================================================

def _make_user(
    *,
    email: str,
    hide_forever: bool = False,
    role: UserRole = UserRole.staff,
) -> User:
    """Create a user in a dedicated session; returns the committed User."""
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="Test User",
            password="TestPass123!",
            role=role,
        )
        db.flush()
        if hide_forever:
            user.hide_releases_forever = True
            db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _make_authenticated_client(app_instance, user: User) -> TestClient:
    """Build a TestClient with a real session cookie for *user*."""
    db = _db_mod.SessionLocal()
    try:
        # Re-attach user to this session
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


def _make_published_release(
    *,
    created_by: User,
    published_at: datetime,
    title: str = "Test Release",
) -> Release:
    """Create and persist a published release; returns the committed Release."""
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body="## body\nHello world.",
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


def _make_draft_release(*, created_by: User, title: str = "Draft Release") -> Release:
    """Create and persist a draft release; returns the committed Release."""
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


def _dismiss_release(*, user: User, release: Release, dont_show_again: bool) -> None:
    """Insert a UserReleaseDismissal row."""
    db = _db_mod.SessionLocal()
    try:
        dismissal = UserReleaseDismissal(
            user_id=user.id,
            release_id=release.id,
            dont_show_again=dont_show_again,
        )
        db.merge(dismissal)
        db.commit()
    finally:
        db.close()


def _permanently_dismiss_all_except(*, user: User, keep_release_id: object) -> None:
    """Permanently dismiss every existing published release except the given one.

    This prevents DB-accumulation cross-test pollution when the in-memory DB
    accumulates published releases from prior tests.
    """
    from sqlalchemy import select as _select

    db = _db_mod.SessionLocal()
    try:
        all_published = db.execute(
            _select(Release).where(
                Release.status == ReleaseStatus.published,
                Release.id != keep_release_id,
            )
        ).scalars().all()
        for rel in all_published:
            dismissal = UserReleaseDismissal(
                user_id=user.id,
                release_id=rel.id,
                dont_show_again=True,
            )
            db.merge(dismissal)
        db.commit()
    finally:
        db.close()


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@releases-test.com"


# =============================================================================
# Tests
# =============================================================================

def test_returns_null_when_no_releases(app_instance):
    """Fresh user, no releases anywhere → 200 with null body."""
    user = _make_user(email=_unique_email("norel"))
    # Dismiss any published releases accumulated from earlier tests so this
    # test is not sensitive to execution order.
    _permanently_dismiss_all_except(user=user, keep_release_id=None)

    tc = _make_authenticated_client(app_instance, user)

    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    assert res.json() is None


def test_returns_null_when_only_drafts_exist(app_instance):
    """Admin creates a draft release; staff user gets null (drafts are invisible)."""
    admin = _make_user(email=_unique_email("admin"), role=UserRole.admin)
    staff = _make_user(email=_unique_email("staff"))

    _make_draft_release(created_by=admin)

    # Dismiss any published releases accumulated from earlier tests so this
    # test is not sensitive to execution order.
    _permanently_dismiss_all_except(user=staff, keep_release_id=None)

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    assert res.json() is None


def test_returns_latest_published_for_new_user(app_instance):
    """Two published releases (older and newer); user gets the newer one."""
    admin = _make_user(email=_unique_email("admin2"), role=UserRole.admin)
    staff = _make_user(email=_unique_email("staff2"))

    now = datetime.now(timezone.utc)
    older = _make_published_release(
        created_by=admin,
        published_at=now - timedelta(days=7),
        title="Older Release",
    )
    newer = _make_published_release(
        created_by=admin,
        published_at=now - timedelta(days=1),
        title="Newer Release",
    )

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    data = res.json()
    assert data is not None
    assert data["title"] == "Newer Release"
    assert str(newer.id) == data["id"]


def test_returns_null_when_dont_show_again_set(app_instance):
    """Published release, user dismisses with dont_show_again=True → endpoint returns null."""
    admin = _make_user(email=_unique_email("admin3"), role=UserRole.admin)
    staff = _make_user(email=_unique_email("staff3"))

    release = _make_published_release(
        created_by=admin,
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
        title="Permanently Dismissed",
    )
    # Permanently dismiss every previously accumulated release AND the target
    # so that no published release is visible for this user.
    _permanently_dismiss_all_except(user=staff, keep_release_id=release.id)
    _dismiss_release(user=staff, release=release, dont_show_again=True)

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    assert res.json() is None


def test_returns_release_when_dismissal_is_session_only(app_instance):
    """Published release, user has dismissal row with dont_show_again=False.

    The server still returns the release — session-scoped dismissal is
    enforced client-side only. Server must NOT exclude these.
    """
    admin = _make_user(email=_unique_email("admin4"), role=UserRole.admin)
    staff = _make_user(email=_unique_email("staff4"))

    # Use a far-future published_at so this release is always the most recent.
    release = _make_published_release(
        created_by=admin,
        published_at=datetime.now(timezone.utc) + timedelta(days=3650),
        title="Session Dismissed Only",
    )
    # Permanently dismiss all previously accumulated releases for this user
    # so only our target release is visible (session-only dismissal doesn't hide it).
    _permanently_dismiss_all_except(user=staff, keep_release_id=release.id)
    _dismiss_release(user=staff, release=release, dont_show_again=False)

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    data = res.json()
    assert data is not None
    assert data["title"] == "Session Dismissed Only"


def test_returns_null_when_hide_forever_is_true(app_instance):
    """User with hide_releases_forever=True gets null even when published releases exist."""
    admin = _make_user(email=_unique_email("admin5"), role=UserRole.admin)
    hider = _make_user(email=_unique_email("hider"), hide_forever=True)

    _make_published_release(
        created_by=admin,
        published_at=datetime.now(timezone.utc) + timedelta(days=3651),
        title="Should Be Hidden Forever",
    )

    tc = _make_authenticated_client(app_instance, hider)
    res = tc.get("/api/v1/releases/latest-unread")

    assert res.status_code == 200
    assert res.json() is None


def test_requires_auth(client):
    """Unauthenticated request → 401."""
    res = client.get("/api/v1/releases/latest-unread")
    assert res.status_code == 401
