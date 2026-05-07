"""User-facing release notes routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.release import Release, ReleaseStatus, UserReleaseDismissal
from app.models.user import User
from app.schemas.release import LatestUnreadResponse

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
        published_at=release.published_at,
    )
