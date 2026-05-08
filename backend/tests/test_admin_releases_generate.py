"""Tests for POST /api/v1/admin/releases/draft-from-commits — full degradation matrix.

Auth pattern: mirrors test_admin_releases_crud.py — uses _make_authenticated_client()
with create_session() + generate_csrf_token().

DB is shared in-memory SQLite (StaticPool); data accumulates across tests.
Use distinct emails (gen-*@gen-test.com) to avoid collisions.
Mocks are applied at the SUT's import path: app.api.admin_releases.*
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.database as _db_mod
from app.models.release import Release, ReleaseStatus
from app.models.user import User, UserRole
from app.services.auth import create_session, create_user, generate_csrf_token
from app.services.github_commits import Commit
from app.services.release_notes_ai import ReleaseNotesSuggestion


# =============================================================================
# Helpers — match the auth pattern from test_admin_releases_crud.py
# =============================================================================

def _make_user(*, email: str, role: UserRole = UserRole.staff) -> User:
    db = _db_mod.SessionLocal()
    try:
        user = create_user(
            db,
            email=email,
            name="Generate Test User",
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


def _make_published_release(
    *,
    created_by: User,
    title: str = "Gen Published Release",
    commit_sha: str | None = "zzz000",
) -> Release:
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title=title,
            body="## published body",
            status=ReleaseStatus.published,
            created_by_id=created_by.id,
            commit_sha_at_release=commit_sha,
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel
    finally:
        db.close()


# =============================================================================
# Convenience: build a Commit dataclass
# =============================================================================

def _commit(sha: str, subject: str) -> Commit:
    return Commit(sha=sha, subject=subject, author_name="Dev", committed_at=None)


_ENDPOINT = "/api/v1/admin/releases/draft-from-commits"

_MOCK_AI     = "app.api.admin_releases.is_release_notes_ai_available"
_MOCK_GH_CFG = "app.api.admin_releases.is_github_configured"
_MOCK_GH_SVC = "app.api.admin_releases.GitHubCommitsService"
_MOCK_GEN    = "app.api.admin_releases.generate_release_notes_suggestion"


# =============================================================================
# Tests
# =============================================================================

def test_github_path_happy(app_instance):
    """GitHub path: 3 commits, only feat: and fix: pass filter → 200 with commit_count=2."""
    admin = _make_user(email="gen-admin-happy@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    raw_commits = [
        _commit("aaa111", "feat: smarter drafts"),
        _commit("bbb222", "fix: broken pagination"),
        _commit("ccc333", "chore: update deps"),
    ]
    suggestion = ReleaseNotesSuggestion(
        title="Smarter Drafts and Fixes",
        body="## What's New\n- Smarter drafts\n- Fixed pagination",
        low_confidence=False,
    )

    mock_svc_instance = MagicMock()
    mock_svc_instance.commits_since.return_value = raw_commits

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=True),
        patch(_MOCK_GH_SVC, return_value=mock_svc_instance),
        patch(_MOCK_GEN, return_value=suggestion),
    ):
        res = tc.post(_ENDPOINT, json={"source": "github_api", "since_sha": "abc"})

    assert res.status_code == 200
    data = res.json()
    assert data["title_suggestion"] == "Smarter Drafts and Fixes"
    assert data["body_suggestion"] == "## What's New\n- Smarter drafts\n- Fixed pagination"
    assert data["commit_count"] == 2
    # SHA of the most-recent *included* commit (feat: smarter drafts = aaa111)
    assert data["commit_sha_at_release"] == "aaa111"
    assert data["generated_from"] == "github_api"
    assert data["low_confidence"] is False


def test_github_path_no_user_facing_commits_returns_zero_count(app_instance):
    """When all commits are chore/refactor, response is 200 with commit_count=0 and empty strings."""
    admin = _make_user(email="gen-admin-zero@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    raw_commits = [
        _commit("ddd444", "chore: update ci config"),
        _commit("eee555", "refactor: clean up utils"),
    ]

    mock_svc_instance = MagicMock()
    mock_svc_instance.commits_since.return_value = raw_commits

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=True),
        patch(_MOCK_GH_SVC, return_value=mock_svc_instance),
        patch(_MOCK_GEN) as mock_gen,
    ):
        res = tc.post(_ENDPOINT, json={"source": "github_api", "since_sha": "abc"})

    assert res.status_code == 200
    data = res.json()
    assert data["commit_count"] == 0
    assert data["title_suggestion"] == ""
    assert data["body_suggestion"] == ""
    assert data["low_confidence"] is False
    # AI should NOT have been called — nothing to summarize
    mock_gen.assert_not_called()


def test_github_path_default_since_sha_uses_last_published(app_instance):
    """When since_sha is omitted, endpoint uses the last published release's commit_sha.

    The shared DB accumulates data across tests, so we query the actual last-published
    SHA after inserting our release and assert against that value — making the test
    robust against ordering non-determinism from prior accumulated data.
    """
    admin = _make_user(email="gen-admin-sha@gen-test.com", role=UserRole.admin)

    # Use the same backdated published_at convention as other test helpers to
    # avoid polluting "latest unread" logic in other test files.
    expected_sha = "zzz999abc"  # distinctive enough not to collide
    db = _db_mod.SessionLocal()
    try:
        rel = Release(
            title="Gen SHA Boundary Release",
            body="## published body",
            status=ReleaseStatus.published,
            created_by_id=admin.id,
            commit_sha_at_release=expected_sha,
            published_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
        db.add(rel)
        db.commit()

        # Read back what the endpoint will actually pick: most-recent published_at.
        from app.models.release import Release as _Rel, ReleaseStatus as _RS
        last_pub = (
            db.query(_Rel)
            .filter(_Rel.status == _RS.published)
            .order_by(_Rel.published_at.desc())
            .first()
        )
        actual_expected_sha = last_pub.commit_sha_at_release if last_pub else None
    finally:
        db.close()

    tc = _make_authenticated_client(app_instance, admin)

    mock_svc_instance = MagicMock()
    mock_svc_instance.commits_since.return_value = [
        _commit("fff666", "feat: default sha test"),
    ]
    suggestion = ReleaseNotesSuggestion(
        title="Default SHA Test",
        body="- New feature",
        low_confidence=False,
    )

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=True),
        patch(_MOCK_GH_SVC, return_value=mock_svc_instance),
        patch(_MOCK_GEN, return_value=suggestion),
    ):
        res = tc.post(_ENDPOINT, json={"source": "github_api"})

    assert res.status_code == 200
    # The service must have been called with whatever the DB said was last-published
    mock_svc_instance.commits_since.assert_called_once()
    call_kwargs = mock_svc_instance.commits_since.call_args.kwargs
    assert call_kwargs["since_sha"] == actual_expected_sha


def test_github_unconfigured_returns_422(app_instance):
    """If GitHub is not configured and source=github_api, return 422 github_not_configured."""
    admin = _make_user(email="gen-admin-gh-cfg@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=False),
    ):
        res = tc.post(_ENDPOINT, json={"source": "github_api", "since_sha": "abc"})

    assert res.status_code == 422
    assert res.json()["detail"] == "github_not_configured"


def test_ai_unconfigured_returns_422(app_instance):
    """If LLM is not configured, both paths fail with 422 ai_unavailable (checked first)."""
    admin = _make_user(email="gen-admin-ai-cfg@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    with patch(_MOCK_AI, return_value=False):
        res = tc.post(
            _ENDPOINT,
            json={"source": "manual_paste", "commits": ["feat: x"]},
        )

    assert res.status_code == 422
    assert res.json()["detail"] == "ai_unavailable"


def test_manual_paste_path_works(app_instance):
    """Manual paste: chore filtered out → commit_count=2, commit_sha_at_release=None."""
    admin = _make_user(email="gen-admin-manual@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    suggestion = ReleaseNotesSuggestion(
        title="Manual Paste Release",
        body="- Feature A\n- Bug fix B",
        low_confidence=False,
    )

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GEN, return_value=suggestion),
    ):
        res = tc.post(
            _ENDPOINT,
            json={
                "source": "manual_paste",
                "commits": ["feat: a", "fix: b", "chore: c"],
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["commit_count"] == 2
    assert data["commit_sha_at_release"] is None
    assert data["generated_from"] == "manual_paste"
    assert data["title_suggestion"] == "Manual Paste Release"


def test_manual_paste_works_without_github_configured(app_instance):
    """Manual paste does not require GitHub — 200 even when is_github_configured=False."""
    admin = _make_user(email="gen-admin-ngh@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    suggestion = ReleaseNotesSuggestion(
        title="No GitHub Needed",
        body="- Feature X",
        low_confidence=False,
    )

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=False),
        patch(_MOCK_GEN, return_value=suggestion),
    ):
        res = tc.post(
            _ENDPOINT,
            json={"source": "manual_paste", "commits": ["feat: x"]},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["commit_count"] == 1


def test_github_request_failure_returns_502(app_instance):
    """GitHub upstream failure raises GitHubError → route returns 502 with github_error detail."""
    from app.services.github_commits import GitHubError

    admin = _make_user(email="gen-admin-502gh@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    mock_svc_instance = MagicMock()
    mock_svc_instance.commits_since.side_effect = GitHubError("connection timeout")

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=True),
        patch(_MOCK_GH_SVC, return_value=mock_svc_instance),
    ):
        res = tc.post(_ENDPOINT, json={"source": "github_api", "since_sha": "abc"})

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "github_error" in detail


def test_llm_failure_returns_502(app_instance):
    """LLM upstream failure raises LLMError → route returns 502 with llm_error detail."""
    from app.services.llm_client import LLMError

    admin = _make_user(email="gen-admin-502llm@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GEN, side_effect=LLMError("quota exceeded")),
    ):
        res = tc.post(
            _ENDPOINT,
            json={"source": "manual_paste", "commits": ["feat: x"]},
        )

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "llm_error" in detail


def test_staff_forbidden(app_instance):
    """Staff (non-admin) user gets 403."""
    staff = _make_user(email="gen-staff-403@gen-test.com", role=UserRole.staff)
    tc = _make_authenticated_client(app_instance, staff)

    res = tc.post(
        _ENDPOINT,
        json={"source": "manual_paste", "commits": ["feat: x"]},
    )

    assert res.status_code == 403


def test_low_confidence_passes_through(app_instance):
    """low_confidence=True from the AI suggestion is returned in the response."""
    admin = _make_user(email="gen-admin-lowconf@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    suggestion = ReleaseNotesSuggestion(
        title="Updates on today",
        body="Some raw output that couldn't be parsed.",
        low_confidence=True,
    )

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GEN, return_value=suggestion),
    ):
        res = tc.post(
            _ENDPOINT,
            json={"source": "manual_paste", "commits": ["feat: x"]},
        )

    assert res.status_code == 200
    assert res.json()["low_confidence"] is True


def test_unauthenticated_returns_401_or_403(client):
    """Unauthenticated POST returns 401 or 403 (CSRF fires first)."""
    res = client.post(
        _ENDPOINT,
        json={"source": "manual_paste", "commits": ["feat: x"]},
    )
    assert res.status_code in (401, 403)


def test_zero_commits_github_latest_sha_still_advances(app_instance):
    """Even when all commits are filtered, commit_sha_at_release = SHA of most-recent fetched."""
    admin = _make_user(email="gen-admin-sha-adv@gen-test.com", role=UserRole.admin)
    tc = _make_authenticated_client(app_instance, admin)

    # All non-user-facing
    raw_commits = [
        _commit("head111", "chore: ci"),
        _commit("head222", "refactor: cleanup"),
    ]

    mock_svc_instance = MagicMock()
    mock_svc_instance.commits_since.return_value = raw_commits

    with (
        patch(_MOCK_AI, return_value=True),
        patch(_MOCK_GH_CFG, return_value=True),
        patch(_MOCK_GH_SVC, return_value=mock_svc_instance),
        patch(_MOCK_GEN) as mock_gen,
    ):
        res = tc.post(_ENDPOINT, json={"source": "github_api", "since_sha": "abc"})

    assert res.status_code == 200
    data = res.json()
    assert data["commit_count"] == 0
    # SHA must still advance to the most-recent fetched commit
    assert data["commit_sha_at_release"] == "head111"
    mock_gen.assert_not_called()
