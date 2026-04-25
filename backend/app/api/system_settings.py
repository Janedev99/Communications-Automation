"""
System settings — admin-only.

GET   /system-settings                — return all flags (key/value)
PATCH /system-settings/{key}          — set a single flag

V1 only exposes one flag: `auto_send_enabled` (string "true" / "false").
The endpoint is intentionally generic so future flags can plug in without
adding new routes.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, require_admin, require_csrf
from app.database import get_db
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services import system_settings as ss
from app.utils.audit import log_action

router = APIRouter(prefix="/system-settings", tags=["system-settings"])


class SystemSettingResponse(BaseModel):
    key: str
    value: str
    updated_at: str
    updated_by_id: str | None = None
    updated_by_name: str | None = None

    @classmethod
    def from_row(cls, row: SystemSetting, user: User | None) -> "SystemSettingResponse":
        return cls(
            key=row.key,
            value=row.value,
            updated_at=row.updated_at.isoformat(),
            updated_by_id=str(row.updated_by_id) if row.updated_by_id else None,
            updated_by_name=user.name if user else None,
        )


class SystemSettingUpdate(BaseModel):
    value: str = Field(..., max_length=2048)


@router.get("", response_model=list[SystemSettingResponse])
def list_settings(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[SystemSettingResponse]:
    rows = db.execute(
        select(SystemSetting).order_by(SystemSetting.key)
    ).scalars().all()

    user_ids = {r.updated_by_id for r in rows if r.updated_by_id}
    user_map: dict = {}
    if user_ids:
        users = db.execute(
            select(User).where(User.id.in_(user_ids))
        ).scalars().all()
        user_map = {u.id: u for u in users}

    return [SystemSettingResponse.from_row(r, user_map.get(r.updated_by_id)) for r in rows]


# Allowlist of settings that can be PATCH'd via the API. Anything outside
# this set gets a 404 — defense against typos elevating arbitrary keys.
_PATCHABLE_KEYS: set[str] = {ss.AUTO_SEND_ENABLED}


@router.patch("/{key}", response_model=SystemSettingResponse)
def update_setting(
    key: str,
    payload: SystemSettingUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    _: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> SystemSettingResponse:
    if key not in _PATCHABLE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No system setting '{key}'.",
        )

    # For boolean flags, normalize and reject malformed inputs.
    raw = payload.value.strip().lower()
    if key == ss.AUTO_SEND_ENABLED:
        if raw not in ("true", "false"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="auto_send_enabled must be 'true' or 'false'.",
            )

    before = ss.get_setting(db, key)
    row = ss.set_setting(db, key, raw, updated_by_id=current_user.id)

    log_action(
        db,
        action=f"system_settings.{key}.updated",
        entity_type="system_setting",
        entity_id=key,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"before": {"value": before}, "after": {"value": raw}},
    )

    db.commit()
    db.refresh(row)
    return SystemSettingResponse.from_row(row, current_user)
