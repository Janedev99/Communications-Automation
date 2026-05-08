"""Unit tests for app/services/release_meta_file.py.

Covers parsing, since_sha boundary slicing, and graceful failures when
the meta file is missing or malformed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.release_meta_file import (
    ReleaseMetaUnavailable,
    commits_since,
    is_release_meta_available,
    read_release_meta,
)


def _write_meta(tmp_path: Path, payload: dict | str) -> Path:
    p = tmp_path / "release-meta.json"
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _sample_meta(commits: list[dict] | None = None) -> dict:
    return {
        "generated_at": "2026-05-08T12:00:00+00:00",
        "head_sha": "abc123abc123",
        "branch": "FEAT/test",
        "commits": commits or [
            {
                "sha": "aaa111aaa111",
                "subject": "feat: add thing",
                "author": "Dev",
                "committed_at": "2026-05-08T11:00:00+00:00",
                "body": "",
            },
            {
                "sha": "bbb222bbb222",
                "subject": "fix: broken thing",
                "author": "Dev",
                "committed_at": "2026-05-07T11:00:00+00:00",
                "body": "",
            },
            {
                "sha": "ccc333ccc333",
                "subject": "chore: bump",
                "author": "Dev",
                "committed_at": "2026-05-06T11:00:00+00:00",
                "body": "",
            },
        ],
    }


# ── Happy path ───────────────────────────────────────────────────────────────


def test_read_release_meta_parses_full_shape(tmp_path):
    p = _write_meta(tmp_path, _sample_meta())
    meta = read_release_meta(p)
    assert meta.head_sha == "abc123abc123"
    assert meta.branch == "FEAT/test"
    assert len(meta.commits) == 3
    c0 = meta.commits[0]
    assert c0.sha == "aaa111aaa111"
    assert c0.subject == "feat: add thing"
    assert c0.author_name == "Dev"
    assert c0.body == ""


def test_read_release_meta_preserves_body_field(tmp_path):
    """Body is critical for the [user-facing] opt-in token to work."""
    payload = _sample_meta([
        {
            "sha": "x" * 12,
            "subject": "chore: bump",
            "author": "Dev",
            "committed_at": "2026-05-08T00:00:00+00:00",
            "body": "[user-facing] this one matters",
        },
    ])
    p = _write_meta(tmp_path, payload)
    meta = read_release_meta(p)
    assert meta.commits[0].body == "[user-facing] this one matters"


# ── Slicing ──────────────────────────────────────────────────────────────────


def test_commits_since_returns_full_list_when_sha_unknown(tmp_path):
    p = _write_meta(tmp_path, _sample_meta())
    meta = read_release_meta(p)
    sliced = commits_since(meta, "nonexistent_sha")
    assert len(sliced) == 3


def test_commits_since_stops_at_boundary(tmp_path):
    p = _write_meta(tmp_path, _sample_meta())
    meta = read_release_meta(p)
    # Boundary = bbb (the 2nd commit). Expect only the 1st returned.
    sliced = commits_since(meta, "bbb222bbb222")
    assert len(sliced) == 1
    assert sliced[0].sha == "aaa111aaa111"


def test_commits_since_returns_full_when_since_sha_none(tmp_path):
    p = _write_meta(tmp_path, _sample_meta())
    meta = read_release_meta(p)
    sliced = commits_since(meta, None)
    assert len(sliced) == 3


# ── Error paths ──────────────────────────────────────────────────────────────


def test_missing_file_raises_unavailable(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(ReleaseMetaUnavailable):
        read_release_meta(missing)


def test_malformed_json_raises_unavailable(tmp_path):
    p = _write_meta(tmp_path, "this is not json {{{")
    with pytest.raises(ReleaseMetaUnavailable):
        read_release_meta(p)


def test_missing_commits_key_raises_unavailable(tmp_path):
    p = _write_meta(tmp_path, {"head_sha": "x", "branch": "y"})
    with pytest.raises(ReleaseMetaUnavailable):
        read_release_meta(p)


def test_commits_not_a_list_raises_unavailable(tmp_path):
    p = _write_meta(tmp_path, {"commits": "not a list"})
    with pytest.raises(ReleaseMetaUnavailable):
        read_release_meta(p)


def test_invalid_commit_entries_are_skipped_not_fatal(tmp_path):
    """Junk entries (missing sha or subject) are silently skipped."""
    payload = _sample_meta([
        {"sha": "good111good111", "subject": "feat: ok", "author": "D", "committed_at": "", "body": ""},
        {"subject": "missing sha"},  # dropped
        {"sha": "abc", "subject": ""},  # dropped (empty subject)
        "not a dict",  # dropped
        {"sha": "good222good222", "subject": "fix: also ok", "author": "D", "committed_at": "", "body": ""},
    ])
    p = _write_meta(tmp_path, payload)
    meta = read_release_meta(p)
    assert len(meta.commits) == 2
    assert meta.commits[0].sha == "good111good111"
    assert meta.commits[1].sha == "good222good222"


def test_is_release_meta_available_reflects_state(tmp_path):
    missing = tmp_path / "missing.json"
    assert is_release_meta_available(missing) is False

    p = _write_meta(tmp_path, _sample_meta())
    assert is_release_meta_available(p) is True
