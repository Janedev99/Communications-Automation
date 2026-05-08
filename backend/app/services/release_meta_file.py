"""Read backend/release-meta.json (the build-time commit snapshot).

Companion to scripts/generate_release_meta.py. The script writes the file;
this module reads it and shapes the data for the existing release-notes
pipeline (Commit dataclass + filter_user_facing).

Adopting cappj's pattern means there's no GitHub API call, no token, and
no admin paste. The file is generated at build time (Docker build stage)
or auto-regenerated on backend startup in dev. If the file is missing,
the endpoint surfaces a clear 422 to the admin so they can fix the build.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.github_commits import Commit

logger = logging.getLogger(__name__)


# Same path the generator script uses by default.
DEFAULT_META_PATH = Path(__file__).resolve().parent.parent.parent / "release-meta.json"


class ReleaseMetaUnavailable(Exception):
    """Raised when the meta file is missing or unreadable.

    Caller (the API endpoint) should translate to HTTP 422 with a clear
    error code so the admin sees that the build artifact is missing.
    """


@dataclass(frozen=True)
class ReleaseMeta:
    """Decoded release-meta.json — the snapshot the build script wrote."""
    generated_at: datetime
    head_sha: str
    branch: str
    commits: list[Commit]


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read_release_meta(path: Path = DEFAULT_META_PATH) -> ReleaseMeta:
    """Read and parse the meta file. Returns a ReleaseMeta on success.

    Raises:
        ReleaseMetaUnavailable: if the file is missing, unreadable, or
            the JSON shape is wrong. The error is intentionally coarse
            because the admin only needs one clear signal: the build
            artifact isn't there, ask CI/devops to regenerate it.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ReleaseMetaUnavailable(
            f"release-meta.json not found at {path}. "
            "Run scripts/generate_release_meta.py to generate it."
        ) from exc
    except OSError as exc:
        raise ReleaseMetaUnavailable(
            f"Failed to read release-meta.json: {exc}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseMetaUnavailable(
            f"release-meta.json is malformed: {exc}"
        ) from exc

    if not isinstance(data, dict) or "commits" not in data:
        raise ReleaseMetaUnavailable(
            "release-meta.json is missing the 'commits' key — regenerate it."
        )

    raw_commits = data.get("commits", [])
    if not isinstance(raw_commits, list):
        raise ReleaseMetaUnavailable(
            "release-meta.json 'commits' key is not a list — regenerate it."
        )

    commits: list[Commit] = []
    for entry in raw_commits:
        if not isinstance(entry, dict):
            continue
        sha = str(entry.get("sha", "")).strip()
        subject = str(entry.get("subject", "")).strip()
        if not sha or not subject:
            # Skip junk; never ship empty placeholders downstream.
            continue
        commits.append(Commit(
            sha=sha,
            subject=subject,
            author_name=str(entry.get("author", "")).strip(),
            committed_at=_parse_iso(entry.get("committed_at", "")),
            body=str(entry.get("body", "")).strip(),
        ))

    return ReleaseMeta(
        generated_at=_parse_iso(data.get("generated_at", "")) or datetime.fromtimestamp(0),
        head_sha=str(data.get("head_sha", "")).strip(),
        branch=str(data.get("branch", "")).strip(),
        commits=commits,
    )


def commits_since(meta: ReleaseMeta, since_sha: str | None) -> list[Commit]:
    """Return commits ordered most-recent-first up to (excluding) since_sha.

    If since_sha is None or doesn't match any commit, returns the full
    list — same boundary semantics as GitHubCommitsService.commits_since.
    """
    if not since_sha:
        return list(meta.commits)

    out: list[Commit] = []
    for c in meta.commits:
        if c.sha == since_sha:
            break
        out.append(c)
    return out


def is_release_meta_available(path: Path = DEFAULT_META_PATH) -> bool:
    """Lightweight existence + parse check — used by the endpoint to
    decide whether to fast-fail with a clear 422.
    """
    try:
        read_release_meta(path)
        return True
    except ReleaseMetaUnavailable:
        return False
