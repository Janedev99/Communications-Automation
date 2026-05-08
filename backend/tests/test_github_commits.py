"""Tests for GitHubCommitsService — mocks httpx at the client level."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.services.github_commits import (
    Commit,
    GitHubCommitsService,
    GitHubError,
    filter_user_facing,
    is_github_configured,
)


def _resp(json_body, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_body
    m.raise_for_status = MagicMock()
    return m


def _commit_payload(sha: str, subject: str) -> dict:
    """Mimic the GitHub /repos/{owner}/{repo}/commits response shape."""
    return {
        "sha": sha,
        "commit": {
            "message": subject,
            "author": {
                "name": "Tester",
                "date": "2026-05-07T12:00:00Z",
            },
        },
    }


def test_returns_commits_until_since_sha():
    svc = GitHubCommitsService(token="t", owner="o", repo="r")
    page1 = [
        _commit_payload("aaa", "feat: thing"),
        _commit_payload("bbb", "fix: bug"),
        _commit_payload("ccc", "chore: bump"),  # boundary
        _commit_payload("ddd", "feat: older"),
    ]
    with patch("app.services.github_commits.httpx.Client") as m_client_cls:
        m_client = m_client_cls.return_value.__enter__.return_value
        m_client.get.return_value = _resp(page1)
        out = svc.commits_since(since_sha="ccc", branch="master", limit=100)

    assert [c.sha for c in out] == ["aaa", "bbb"]
    assert all(isinstance(c, Commit) for c in out)


def test_returns_up_to_limit_when_no_since_sha():
    svc = GitHubCommitsService(token="t", owner="o", repo="r")
    page1 = [_commit_payload(f"{i:040x}", f"feat: x{i}") for i in range(100)]
    with patch("app.services.github_commits.httpx.Client") as m_client_cls:
        m_client = m_client_cls.return_value.__enter__.return_value
        m_client.get.return_value = _resp(page1)
        out = svc.commits_since(since_sha=None, branch="master", limit=50)
    assert len(out) == 50


def test_walks_pages_when_since_sha_not_in_first_page():
    svc = GitHubCommitsService(token="t", owner="o", repo="r")
    page1 = [_commit_payload(f"a{i:039d}", f"feat: p1-{i}") for i in range(100)]
    page2 = [
        _commit_payload("b" * 40, "feat: page2"),
        _commit_payload("BOUND", "chore: cut"),
    ]
    with patch("app.services.github_commits.httpx.Client") as m_client_cls:
        m_client = m_client_cls.return_value.__enter__.return_value
        m_client.get.side_effect = [_resp(page1), _resp(page2)]
        out = svc.commits_since(since_sha="BOUND", branch="master", limit=200)
    assert len(out) == 101  # 100 from page 1 + 1 from page 2 (excludes boundary)


def test_stops_when_payload_empty():
    """No infinite loop if GitHub returns []."""
    svc = GitHubCommitsService(token="t", owner="o", repo="r")
    with patch("app.services.github_commits.httpx.Client") as m_client_cls:
        m_client = m_client_cls.return_value.__enter__.return_value
        m_client.get.return_value = _resp([])
        out = svc.commits_since(since_sha=None, branch="master", limit=100)
    assert out == []


def test_http_error_wraps_in_github_error():
    """httpx errors are translated to GitHubError so the route layer can 502."""
    import httpx as _httpx
    svc = GitHubCommitsService(token="t", owner="o", repo="r")
    with patch("app.services.github_commits.httpx.Client") as m_client_cls:
        m_client = m_client_cls.return_value.__enter__.return_value
        m_client.get.side_effect = _httpx.RequestError("boom", request=None)
        with pytest.raises(GitHubError):
            svc.commits_since(since_sha=None, branch="master", limit=10)


def test_is_github_configured_reflects_settings():
    with patch("app.services.github_commits.get_settings") as m:
        m.return_value = MagicMock(github_token="abc")
        assert is_github_configured() is True
        m.return_value = MagicMock(github_token="")
        assert is_github_configured() is False


def test_filter_user_facing_keeps_feat_and_fix_only():
    commits = [
        Commit(sha="a", subject="feat: x", author_name="x", committed_at=None),
        Commit(sha="b", subject="fix: y", author_name="x", committed_at=None),
        Commit(sha="c", subject="chore: z", author_name="x", committed_at=None),
        Commit(sha="d", subject="refactor: q", author_name="x", committed_at=None),
        Commit(sha="e", subject="feat(scope): w", author_name="x", committed_at=None),
        Commit(sha="f", subject="fix(scope): v", author_name="x", committed_at=None),
    ]
    out = filter_user_facing(commits)
    # Note: the spec says "starts with feat: or fix:" — confirm whether
    # `feat(scope):` should also be kept. Per Conventional Commits convention,
    # both `feat:` and `feat(scope):` are user-facing. Implementer choice:
    # if you choose to support scoped prefixes, this assertion should be
    # `[c.sha for c in out] == ["a", "b", "e", "f"]`. If you want strict
    # "feat:"/"fix:" only, the assertion is `["a", "b"]`. Follow your
    # judgment — match what is actually idiomatic for the project's
    # commit style. The git log shows `fix(drafts):`, `feat(seed):`, etc.
    # so scoped prefixes ARE used in this repo. Recommend supporting both.
    assert "a" in [c.sha for c in out]
    assert "b" in [c.sha for c in out]
    assert "c" not in [c.sha for c in out]
    assert "d" not in [c.sha for c in out]
    # If scoped prefixes are kept (recommended):
    if {"e", "f"}.issubset({c.sha for c in out}):
        # scoped support — good
        assert True
    else:
        # strict — also acceptable; just document the choice
        pass
