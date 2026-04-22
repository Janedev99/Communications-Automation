"""
FastAPI dependencies for authentication, authorization, and CSRF.

`get_current_user`  — requires a valid session cookie; raises 401 otherwise.
`require_admin`     — like get_current_user but also enforces admin role.
`require_csrf`      — double-submit CSRF check for state-changing requests.
"""
from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth import validate_session


def get_current_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias="session_token"),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the session_token cookie and return the authenticated User.

    Raises HTTP 401 if the cookie is missing, invalid, or expired.
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )

    user = validate_session(db, session_token)
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


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    csrf_token_cookie: str | None = Cookie(default=None, alias="csrf_token"),
) -> None:
    """
    Double-submit CSRF defense.

    The client must:
      1. Read the `csrf_token` cookie (non-HttpOnly, set at login).
      2. Echo the same value in the `X-CSRF-Token` request header.

    A cross-origin attacker cannot read the cookie value, so they cannot
    construct the matching header — even with credentialed requests.

    This dependency should be applied to all POST/PUT/DELETE routes.
    Login itself is explicitly exempt (no session exists yet).
    """
    if not csrf_token_cookie:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token cookie missing. Please log in again.",
        )
    if not x_csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-CSRF-Token header missing.",
        )
    if csrf_token_cookie != x_csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch.",
        )


def get_client_ip(request: Request) -> str | None:
    """
    Extract the real client IP.

    X-Forwarded-For is only trusted when:
      - TRUSTED_PROXIES is configured (non-empty), AND
      - The direct connection IP (request.client.host) is in that set.

    Without trusted proxy configuration, the direct connection IP is returned
    unconditionally. This prevents rate-limit bucket spoofing via header injection
    when the backend is reachable directly (bypassing the reverse proxy).
    """
    from app.config import get_settings
    direct_ip = request.client.host if request.client else None

    settings = get_settings()
    trusted = settings.trusted_proxy_set
    if trusted and direct_ip in trusted:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return direct_ip
