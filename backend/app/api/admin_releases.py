"""Admin-only release_notes routes (CRUD; publish is a separate task).

GET    /api/v1/admin/releases              — list all releases (drafts + published)
POST   /api/v1/admin/releases              — create a draft
PATCH  /api/v1/admin/releases/{release_id} — update a draft (published are immutable)
DELETE /api/v1/admin/releases/{release_id} — delete a draft (published are immutable)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_csrf
from app.models.release import Release, ReleaseStatus
from app.models.user import User
from app.schemas.release import (
    CreateReleaseRequest,
    CreatedByBrief,
    ReleaseAdminResponse,
    UpdateReleaseRequest,
)

router = APIRouter(prefix="/admin/releases", tags=["admin-releases"])


def _to_admin_response(rel: Release) -> ReleaseAdminResponse:
    return ReleaseAdminResponse(
        id=rel.id,
        title=rel.title,
        body=rel.body,
        status=rel.status,
        generated_from=rel.generated_from,
        commit_sha_at_release=rel.commit_sha_at_release,
        created_by=CreatedByBrief(
            id=rel.created_by.id,
            name=rel.created_by.name,
            email=rel.created_by.email,
        ),
        created_at=rel.created_at,
        updated_at=rel.updated_at,
        published_at=rel.published_at,
    )


@router.get("", response_model=list[ReleaseAdminResponse])
def list_releases(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[ReleaseAdminResponse]:
    """List all releases (drafts + published), ordered created_at DESC."""
    rows = db.query(Release).order_by(Release.created_at.desc()).all()
    return [_to_admin_response(r) for r in rows]


@router.post(
    "",
    response_model=ReleaseAdminResponse,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_release(
    payload: CreateReleaseRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ReleaseAdminResponse:
    """Create a new draft release."""
    rel = Release(
        title=payload.title,
        body=payload.body,
        status=ReleaseStatus.draft,
        generated_from=payload.generated_from,
        commit_sha_at_release=payload.commit_sha_at_release,
        created_by_id=admin.id,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return _to_admin_response(rel)


@router.patch(
    "/{release_id}",
    response_model=ReleaseAdminResponse,
    dependencies=[Depends(require_csrf)],
)
def update_release(
    release_id: uuid.UUID,
    payload: UpdateReleaseRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ReleaseAdminResponse:
    """Update a draft release. Published releases are immutable (409)."""
    rel = db.query(Release).filter_by(id=release_id).one_or_none()
    if rel is None:
        raise HTTPException(status_code=404, detail="release_not_found")
    if rel.status == ReleaseStatus.published:
        raise HTTPException(status_code=409, detail="release_is_published_immutable")
    if payload.title is not None:
        rel.title = payload.title
    if payload.body is not None:
        rel.body = payload.body
    db.commit()
    db.refresh(rel)
    return _to_admin_response(rel)


@router.delete(
    "/{release_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def delete_release(
    release_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """Delete a draft release. Published releases cannot be deleted (409)."""
    rel = db.query(Release).filter_by(id=release_id).one_or_none()
    if rel is None:
        raise HTTPException(status_code=404, detail="release_not_found")
    if rel.status == ReleaseStatus.published:
        raise HTTPException(status_code=409, detail="release_is_published_immutable")
    db.delete(rel)
    db.commit()
