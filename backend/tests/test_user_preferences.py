"""Tests for PATCH /api/v1/auth/me/preferences and the hide_releases_forever
field on GET /api/v1/auth/me.

Auth pattern: same as test_releases_dismiss.py — uses _make_authenticated_client()
with create_session() + generate_csrf_token().

DB is shared in-memory SQLite (StaticPool); data accumulates across tests.
Use distinct emails (pref*@example.com) to avoid collisions.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.database as _db_mod
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
            name="Prefs Test User",
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


def _get_user_hide_forever(user_id) -> bool:
    """Read hide_releases_forever directly from the DB."""
    db = _db_mod.SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        return user.hide_releases_forever
    finally:
        db.close()


# =============================================================================
# Tests
# =============================================================================

def test_patch_sets_hide_forever_true(app_instance):
    """User starts with hide_releases_forever=False; PATCH true → 200, DB updated."""
    user = _make_user(email="pref1@example.com", hide_forever=False)
    assert _get_user_hide_forever(user.id) is False

    tc = _make_authenticated_client(app_instance, user)
    res = tc.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": True},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["hide_releases_forever"] is True
    # Confirm persisted in DB
    assert _get_user_hide_forever(user.id) is True


def test_patch_sets_hide_forever_false(app_instance):
    """User starts with hide_releases_forever=True; PATCH false → 200, DB updated."""
    user = _make_user(email="pref2@example.com", hide_forever=True)
    assert _get_user_hide_forever(user.id) is True

    tc = _make_authenticated_client(app_instance, user)
    res = tc.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": False},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["hide_releases_forever"] is False
    # Confirm persisted in DB
    assert _get_user_hide_forever(user.id) is False


def test_partial_update_does_not_clobber(app_instance):
    """User has hide_releases_forever=True; PATCH {} (empty body) → 200, field unchanged."""
    user = _make_user(email="pref3@example.com", hide_forever=True)
    assert _get_user_hide_forever(user.id) is True

    tc = _make_authenticated_client(app_instance, user)
    res = tc.patch(
        "/api/v1/auth/me/preferences",
        json={},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["hide_releases_forever"] is True
    # Confirm DB not clobbered
    assert _get_user_hide_forever(user.id) is True


def test_requires_auth(client):
    """Unauthenticated request → 401 or 403.

    CSRF dependency fires before the session check, so an unauthenticated
    client (no cookies at all) may receive 403 (missing CSRF cookie) rather
    than 401. Both statuses confirm the endpoint is protected.
    """
    res = client.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": True},
    )
    assert res.status_code in (401, 403)


def test_me_response_includes_hide_releases_forever(app_instance):
    """GET /auth/me returns hide_releases_forever in the response body."""
    user = _make_user(email="pref4@example.com", hide_forever=False)

    tc = _make_authenticated_client(app_instance, user)
    res = tc.get("/api/v1/auth/me")

    assert res.status_code == 200
    data = res.json()
    assert "hide_releases_forever" in data
    assert data["hide_releases_forever"] is False
