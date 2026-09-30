"""
System settings — admin-only.

GET   /system-settings                — return all flags (key/value)
PATCH /system-settings/{key}          — set a single flag
GET    /system-settings/todo-reset    — "Start clean" state + live preview counts
POST   /system-settings/todo-reset    — set the to-do cutoff to server time
DELETE /system-settings/todo-reset    — undo the last reset (409 if none)

V1 only exposes one flag: `auto_send_enabled` (string "true" / "false").
The endpoint is intentionally generic so future flags can plug in without
adding new routes.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
from app.services import todo_queue
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
# Note: LEGACY_DRAFT_SIGNATURE is deliberately NOT patchable — it's the
# frozen pre-018 text used for send-time strip matching on old drafts.
_PATCHABLE_KEYS: set[str] = {ss.AUTO_SEND_ENABLED, ss.COMPANY_SIGNATURE}


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

    # Per-key normalization. Boolean flags are lowercased + validated; free-text
    # settings (the signature) must preserve case + internal formatting — only
    # outer whitespace is trimmed.
    if key == ss.AUTO_SEND_ENABLED:
        value_to_store = payload.value.strip().lower()
        if value_to_store not in ("true", "false"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="auto_send_enabled must be 'true' or 'false'.",
            )
    else:
        value_to_store = payload.value.strip()

    before = ss.get_setting(db, key)
    row = ss.set_setting(db, key, value_to_store, updated_by_id=current_user.id)

    log_action(
        db,
        action=f"system_settings.{key}.updated",
        entity_type="system_setting",
        entity_id=key,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"before": {"value": before}, "after": {"value": value_to_store}},
    )

    db.commit()
    db.refresh(row)
    return SystemSettingResponse.from_row(row, current_user)


# ── "Start clean" to-do reset (Feature B) ────────────────────────────────────
#
# The reset never mutates a thread/escalation/draft: it stores a cutoff
# timestamp in system_settings and the to-do surfaces hide anything with no
# activity since (services/todo_queue). The two keys live outside
# _PATCHABLE_KEYS on purpose — only these endpoints may write them, and the
# cutoff is always server time (R-B4), never a client-supplied value.


class TodoResetWouldHide(BaseModel):
    escalations: int
    reviews: int


class TodoResetState(BaseModel):
    cutoff_at: str | None
    set_by_name: str | None
    set_at: str | None
    can_undo: bool
    would_hide: TodoResetWouldHide


def _reset_state(db: Session) -> TodoResetState:
    cutoff = todo_queue.get_cutoff(db)
    row = db.get(SystemSetting, todo_queue.CUTOFF_KEY)
    setter = (
        db.get(User, row.updated_by_id)
        if cutoff is not None and row is not None and row.updated_by_id
        else None
    )
    # Anything currently visible would be hidden by a reset right now: it has
    # no activity at or after "now".
    counts = todo_queue.todo_counts(db, cutoff)
    return TodoResetState(
        cutoff_at=cutoff.isoformat() if cutoff else None,
        set_by_name=setter.name if setter else None,
        set_at=row.updated_at.isoformat() if cutoff is not None and row is not None else None,
        can_undo=ss.get_setting(db, todo_queue.CUTOFF_PREVIOUS_KEY) is not None,
        would_hide=TodoResetWouldHide(
            escalations=counts.active_escalations,
            reviews=counts.t2_review,
        ),
    )


@router.get("/todo-reset", response_model=TodoResetState)
def get_todo_reset(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TodoResetState:
    return _reset_state(db)


@router.post("/todo-reset", response_model=TodoResetState)
def apply_todo_reset(
    request: Request,
    current_user: User = Depends(require_admin),
    _: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TodoResetState:
    previous_raw = ss.get_setting(db, todo_queue.CUTOFF_KEY) or ""
    previous = todo_queue.parse_cutoff(previous_raw)
    hidden = todo_queue.todo_counts(db, previous)
    now = datetime.now(timezone.utc)
    current_row = db.get(SystemSetting, todo_queue.CUTOFF_KEY)

    # Save the previous value first so Undo can restore it (reset twice, then
    # undo, returns to the first cutoff — not to "no cutoff"). The saved row
    # keeps the ORIGINAL setter and time, so after Undo "set by" describes the
    # restored cutoff rather than whoever pressed Undo.
    saved = ss.set_setting(
        db,
        todo_queue.CUTOFF_PREVIOUS_KEY,
        previous.isoformat() if previous else "",
        updated_by_id=(
            current_row.updated_by_id if previous and current_row else current_user.id
        ),
    )
    if previous and current_row is not None:
        saved.updated_at = current_row.updated_at
    ss.set_setting(
        db, todo_queue.CUTOFF_KEY, now.isoformat(), updated_by_id=current_user.id
    )
    log_action(
        db,
        action="todo_reset.applied",
        entity_type="system_setting",
        entity_id=todo_queue.CUTOFF_KEY,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "cutoff_at": now.isoformat(),
            "previous_cutoff_at": previous.isoformat() if previous else None,
            "hidden_escalations": hidden.active_escalations,
            "hidden_reviews": hidden.t2_review,
            "hidden_escalated_threads": hidden.t3_escalate,
            "hidden_drafts_pending": hidden.drafts_pending_review,
        },
    )
    db.commit()
    return _reset_state(db)


@router.delete("/todo-reset", response_model=TodoResetState)
def undo_todo_reset(
    request: Request,
    current_user: User = Depends(require_admin),
    _: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TodoResetState:
    previous_row = db.get(SystemSetting, todo_queue.CUTOFF_PREVIOUS_KEY)
    if previous_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nothing to undo.",
        )
    current = todo_queue.get_cutoff(db)
    restored = todo_queue.parse_cutoff(previous_row.value)
    restored_row = ss.set_setting(
        db,
        todo_queue.CUTOFF_KEY,
        restored.isoformat() if restored else "",
        # The restored cutoff keeps its original setter/time (saved on reset);
        # the undo itself is attributed to current_user in the audit log below.
        updated_by_id=previous_row.updated_by_id if restored else current_user.id,
    )
    if restored:
        restored_row.updated_at = previous_row.updated_at
    # One level of undo: consume the saved value so a second Undo is a 409.
    db.delete(previous_row)
    db.flush()
    # Counts of what comes back into view.
    before = todo_queue.todo_counts(db, current)
    after = todo_queue.todo_counts(db, restored)
    log_action(
        db,
        action="todo_reset.undone",
        entity_type="system_setting",
        entity_id=todo_queue.CUTOFF_KEY,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "undone_cutoff_at": current.isoformat() if current else None,
            "restored_cutoff_at": restored.isoformat() if restored else None,
            "restored_escalations": max(after.active_escalations - before.active_escalations, 0),
            "restored_reviews": max(after.t2_review - before.t2_review, 0),
        },
    )
    db.commit()
    return _reset_state(db)


@router.post("/todo-reset/clear", response_model=TodoResetState)
def clear_todo_reset(
    request: Request,
    current_user: User = Depends(require_admin),
    _: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TodoResetState:
    """Turn the reset off (QA P3-2): the to-do lanes show everything again.

    Undo is one level deep, so after two resets it can never get back to "no
    cutoff" — this is that way back. The active cutoff (with its original
    setter and time) is saved as the Undo target, so clearing is reversible.
    """
    current = todo_queue.get_cutoff(db)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No reset is active.",
        )
    current_row = db.get(SystemSetting, todo_queue.CUTOFF_KEY)
    before = todo_queue.todo_counts(db, current)

    saved = ss.set_setting(
        db,
        todo_queue.CUTOFF_PREVIOUS_KEY,
        current.isoformat(),
        updated_by_id=current_row.updated_by_id if current_row else current_user.id,
    )
    if current_row is not None:
        saved.updated_at = current_row.updated_at
    ss.set_setting(db, todo_queue.CUTOFF_KEY, "", updated_by_id=current_user.id)
    db.flush()

    after = todo_queue.todo_counts(db, None)
    log_action(
        db,
        action="todo_reset.cleared",
        entity_type="system_setting",
        entity_id=todo_queue.CUTOFF_KEY,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "cleared_cutoff_at": current.isoformat(),
            "restored_escalations": max(after.active_escalations - before.active_escalations, 0),
            "restored_reviews": max(after.t2_review - before.t2_review, 0),
        },
    )
    db.commit()
    return _reset_state(db)
