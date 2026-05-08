"""Tests for the publish endpoint: POST /api/v1/admin/releases/{release_id}/publish.

Auth pattern: mirrors test_admin_releases_crud.py — uses _make_authenticated_client()
with create_session() + generate_csrf_token().

DB is shared in-memory SQLite (StaticPool); data accumulates across tests.
Use distinct emails (pub-*@pub-test.com) to avoid collisions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus
from app.models.user import User, UserRole
from app.services.auth import create_session, create_user, generate_csrf_token


# =============================================================================
# Helpers
# =============================================================================

def _make_user(*, email: str, role: UserRole = UserRole.staff) -> User:
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="Publish Test User",
            password="TestPass123!",
            role=role,
        )
        db.flush()
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _make_authenticated_client(app_instance, user: User) -> TestClient:
    db = _db_mod.SessionLocal()
    try:
        u = db.merge(user)
        _, raw_token = create_session(db, u)
        csrf = generate_csrf_token()
        db.commit()
    finally:
        db.close()

    tc = TestClient(app_instance, raise_server_exceptions=True)
    tc.cookies.set("session_token", raw_token)
    tc.cookies.set("csrf_token", csrf)
    tc.headers.update({"X-CSRF-Token": csrf})
    return tc


def _make_draft_release(
    *,
    created_by: User,
    title: str = "Publish Test Draft",
    summary: str | None = "Some summary about staff-visible changes.",
    highlights: list[dict] | None = None,
) -> Release:
    """Make a draft release with VALID structured fields so publish succeeds.

    Tests that exercise the strict gate (missing summary / no highlights)
    pass overrides explicitly.
    """
    if highlights is None:
        highlights = [{"category": "new", "text": "Adds publish-flow test capability"}]
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body=None,
            summary=summary,
            highlights=highlights,
            status=ReleaseStatus.draft,
            created_by_id=created_by.id,
            published_at=None,
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


def _make_published_release(*, created_by: User, title: str = "Publish Test Published") -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body=None,
            summary="Already-published summary",
            highlights=[{"category": "fixed", "text": "Already published"}],
            status=ReleaseStatus.published,
            created_by_id=created_by.id,
            # Backdate so it never appears as "latest" for other test modules
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


def _get_release(release_id) -> Release | None:
    db = _db_mod.SessionLocal()
    try:
        return db.query(Release).filter_by(id=release_id).one_or_none()
    finally:
        db.close()


# =============================================================================
# Tests
# =============================================================================

def test_publish_flips_status_and_sets_published_at(app_instance):
    """POST publish on a draft: 200, status=published, published_at set and >= before timestamp.

    The before capture happens BEFORE the POST call. After the call we re-query
    the DB row (not just the response body) to prove the write actually landed.

    After assertions, the release is backdated so it doesn't pollute the
    "latest unread" logic in other test files (shared StaticPool SQLite DB).
    """
    admin = _make_user(email="pub-admin-1@example.com", role=UserRole.admin)
    draft = _make_draft_release(created_by=admin, title="Pub Flip Draft")

    assert draft.status == ReleaseStatus.draft
    assert draft.published_at is None

    tc = _make_authenticated_client(app_instance, admin)

    # Capture timestamp BEFORE the POST
    before = datetime.now(timezone.utc)

    res = tc.post(f"/api/v1/admin/releases/{draft.id}/publish")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "published"
    assert data["published_at"] is not None

    # Re-query the DB row to verify the write happened (not just response body)
    updated = _get_release(draft.id)
    assert updated is not None
    assert updated.status == ReleaseStatus.published
    assert updated.published_at is not None

    # Normalize to UTC for comparison (SQLite may return naive datetimes)
    pub_at = updated.published_at
    if pub_at.tzinfo is None:
        pub_at = pub_at.replace(tzinfo=timezone.utc)

    assert pub_at >= before

    # Backdate the release so it doesn't appear as "latest" in other test files
    # that share the same StaticPool SQLite DB (same convention as _make_published_release).
    db = _db_mod.SessionLocal()
    try:
        row = db.query(Release).filter_by(id=draft.id).one()
        row.published_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    finally:
        db.close()


def test_publish_409_if_already_published(app_instance):
    """POST publish on an already-published release returns 409."""
    admin = _make_user(email="pub-admin-2@example.com", role=UserRole.admin)
    published = _make_published_release(created_by=admin, title="Already Published Release")

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.post(f"/api/v1/admin/releases/{published.id}/publish")

    assert res.status_code == 409


def test_publish_404_if_not_found(app_instance):
    """POST publish with a random UUID that doesn't exist returns 404."""
    admin = _make_user(email="pub-admin-3@example.com", role=UserRole.admin)

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.post(f"/api/v1/admin/releases/{uuid.uuid4()}/publish")

    assert res.status_code == 404


def test_publish_forbidden_for_staff(app_instance):
    """Staff user (non-admin) gets 403 on POST publish."""
    admin = _make_user(email="pub-admin-4@example.com", role=UserRole.admin)
    staff = _make_user(email="pub-staff-4@example.com", role=UserRole.staff)
    draft = _make_draft_release(created_by=admin, title="Staff Cannot Publish")

    tc = _make_authenticated_client(app_instance, staff)
    res = tc.post(f"/api/v1/admin/releases/{draft.id}/publish")

    assert res.status_code == 403


def test_publish_requires_csrf(client):
    """Request without CSRF token returns 401 or 403."""
    res = client.post(f"/api/v1/admin/releases/{uuid.uuid4()}/publish")
    assert res.status_code in (401, 403)


# ─── Strict publish gate ────────────────────────────────────────────────────


def test_publish_422_when_summary_missing(app_instance):
    """A draft with no summary cannot be published — 422 release_summary_required."""
    admin = _make_user(email="pub-admin-no-summary@example.com", role=UserRole.admin)
    draft = _make_draft_release(
        created_by=admin,
        title="No Summary Draft",
        summary=None,
        highlights=[{"category": "new", "text": "Has highlight but no summary"}],
    )

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.post(f"/api/v1/admin/releases/{draft.id}/publish")

    assert res.status_code == 422
    assert res.json()["detail"] == "release_summary_required"

    # Status unchanged.
    after = _get_release(draft.id)
    assert after is not None and after.status == ReleaseStatus.draft


def test_publish_422_when_highlights_empty(app_instance):
    """A draft with empty highlights cannot be published — 422 release_highlights_required."""
    admin = _make_user(email="pub-admin-no-highlights@example.com", role=UserRole.admin)
    draft = _make_draft_release(
        created_by=admin,
        title="No Highlights Draft",
        summary="Has summary but no highlights",
        highlights=[],
    )

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.post(f"/api/v1/admin/releases/{draft.id}/publish")

    assert res.status_code == 422
    assert res.json()["detail"] == "release_highlights_required"

    after = _get_release(draft.id)
    assert after is not None and after.status == ReleaseStatus.draft


def test_publish_422_when_summary_only_whitespace(app_instance):
    """Whitespace-only summary fails the gate the same as None."""
    admin = _make_user(email="pub-admin-ws-summary@example.com", role=UserRole.admin)
    draft = _make_draft_release(
        created_by=admin,
        title="WS Summary Draft",
        summary="   \n  \t  ",
        highlights=[{"category": "fixed", "text": "Has a real highlight"}],
    )

    tc = _make_authenticated_client(app_instance, admin)
    res = tc.post(f"/api/v1/admin/releases/{draft.id}/publish")

    assert res.status_code == 422
    assert res.json()["detail"] == "release_summary_required"
