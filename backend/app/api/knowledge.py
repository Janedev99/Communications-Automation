"""
Knowledge base routes.

GET    /knowledge                — list entries (filter by category, entry_type, is_active)
GET    /knowledge/{id}           — get a single entry
POST   /knowledge                — create an entry (auth required)
PUT    /knowledge/{id}           — update an entry (auth required)
DELETE /knowledge/{id}           — soft-delete (set is_active=False; auth required)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user, require_csrf
from app.database import get_db
from app.models.email import KnowledgeEntry
from app.models.user import User
from app.schemas.knowledge import (
    CreateKnowledgeEntryRequest,
    KnowledgeEntryListResponse,
    KnowledgeEntryResponse,
    UpdateKnowledgeEntryRequest,
)
from app.utils.audit import log_action

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=KnowledgeEntryListResponse)
def list_knowledge_entries(
    category: str | None = Query(default=None, description="Filter by category value"),
    entry_type: str | None = Query(default=None, description="Filter by entry_type"),
    is_active: bool | None = Query(default=True, description="Filter by active status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeEntryListResponse:
    """
    List knowledge base entries with optional filters.

    By default returns only active entries (is_active=true).
    Pass is_active=false to see soft-deleted entries, or omit the filter
    to see all entries.
    """
    query = select(KnowledgeEntry)

    if category is not None:
        query = query.where(KnowledgeEntry.category == category)
    if entry_type is not None:
        query = query.where(KnowledgeEntry.entry_type == entry_type)
    if is_active is not None:
        query = query.where(KnowledgeEntry.is_active == is_active)

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar_one()

    # Paginate — newest first
    offset = (page - 1) * page_size
    rows = db.execute(
        query.order_by(KnowledgeEntry.created_at.desc()).offset(offset).limit(page_size)
    ).scalars().all()

    return KnowledgeEntryListResponse(
        items=[KnowledgeEntryResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{entry_id}", response_model=KnowledgeEntryResponse)
def get_knowledge_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeEntryResponse:
    """Retrieve a single knowledge base entry by ID."""
    entry = db.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
    ).scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found.",
        )

    return KnowledgeEntryResponse.model_validate(entry)


@router.post("", response_model=KnowledgeEntryResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_knowledge_entry(
    request: Request,
    body: CreateKnowledgeEntryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeEntryResponse:
    """
    Create a new knowledge base entry.

    All authenticated staff members can create entries.
    """
    entry = KnowledgeEntry(
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags or None,
        entry_type=body.entry_type,
        is_active=True,
        created_by_id=current_user.id,
    )
    db.add(entry)
    db.flush()

    log_action(
        db,
        action="knowledge.created",
        entity_type="knowledge_entry",
        entity_id=str(entry.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={
            "title": entry.title,
            "category": entry.category,
            "entry_type": entry.entry_type,
            "tags": entry.tags,
        },
    )

    return KnowledgeEntryResponse.model_validate(entry)


@router.put("/{entry_id}", response_model=KnowledgeEntryResponse, dependencies=[Depends(require_csrf)])
def update_knowledge_entry(
    request: Request,
    entry_id: uuid.UUID,
    body: UpdateKnowledgeEntryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeEntryResponse:
    """
    Update a knowledge base entry.

    Only fields provided in the request body are modified.
    Send is_active=false to soft-delete via this endpoint (or use DELETE).
    """
    entry = db.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
    ).scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found.",
        )

    # Use model_fields_set to distinguish "field not provided" from "field set to null"
    provided = body.model_fields_set
    changed_fields: dict = {}
    if "title" in provided:
        changed_fields["title"] = body.title
        entry.title = body.title
    if "content" in provided:
        changed_fields["content"] = "<updated>"  # Don't log full content — may be large
        entry.content = body.content
    if "category" in provided:
        changed_fields["category"] = body.category
        entry.category = body.category  # Can be set to None to clear
    if "tags" in provided:
        changed_fields["tags"] = body.tags
        entry.tags = body.tags or None
    if "entry_type" in provided:
        changed_fields["entry_type"] = body.entry_type
        entry.entry_type = body.entry_type
    if "is_active" in provided:
        changed_fields["is_active"] = body.is_active
        entry.is_active = body.is_active

    entry.updated_at = datetime.now(timezone.utc)
    db.flush()

    log_action(
        db,
        action="knowledge.updated",
        entity_type="knowledge_entry",
        entity_id=str(entry.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"changed_fields": changed_fields},
    )

    return KnowledgeEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(require_csrf)])
def delete_knowledge_entry(
    request: Request,
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Soft-delete a knowledge entry by setting is_active=False.

    The record is preserved for audit purposes. To fully restore it,
    use PUT /{id} with is_active=true.
    """
    entry = db.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
    ).scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found.",
        )

    if not entry.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge entry is already inactive.",
        )

    entry.is_active = False
    entry.updated_at = datetime.now(timezone.utc)
    db.flush()

    log_action(
        db,
        action="knowledge.deleted",
        entity_type="knowledge_entry",
        entity_id=str(entry.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"title": entry.title, "category": entry.category},
    )

    return {"ok": True}
