"""
Tests for password-change session rotation (F4).

When a user changes their password:
  - All OTHER active sessions are invalidated.
  - The session used for the change request remains valid.
"""
from __future__ import annotations

import uuid
import pytest
from sqlalchemy.orm import Session


def _seed_user_with_two_sessions(db_session: Session):
    """
    Create a user and two active sessions. Returns (user, token_a, token_b).
    token_a is the "current" session; token_b is an "other" session.
    """
    from app.services.auth import create_user, create_session, generate_csrf_token
    from app.models.user import UserRole

    suffix = str(uuid.uuid4())[:8]
    user = create_user(
        db_session,
        email=f"rottest-{suffix}@example.com",
        name="Rotation Test User",
        password="OldPass123!",
        role=UserRole.staff,
    )
    db_session.flush()

    # Session A — will be used for the change request (should survive)
    _, token_a = create_session(db_session, user)
    csrf_a = generate_csrf_token()

    # Session B — a second active session (should be revoked after password change)
    # To get a second session, we need to work around the rotation-on-login logic.
    # We do this by directly inserting a second session record.
    from datetime import datetime, timedelta, timezone
    from app.models.user import Session as DbSession
    import hashlib, secrets

    raw_b = secrets.token_urlsafe(32)
    hash_b = hashlib.sha256(raw_b.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    session_b = DbSession(
        user_id=user.id,
        token_hash=hash_b,
        created_at=now,
        expires_at=now + timedelta(hours=8),
        is_active=True,
    )
    db_session.add(session_b)
    db_session.flush()

    db_session.commit()
    return user, token_a, csrf_a, raw_b


def test_password_change_invalidates_other_sessions(app_instance, db_session):
    """
    After a password change, the OTHER session token (token_b) must be
    rejected by the /auth/me endpoint (401 Unauthorized).
    """
    from fastapi.testclient import TestClient

    user, token_a, csrf_a, token_b = _seed_user_with_two_sessions(db_session)

    client_a = TestClient(app_instance, raise_server_exceptions=False)
    client_a.cookies.set("session_token", token_a)
    client_a.cookies.set("csrf_token", csrf_a)
    client_a.headers.update({"X-CSRF-Token": csrf_a})

    # Verify token_b is initially valid
    client_b = TestClient(app_instance, raise_server_exceptions=False)
    client_b.cookies.set("session_token", token_b)
    me_before = client_b.get("/api/v1/auth/me")
    assert me_before.status_code == 200, (
        f"token_b should be valid before password change, got {me_before.status_code}"
    )

    # Change password using session A
    resp = client_a.post(
        "/api/v1/auth/change-password",
        json={"current_password": "OldPass123!", "new_password": "NewPass456!"},
    )
    assert resp.status_code == 200, f"Password change failed: {resp.text}"

    # token_b must now be invalid
    me_after = client_b.get("/api/v1/auth/me")
    assert me_after.status_code == 401, (
        f"token_b should be invalidated after password change, got {me_after.status_code}"
    )


def test_password_change_preserves_current_session(app_instance, db_session):
    """
    The session used for the change request (token_a) must remain valid
    after the password change — the user should not be forcibly logged out.
    """
    from fastapi.testclient import TestClient

    user, token_a, csrf_a, token_b = _seed_user_with_two_sessions(db_session)

    client_a = TestClient(app_instance, raise_server_exceptions=False)
    client_a.cookies.set("session_token", token_a)
    client_a.cookies.set("csrf_token", csrf_a)
    client_a.headers.update({"X-CSRF-Token": csrf_a})

    # Change password
    resp = client_a.post(
        "/api/v1/auth/change-password",
        json={"current_password": "OldPass123!", "new_password": "NewPass456!"},
    )
    assert resp.status_code == 200

    # Current session (A) must still be valid
    me = client_a.get("/api/v1/auth/me")
    assert me.status_code == 200, (
        f"Current session should remain valid after password change, got {me.status_code}"
    )
