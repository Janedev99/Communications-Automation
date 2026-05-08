"""User-facing release notes routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.models.release import Release, ReleaseStatus, UserReleaseDismissal
from app.models.user import User
from app.schemas.release import DismissRequest, LatestUnreadResponse

router = APIRouter(prefix="/releases", tags=["releases"])


@router.get("/latest-unread", response_model=LatestUnreadResponse | None)
def get_latest_unread(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LatestUnreadResponse | None:
    """Return the most recent published release the user hasn't permanently dismissed.

    Returns null when:
    - The user has hide_releases_forever=True, OR
    - No published release exists that lacks a permanent (dont_show_again=True)
      dismissal for this user.

    Releases with a session-only dismissal (dont_show_again=False) are still
    returned — session-scoped exclusion is enforced client-side.
    """
    if current_user.hide_releases_forever:
        return None

    # Subquery: release_ids this user has permanently dismissed.
    permanently_dismissed = (
        select(UserReleaseDismissal.release_id)
        .where(
            and_(
                UserReleaseDismissal.user_id == current_user.id,
                UserReleaseDismissal.dont_show_again.is_(True),
            )
        )
    )

    stmt = (
        select(Release)
        .where(
            and_(
                Release.status == ReleaseStatus.published,
                Release.id.notin_(permanently_dismissed),
            )
        )
        .order_by(Release.published_at.desc())
        .limit(1)
    )
    release = db.execute(stmt).scalar_one_or_none()
    if release is None:
        return None
    return LatestUnreadResponse(
        id=release.id,
        title=release.title,
        body=release.body,
        summary=release.summary,
        highlights=release.highlights or [],
        published_at=release.published_at,
    )


# ---------------------------------------------------------------------------
# Dismissal upsert helper
# ---------------------------------------------------------------------------

def _upsert_dismissal(
    db: Session,
    *,
    user_id: uuid.UUID,
    release_id: uuid.UUID,
    dont_show_again: bool,
) -> None:
    """Insert or update a (user_id, release_id) dismissal row atomically.

    Uses dialect-specific ON CONFLICT DO UPDATE for SQLite and PostgreSQL.
    Falls back to a query-then-update for any other dialect (defensive path).
    """
    dialect = db.get_bind().dialect.name
    table = UserReleaseDismissal.__table__
    values = {
        "user_id": user_id,
        "release_id": release_id,
        "dont_show_again": dont_show_again,
    }
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(table).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "release_id"],
            set_={"dont_show_again": dont_show_again},
        )
        db.execute(stmt)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(table).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "release_id"],
            set_={"dont_show_again": dont_show_again},
        )
        db.execute(stmt)
    else:
        existing = (
            db.query(UserReleaseDismissal)
            .filter_by(user_id=user_id, release_id=release_id)
            .one_or_none()
        )
        if existing:
            existing.dont_show_again = dont_show_again
        else:
            db.add(UserReleaseDismissal(**values))
    db.commit()


# ---------------------------------------------------------------------------
# PUT /releases/{release_id}/dismissal
# Registered AFTER /latest-unread so path resolution is unambiguous.
# ---------------------------------------------------------------------------

@router.put(
    "/{release_id}/dismissal",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def dismiss_release(
    release_id: uuid.UUID,
    payload: DismissRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Mark a published release as dismissed for the current user.

    Idempotent — repeated calls update the existing row rather than
    inserting a duplicate. Returns 404 if the release does not exist
    or is not in published status (drafts are not dismissible).
    """
    rel = (
        db.query(Release)
        .filter_by(id=release_id, status=ReleaseStatus.published)
        .one_or_none()
    )
    if rel is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="release_not_found",
        )
    _upsert_dismissal(
        db,
        user_id=current_user.id,
        release_id=release_id,
        dont_show_again=payload.dont_show_again,
    )
