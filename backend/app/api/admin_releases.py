"""Admin-only release_notes routes (CRUD; publish is a separate task).

GET    /api/v1/admin/releases                        — list all releases (drafts + published)
POST   /api/v1/admin/releases                        — create a draft
PATCH  /api/v1/admin/releases/{release_id}           — update a draft (published are immutable)
DELETE /api/v1/admin/releases/{release_id}           — delete a draft (published are immutable)
POST   /api/v1/admin/releases/draft-from-commits     — AI-generate a suggestion (no DB write)

The draft-from-commits endpoint reads commits from a build-time JSON
snapshot (backend/release-meta.json) instead of calling GitHub or
asking admins to paste. See app/services/release_meta_file.py and
scripts/generate_release_meta.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_csrf
from app.models.release import GeneratedFromSource, Release, ReleaseStatus
from app.models.user import User
from app.schemas.release import (
    CreateReleaseRequest,
    CreatedByBrief,
    DraftFromCommitsRequest,
    DraftSuggestionResponse,
    ReleaseAdminResponse,
    UpdateReleaseRequest,
)
from app.services.github_commits import filter_user_facing
from app.services.llm_client import LLMError
from app.services.release_meta_file import (
    ReleaseMetaUnavailable,
    commits_since,
    read_release_meta,
)
from app.services.release_notes_ai import (
    generate_release_notes_suggestion,
    is_release_notes_ai_available,
)

router = APIRouter(prefix="/admin/releases", tags=["admin-releases"])


def _to_admin_response(rel: Release) -> ReleaseAdminResponse:
    return ReleaseAdminResponse(
        id=rel.id,
        title=rel.title,
        body=rel.body,
        summary=rel.summary,
        highlights=rel.highlights or [],
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
    """Create a new draft release.

    Drafts may be created with any combination of body / summary / highlights —
    the publish endpoint enforces the gate (title + summary + ≥1 highlight).
    Drafts with neither body nor summary nor highlights are rejected here
    so the admin can't end up with a totally empty record.
    """
    has_legacy_body = bool(payload.body and payload.body.strip())
    has_structured = bool(
        (payload.summary and payload.summary.strip()) or payload.highlights
    )
    if not has_legacy_body and not has_structured:
        raise HTTPException(
            status_code=422,
            detail="release_must_have_body_or_summary_or_highlights",
        )

    rel = Release(
        title=payload.title,
        body=payload.body,
        summary=payload.summary,
        highlights=[h.model_dump() for h in payload.highlights],
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
    if payload.summary is not None:
        rel.summary = payload.summary
    if payload.highlights is not None:
        # Pass [] explicitly to clear; passing None means "leave alone".
        rel.highlights = [h.model_dump() for h in payload.highlights]
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


@router.post(
    "/{release_id}/publish",
    response_model=ReleaseAdminResponse,
    dependencies=[Depends(require_csrf)],
)
def publish_release(
    release_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ReleaseAdminResponse:
    """Publish a draft release. Sets status=published and published_at=now(UTC).

    Strict gate (per the structured-shape adoption): a release must have a
    non-empty title, a non-empty summary, and at least one highlight. Body
    is optional and exists only for backward compat with legacy releases.

    Returns 422 if the gate fails, 404 if not found, 409 if already published.
    """
    rel = db.query(Release).filter_by(id=release_id).one_or_none()
    if rel is None:
        raise HTTPException(status_code=404, detail="release_not_found")
    if rel.status == ReleaseStatus.published:
        raise HTTPException(status_code=409, detail="release_already_published")

    if not rel.title or not rel.title.strip():
        raise HTTPException(status_code=422, detail="release_title_required")
    if not rel.summary or not rel.summary.strip():
        raise HTTPException(status_code=422, detail="release_summary_required")
    if not rel.highlights or len(rel.highlights) < 1:
        raise HTTPException(status_code=422, detail="release_highlights_required")

    rel.status = ReleaseStatus.published
    rel.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rel)
    return _to_admin_response(rel)


@router.post(
    "/draft-from-commits",
    response_model=DraftSuggestionResponse,
    dependencies=[Depends(require_csrf)],
)
def draft_from_commits(
    payload: DraftFromCommitsRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> DraftSuggestionResponse:
    """Generate a release-notes suggestion from local commit metadata.

    Reads backend/release-meta.json (a build-time snapshot of `git log`),
    filters to user-facing commits (feat:/fix: prefixes or `[user-facing]`
    body opt-in token), and asks the configured LLM to produce a
    title + summary + highlights triple. No DB write — the admin reviews
    the suggestion and explicitly POSTs to /admin/releases to create.

    Error cases:
        422 ai_unavailable          — no LLM provider configured
        422 release_meta_unavailable — meta file missing or unreadable
        502 llm_error: <detail>      — LLM upstream failure
    """
    if not is_release_notes_ai_available():
        raise HTTPException(status_code=422, detail="ai_unavailable")

    try:
        meta = read_release_meta()
    except ReleaseMetaUnavailable as exc:
        raise HTTPException(
            status_code=422,
            detail="release_meta_unavailable",
            headers=None,
        ) from exc

    # Resolve since_sha: explicit → last published release → None (full snapshot).
    since_sha = payload.since_sha
    if since_sha is None:
        last_pub = (
            db.query(Release)
            .filter(Release.status == ReleaseStatus.published)
            .order_by(Release.published_at.desc())
            .first()
        )
        since_sha = last_pub.commit_sha_at_release if last_pub else None

    raw_commits = commits_since(meta, since_sha)

    # Track the most-recent fetched SHA BEFORE filtering — this is the
    # boundary for next time even if everything filters out.
    latest_sha: str | None = raw_commits[0].sha if raw_commits else None
    filtered = filter_user_facing(raw_commits)
    # If anything passed the filter, update latest_sha to the most-recent
    # included commit (so the next generation starts after what's about to
    # be published, not at a pre-filter boundary).
    if filtered:
        latest_sha = filtered[0].sha

    if not filtered:
        return DraftSuggestionResponse(
            title_suggestion="",
            summary_suggestion="",
            highlights_suggestion=[],
            commit_count=0,
            commit_sha_at_release=latest_sha,
            generated_from=GeneratedFromSource.local_meta,
            low_confidence=False,
        )

    try:
        suggestion = generate_release_notes_suggestion(
            commits=[c.subject for c in filtered],
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"llm_error: {exc}")

    return DraftSuggestionResponse(
        title_suggestion=suggestion.title,
        summary_suggestion=suggestion.summary,
        highlights_suggestion=suggestion.highlights,
        commit_count=len(filtered),
        commit_sha_at_release=latest_sha,
        generated_from=GeneratedFromSource.local_meta,
        low_confidence=suggestion.low_confidence,
    )
