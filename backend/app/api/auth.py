"""
Auth routes.

POST /auth/login            — exchange credentials for a session cookie
POST /auth/logout           — revoke the current session
GET  /auth/me               — return the current user's profile
POST /auth/users            — create a new user (admin only)
GET  /auth/users            — list all users (admin only)
PUT  /auth/users/{user_id}  — update a user (admin only)

Security model:
  - Session cookie: HttpOnly, SameSite=None+Secure in production (cross-origin
    Railway deploys), SameSite=Lax locally.
  - CSRF defense: double-submit pattern. Login issues a non-HttpOnly `csrf_token`
    cookie. All state-changing requests (POST/PUT/DELETE) must echo the same
    value in X-CSRF-Token header. Validated by `require_csrf` dependency.
    Login itself is exempt (no session yet).
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import DefaultDict

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user, require_admin, require_csrf
from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import ChangePasswordRequest, CreateUserRequest, LoginRequest, LoginResponse, MeResponse, UpdateUserRequest, UserResponse
from app.services import auth as auth_service
from app.utils.audit import log_action

# ── In-memory rate limiting for login ─────────────────────────────────────────
# Tracks failed login timestamps per IP: {ip: [timestamp, ...]}
_failed_attempts: DefaultDict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_MAX_ATTEMPTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(ip: str) -> None:
    """Raise 429 if the IP has exceeded the failed-login threshold."""
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    # Drop timestamps outside the window; remove the key entirely when empty
    # to prevent unbounded dict growth from stale IP entries.
    recent = [t for t in _failed_attempts[ip] if t > window_start]
    if recent:
        _failed_attempts[ip] = recent
    else:
        _failed_attempts.pop(ip, None)

    if len(recent) >= _RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 5 minutes.",
        )


def _record_failed_attempt(ip: str) -> None:
    _failed_attempts[ip].append(time.monotonic())


def _clear_failed_attempts(ip: str) -> None:
    _failed_attempts.pop(ip, None)


# ── CSRF helper ───────────────────────────────────────────────────────────────

def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    """Set the HttpOnly session cookie with environment-appropriate SameSite."""
    settings = get_settings()
    if settings.is_production:
        # SameSite=None is required for cross-origin cookie sending (Railway deploys).
        # Secure=True is mandatory when SameSite=None per RFC 6265bis.
        samesite = "none"
        secure = True
    else:
        samesite = "lax"
        secure = False

    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path="/",
        max_age=max_age,
    )


def _set_csrf_cookie(response: Response, csrf_token: str, max_age: int) -> None:
    """
    Set the non-HttpOnly CSRF cookie so the browser JS can read and echo it.
    SameSite mirrors the session cookie strategy.
    """
    settings = get_settings()
    if settings.is_production:
        samesite = "none"
        secure = True
    else:
        samesite = "lax"
        secure = False

    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # Must be readable by JS for the double-submit pattern
        samesite=samesite,
        secure=secure,
        path="/",
        max_age=max_age,
    )


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate with email + password.

    On success:
      - Sets an HttpOnly `session_token` cookie (the auth material).
      - Sets a non-HttpOnly `csrf_token` cookie (for the double-submit CSRF pattern).
    """
    ip = get_client_ip(request)

    # Enforce rate limit before touching the database
    _check_rate_limit(ip)

    user = auth_service.authenticate(db, email=body.email, password=body.password)
    if user is None:
        _record_failed_attempt(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Clear failed attempts on successful login
    _clear_failed_attempts(ip)
    user_agent = request.headers.get("User-Agent")
    session, raw_token = auth_service.create_session(
        db, user, ip_address=ip, user_agent=user_agent
    )

    log_action(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
        user_id=user.id,
        ip_address=ip,
        details={"email": user.email},
    )

    max_age = int((session.expires_at - session.created_at).total_seconds())

    _set_session_cookie(response, raw_token, max_age)

    # Issue CSRF token for the double-submit pattern
    csrf_token = auth_service.generate_csrf_token()
    _set_csrf_cookie(response, csrf_token, max_age)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        session_id=session.id,
        expires_at=session.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_200_OK, dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Invalidate the current session and clear the cookies."""
    session_token = request.cookies.get("session_token")
    if session_token:
        auth_service.logout(db, session_token)

    log_action(
        db,
        action="auth.logout",
        entity_type="user",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
    )

    response.delete_cookie("session_token")
    response.delete_cookie("csrf_token")


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    """Return the currently authenticated user's profile."""
    return MeResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_200_OK, dependencies=[Depends(require_csrf)])
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Change the current user's password.

    Validates the current password before accepting the new one.
    Enforces complexity requirements on the new password.
    """
    if not auth_service.verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.hashed_password = auth_service.hash_password(body.new_password)
    db.flush()

    log_action(
        db,
        action="auth.password_changed",
        entity_type="user",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
    )

    return {"detail": "Password updated successfully."}


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin), Depends(require_csrf)],
)
def create_user(
    request: Request,
    body: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> UserResponse:
    """
    Create a new staff or admin user. Admin role required.
    """
    try:
        user = auth_service.create_user(
            db,
            email=body.email,
            name=body.name,
            password=body.password,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    log_action(
        db,
        action="user.created",
        entity_type="user",
        entity_id=str(user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"email": user.email, "role": user.role.value},
    )

    return UserResponse.model_validate(user)


@router.get(
    "/users",
    response_model=list[UserResponse],
    dependencies=[Depends(require_admin)],
)
def list_users(
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    """List all users. Admin role required."""
    offset = (page - 1) * page_size
    users = db.query(User).order_by(User.created_at.desc()).offset(offset).limit(page_size).all()
    return [UserResponse.model_validate(u) for u in users]


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_admin), Depends(require_csrf)],
)
def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> UserResponse:
    """Update a user's name, role, or active status. Admin role required."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Admin self-protection: prevent admins from breaking themselves or the last admin
    is_self = user_id == current_user.id
    if is_self:
        if body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot deactivate your own account.",
            )
        if body.role is not None and body.role != UserRole.admin:
            # Ensure at least one other active admin exists before downgrading
            active_admin_count = (
                db.query(User)
                .filter(User.role == UserRole.admin, User.is_active == True, User.id != current_user.id)  # noqa: E712
                .count()
            )
            if active_admin_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You are the last active admin. Assign another admin first.",
                )

    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active

    db.commit()
    db.refresh(user)

    log_action(
        db,
        action="user.updated",
        entity_type="user",
        entity_id=str(user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"changes": body.model_dump(exclude_none=True)},
    )

    return UserResponse.model_validate(user)
