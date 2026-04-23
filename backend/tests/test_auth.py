"""
Tests for the authentication system.

Covers:
  - Rate limiting after 5 failed logins
  - Session cookie is opaque (not a DB PK); token_hash matches SHA-256
  - Expired session returns 401
  - New login invalidates prior sessions
  - CSRF header required on POST requests
  - Admin cannot deactivate their own account
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session


# ===========================================================================
# Helpers
# ===========================================================================

def _seed_user(*, email_suffix: str = "", role: str = "staff"):
    """Create a user via the auth service in a dedicated session. Returns (user_id, email, password)."""
    import app.database as _db_mod
    from app.services.auth import create_user
    from app.models.user import UserRole

    suffix = email_suffix or str(uuid.uuid4())[:8]
    email = f"user-{suffix}@authtest.com"
    password = "TestPass123!"

    db = _db_mod.SessionLocal()
    try:
        r = UserRole.admin if role == "admin" else UserRole.staff
        user = create_user(db, email=email, name="Test User", password=password, role=r)
        db.commit()
        return str(user.id), email, password
    finally:
        db.close()


# ===========================================================================
# 1. Rate limiting after 5 failed login attempts
# ===========================================================================

def test_rate_limit_after_5_failed_logins(client):
    """
    After 5 failed login attempts from the same IP, the 6th attempt must
    return HTTP 429 Too Many Requests.
    """
    payload = {"email": "nobody@example.com", "password": "WrongPass"}

    # Make 5 failing attempts
    for _ in range(5):
        resp = client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 401

    # 6th attempt must be rate-limited
    resp = client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 429, (
        "6th failed login from same IP must return 429"
    )
    assert "too many" in resp.json()["detail"].lower()


# ===========================================================================
# 2. Session cookie is opaque (not a DB primary key)
# ===========================================================================

def test_session_token_cookie_is_opaque(client):
    """
    The session_token cookie must be an opaque random value, NOT the session's
    DB primary key (UUID). The DB stores only the SHA-256 hash.
    """
    import app.database as _db_mod
    from app.models.user import Session as DbSession
    from sqlalchemy import select

    _, email, password = _seed_user(role="admin")

    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200

    raw_token = resp.cookies.get("session_token")
    assert raw_token is not None

    # Token must not be a valid UUID (DB PK)
    try:
        uuid.UUID(raw_token)
        is_uuid = True
    except ValueError:
        is_uuid = False
    assert not is_uuid, "session_token cookie must not be a bare UUID (DB primary key)"

    # The DB must store the SHA-256 hash of the raw token, not the raw token
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db = _db_mod.SessionLocal()
    try:
        session = db.execute(
            select(DbSession).where(DbSession.token_hash == expected_hash)
        ).scalar_one_or_none()
        assert session is not None, "DB must store token_hash = sha256(raw_token)"
    finally:
        db.close()


# ===========================================================================
# 3. Expired session returns 401
# ===========================================================================

def test_session_expiry_rejects_request(client):
    """
    A session whose expires_at is in the past must be rejected with HTTP 401.
    """
    import app.database as _db_mod
    from app.models.user import Session as DbSession
    from app.services.auth import _hash_token
    from sqlalchemy import select, update

    _, email, password = _seed_user(role="admin")

    # Login to get a session
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    raw_token = resp.cookies.get("session_token")
    assert raw_token is not None

    # Manually expire the session in the DB
    token_hash = _hash_token(raw_token)
    db = _db_mod.SessionLocal()
    try:
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        db.execute(
            update(DbSession)
            .where(DbSession.token_hash == token_hash)
            .values(expires_at=past)
        )
        db.commit()
    finally:
        db.close()

    # Authenticated request should now fail
    resp = client.get(
        "/api/v1/auth/me",
        cookies={"session_token": raw_token},
    )
    assert resp.status_code == 401, "Expired session must return 401"


# ===========================================================================
# 4. New login invalidates prior sessions
# ===========================================================================

def test_prior_sessions_invalidated_on_new_login(client):
    """
    Logging in twice as the same user must invalidate the first session.
    Using the first session token after a second login must return 401.
    """
    import app.database as _db_mod
    from app.models.user import Session as DbSession
    from app.services.auth import _hash_token
    from sqlalchemy import select

    _, email, password = _seed_user(role="admin")

    # First login
    resp1 = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp1.status_code == 200
    token1 = resp1.cookies["session_token"]

    # Second login (should rotate the session)
    resp2 = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp2.status_code == 200

    # First session must now be invalid
    me_resp = client.get(
        "/api/v1/auth/me",
        cookies={"session_token": token1},
    )
    assert me_resp.status_code == 401, (
        "First session must be invalidated after a second login"
    )

    # Verify in DB: first session's is_active should be False
    hash1 = _hash_token(token1)
    db = _db_mod.SessionLocal()
    try:
        old_session = db.execute(
            select(DbSession).where(DbSession.token_hash == hash1)
        ).scalar_one_or_none()
        if old_session:
            assert not old_session.is_active, "First session must have is_active=False"
    finally:
        db.close()


# ===========================================================================
# 5. CSRF required on POST requests
# ===========================================================================

def test_csrf_required_on_post(client):
    """
    POST requests to CSRF-protected routes must fail with 403 when
    X-CSRF-Token header is absent.

    We use /api/v1/auth/logout which requires an active session + CSRF.
    We send a valid session cookie but no CSRF header.
    """
    import app.database as _db_mod
    from app.services.auth import create_session
    from app.models.user import User
    from sqlalchemy import select

    _, email, password = _seed_user(role="staff")

    # Login to get a real session token
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    session_token = resp.cookies["session_token"]

    # Attempt logout with session cookie but WITHOUT X-CSRF-Token header
    resp_logout = client.post(
        "/api/v1/auth/logout",
        cookies={"session_token": session_token},
        # No X-CSRF-Token header
    )
    assert resp_logout.status_code == 403, (
        "POST without X-CSRF-Token must return 403"
    )


# ===========================================================================
# 6. Admin cannot deactivate own account
# ===========================================================================

def test_admin_cannot_delete_self(app_instance):
    """
    Attempting to set is_active=False on the currently logged-in admin account
    must return HTTP 409 Conflict.
    """
    import app.database as _db_mod
    from app.models.user import User, UserRole
    from app.services.auth import create_user, create_session, generate_csrf_token
    from sqlalchemy import select
    from fastapi.testclient import TestClient

    # Seed admin user
    db = _db_mod.SessionLocal()
    try:
        suffix = str(uuid.uuid4())[:8]
        email = f"admin-self-{suffix}@example.com"
        user = create_user(
            db,
            email=email,
            name="Admin Self",
            password="AdminSelf123!",
            role=UserRole.admin,
        )
        db.flush()
        _, raw_token = create_session(db, user)
        csrf = generate_csrf_token()
        user_id = str(user.id)
        db.commit()
    finally:
        db.close()

    tc = TestClient(app_instance, raise_server_exceptions=True)
    tc.cookies.set("session_token", raw_token)
    tc.cookies.set("csrf_token", csrf)
    tc.headers.update({"X-CSRF-Token": csrf})

    resp = tc.put(
        f"/api/v1/auth/users/{user_id}",
        json={"is_active": False},
    )
    assert resp.status_code == 409, (
        "Admin must not be able to deactivate their own account"
    )
    assert "deactivate" in resp.json()["detail"].lower()
