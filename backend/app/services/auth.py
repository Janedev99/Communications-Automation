"""
Authentication service.

Handles:
  - Password hashing / verification (bcrypt)
  - User creation
  - Session creation (with hashed opaque token), validation, and revocation
  - Session rotation (invalidate all prior sessions on new login)
  - Role-based access checks
  - CSRF token generation for the double-submit pattern
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import Session as DbSession, User, UserRole
from app.utils.audit import log_action


settings = get_settings()

# Length of the opaque token issued to the browser cookie.
_TOKEN_BYTES = 32


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a session token."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token for the double-submit pattern."""
    return secrets.token_urlsafe(32)


# ── User management ────────────────────────────────────────────────────────────

def create_user(
    db: Session,
    *,
    email: str,
    name: str,
    password: str,
    role: UserRole = UserRole.staff,
) -> User:
    """
    Create a new user.  Raises ValueError if the email is already in use.
    """
    existing = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"A user with email '{email}' already exists.")

    user = User(
        email=email.lower(),
        name=name,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()  # Get the generated ID without committing
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        select(User).where(User.email == email.lower(), User.is_active == True)  # noqa: E712
    ).scalar_one_or_none()


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    ).scalar_one_or_none()


# ── Session management ─────────────────────────────────────────────────────────

def create_session(
    db: Session,
    user: User,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[DbSession, str]:
    """
    Create and persist a new server-side session.

    Invalidates all prior active sessions for the user (session rotation) to
    prevent session fixation and limit the blast radius of a leaked cookie.

    Returns (session_db_record, raw_token).
    The raw_token MUST be set as the cookie value — it is never stored in DB.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.session_ttl_hours)

    # ── Rotate: expire all active sessions for this user ──────────────────────
    # This forces re-authentication if the user is already logged in elsewhere.
    # We log it so admins can see concurrent-session activity in the audit log.
    revoked = db.execute(
        update(DbSession)
        .where(
            DbSession.user_id == user.id,
            DbSession.is_active == True,  # noqa: E712
            DbSession.expires_at > now,
        )
        .values(is_active=False, expires_at=now)
        .returning(DbSession.id)
    ).fetchall()

    if revoked:
        log_action(
            db,
            action="session_rotated",
            entity_type="user",
            entity_id=str(user.id),
            user_id=user.id,
            ip_address=ip_address,
            details={"revoked_session_count": len(revoked)},
        )

    # ── Create new session ────────────────────────────────────────────────────
    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    token_hash = _hash_token(raw_token)

    session = DbSession(
        user_id=user.id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
        is_active=True,
    )
    db.add(session)
    db.flush()
    return session, raw_token


def validate_session(db: Session, raw_token: str) -> User | None:
    """
    Validate a session cookie value (raw opaque token).

    Hashes the token and looks up the session record.
    Returns the associated User if valid and not expired, otherwise None.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    session = db.execute(
        select(DbSession).where(
            DbSession.token_hash == token_hash,
            DbSession.is_active == True,  # noqa: E712
            DbSession.expires_at > now,
        )
    ).scalar_one_or_none()

    if session is None:
        return None

    user = db.execute(
        select(User).where(User.id == session.user_id, User.is_active == True)  # noqa: E712
    ).scalar_one_or_none()

    return user


def logout(db: Session, raw_token: str) -> None:
    """Deactivate a session identified by its raw token (soft-delete)."""
    token_hash = _hash_token(raw_token)
    session = db.execute(
        select(DbSession).where(DbSession.token_hash == token_hash)
    ).scalar_one_or_none()
    if session:
        session.is_active = False
        db.flush()


def invalidate_other_sessions(
    db: Session,
    user_id: uuid.UUID,
    except_raw_token: str | None,
) -> int:
    """
    Deactivate all active sessions for the given user EXCEPT the one matching
    except_raw_token (the caller's current session).

    Returns the count of sessions revoked.
    Used after a password change to prevent stale sessions from remaining valid.
    """
    now = datetime.now(timezone.utc)
    current_hash = _hash_token(except_raw_token) if except_raw_token else None

    sessions = db.execute(
        select(DbSession).where(
            DbSession.user_id == user_id,
            DbSession.is_active == True,  # noqa: E712
            DbSession.expires_at > now,
        )
    ).scalars().all()

    revoked = 0
    for session in sessions:
        if current_hash and session.token_hash == current_hash:
            continue  # Keep the caller's current session active
        session.is_active = False
        session.expires_at = now
        revoked += 1

    if revoked:
        db.flush()

    return revoked


def authenticate(db: Session, email: str, password: str) -> User | None:
    """
    Verify credentials and return the User, or None if invalid.
    Deliberately does not distinguish between 'wrong email' and 'wrong password'
    to avoid user enumeration.
    """
    user = get_user_by_email(db, email)
    if user is None:
        # Run bcrypt anyway to prevent timing-based user enumeration
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user
