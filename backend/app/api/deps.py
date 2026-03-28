"""
FastAPI dependencies for authentication and authorization.

`get_current_user`  — requires a valid session cookie; raises 401 otherwise.
`require_admin`     — like get_current_user but also enforces admin role.
"""
from __future__ import annotations

import uuid

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth import validate_session


def get_current_user(
    request: Request,
    session_id: str | None = Cookie(default=None, alias="session_id"),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the session_id cookie and return the authenticated User.

    Raises HTTP 401 if the cookie is missing, invalid, or expired.
    """
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )

    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        )

    user = validate_session(db, sid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require the current user to have admin role."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return current_user


def get_client_ip(request: Request) -> str | None:
    """Extract the real client IP, respecting X-Forwarded-For if present."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
