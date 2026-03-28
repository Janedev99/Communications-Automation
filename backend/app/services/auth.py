"""
Authentication service.

Handles:
  - Password hashing / verification (bcrypt)
  - User creation
  - Session creation, validation, and revocation
  - Role-based access checks
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import Session as DbSession, User, UserRole


settings = get_settings()


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
) -> DbSession:
    """Create and persist a new server-side session. Returns the session object."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.session_ttl_hours)

    session = DbSession(
        user_id=user.id,
        created_at=now,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
        is_active=True,
    )
    db.add(session)
    db.flush()
    return session


def validate_session(db: Session, session_id: uuid.UUID) -> User | None:
    """
    Validate a session cookie value.

    Returns the associated User if the session is valid and not expired,
    otherwise returns None.
    """
    now = datetime.now(timezone.utc)
    session = db.execute(
        select(DbSession).where(
            DbSession.id == session_id,
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


def logout(db: Session, session_id: uuid.UUID) -> None:
    """Deactivate a session (soft-delete)."""
    session = db.execute(
        select(DbSession).where(DbSession.id == session_id)
    ).scalar_one_or_none()
    if session:
        session.is_active = False
        db.flush()


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
