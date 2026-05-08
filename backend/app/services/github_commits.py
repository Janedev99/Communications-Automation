"""GitHub Commits API wrapper for release-notes draft generation.

Walks paginated /repos/{owner}/{repo}/commits responses, returns Commit
dataclasses ordered most-recent-first, stopping at since_sha or limit
(whichever comes first).

Used by `app/api/admin_releases.py::draft_from_commits` (Task 4.3) to
gather commit subjects for the LLM to summarize.

Filtering note: `filter_user_facing` supports both plain (`feat:`, `fix:`)
and scoped (`feat(scope):`, `fix(scope):`) conventional-commit prefixes.
The repo uses scoped prefixes (e.g. `feat(seed):`, `fix(drafts):`) so both
forms are treated as user-facing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    author_name: str
    committed_at: datetime | None


class GitHubError(Exception):
    """Wraps any GitHub API failure for callers (route layer translates to 502)."""


class GitHubCommitsService:
    BASE_URL = "https://api.github.com"
    PER_PAGE = 100

    def __init__(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._owner = owner
        self._repo = repo
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def commits_since(
        self,
        *,
        since_sha: str | None,
        branch: str = "master",
        limit: int = 100,
    ) -> list[Commit]:
        """Walk pages until `since_sha` is hit or `limit` is reached.

        Returns most-recent-first. Excludes the boundary commit itself
        (commits AFTER since_sha, not including it).
        """
        out: list[Commit] = []
        page = 1
        url = f"{self.BASE_URL}/repos/{self._owner}/{self._repo}/commits"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                while len(out) < limit:
                    params = {
                        "sha": branch,
                        "per_page": self.PER_PAGE,
                        "page": page,
                    }
                    resp = client.get(url, headers=self._headers(), params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                    if not payload:
                        break  # ran out of commits

                    for item in payload:
                        sha = item["sha"]
                        if sha == since_sha:
                            return out
                        commit_obj = item.get("commit", {})
                        message = commit_obj.get("message") or ""
                        subject = message.splitlines()[0] if message else ""
                        author = commit_obj.get("author") or {}
                        committed_at = None
                        date_str = author.get("date")
                        if date_str:
                            try:
                                committed_at = datetime.fromisoformat(
                                    date_str.replace("Z", "+00:00")
                                )
                            except ValueError:
                                committed_at = None
                        out.append(Commit(
                            sha=sha,
                            subject=subject,
                            author_name=author.get("name", ""),
                            committed_at=committed_at,
                        ))
                        if len(out) >= limit:
                            return out

                    if len(payload) < self.PER_PAGE:
                        break  # last page reached
                    page += 1
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed: {exc}") from exc

        return out


def is_github_configured() -> bool:
    """Return True if a GitHub token has been configured in settings."""
    settings = get_settings()
    return bool(settings.github_token)


def filter_user_facing(commits: Iterable[Commit]) -> list[Commit]:
    """Keep only user-facing commits (feat: or fix: prefix, scoped or unscoped).

    Matches both `feat: x`, `feat(scope): x`, `fix: y`, and `fix(scope): y`.
    The repo's conventional-commits style uses scoped prefixes (e.g.
    `feat(seed):`, `fix(drafts):`), so both forms are kept.
    """
    out: list[Commit] = []
    for c in commits:
        s = c.subject
        if s.startswith(("feat:", "fix:")):
            out.append(c)
        elif s.startswith(("feat(", "fix(")):
            # Require closing paren immediately followed by colon: feat(scope):
            close_paren = s.find(")")
            if (
                close_paren != -1
                and close_paren + 1 < len(s)
                and s[close_paren + 1] == ":"
            ):
                out.append(c)
    return out
