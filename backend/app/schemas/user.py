"""Pydantic schemas for User and Session."""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole


def _validate_password_complexity(v: str) -> str:
    """
    Enforce password policy: min 8 chars, at least 1 uppercase, 1 lowercase, 1 digit.
    Raises ValueError on any violation.
    """
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit.")
    return v


# ── Request schemas ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.staff

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def new_password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)


class UpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    role: UserRole | None = None


# ── Response schemas ───────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    user: UserResponse
    session_id: uuid.UUID
    expires_at: datetime


class MeResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    is_active: bool
