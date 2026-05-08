"""Generate backend/release-meta.json from `git log`.

Adopts cappj's pattern: a build-time script bakes the last N commits into
a JSON file the backend reads at request time. Removes runtime dependence
on the GitHub API, on a configured token, and on admins copy-pasting
`git log` output. The release-notes "Generate from commits" button works
zero-input as long as this file is fresh.

Trigger points:
    - Local dev: invoked automatically by FastAPI lifespan if file is
      missing or stale (>5 min). See app/main.py.
    - CI / Docker build: invoke explicitly before the runtime image is
      sealed. The build stage needs `.git/`; the runtime image does not.

Output schema (matches the runtime reader in app/services/release_meta_file.py):
    {
        "generated_at": ISO-8601 UTC timestamp,
        "head_sha":     str,
        "branch":       str,
        "commits": [
            {
                "sha":          str,
                "subject":      str,
                "body":         str,
                "author":       str,
                "committed_at": ISO-8601 timestamp,
            },
            ...
        ]
    }

Usage:
    python scripts/generate_release_meta.py [--output PATH] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Default output is alongside the backend package — the lifespan reader
# uses the same path. Both relative to the backend/ working directory.
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "release-meta.json"
DEFAULT_LIMIT = 200

# Field separator within a commit record.
_FS = "\x1f"  # ASCII unit separator
# Record separator between commits.
_RS = "\x1e"  # ASCII record separator

_GIT_LOG_FORMAT = (
    "%H" + _FS +
    "%s" + _FS +
    "%an" + _FS +
    "%aI" + _FS +
    "%b" + _RS
)


def _run_git(args: list[str], cwd: Path) -> str:
    """Run a git subcommand and return stdout, stripped."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git binary not found on PATH — release-meta generation requires git."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git {' '.join(args)!r} failed: {exc.stderr.strip()}"
        ) from exc
    return result.stdout


def _parse_commits(raw: str) -> list[dict]:
    """Parse the structured output of `git log` into commit dicts."""
    commits: list[dict] = []
    # Strip a trailing record separator if present.
    raw = raw.rstrip(_RS + "\n")
    if not raw:
        return commits
    for record in raw.split(_RS):
        record = record.lstrip("\n")  # gap between records is "\n"
        if not record:
            continue
        parts = record.split(_FS)
        # Expect 5 fields. Defensive against malformed records.
        if len(parts) < 4:
            logger.warning("Skipping malformed git log record: %r", record[:80])
            continue
        sha, subject, author, committed_at = parts[0], parts[1], parts[2], parts[3]
        body = parts[4] if len(parts) >= 5 else ""
        commits.append({
            "sha": sha.strip(),
            "subject": subject.strip(),
            "body": body.strip(),
            "author": author.strip(),
            "committed_at": committed_at.strip(),
        })
    return commits


def generate(*, output_path: Path, limit: int, repo_root: Path) -> dict:
    """Generate the meta file. Returns the dict that was written."""
    if not (repo_root / ".git").exists():
        raise RuntimeError(
            f"Not a git repository: {repo_root}. "
            "release-meta generation requires .git/ to be present at build time."
        )

    head_sha = _run_git(["rev-parse", "HEAD"], cwd=repo_root).strip()
    try:
        branch = _run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root,
        ).strip()
    except RuntimeError:
        branch = "(detached)"

    raw = _run_git(
        [
            "log",
            f"-{limit}",
            f"--pretty=format:{_GIT_LOG_FORMAT}",
            "HEAD",
        ],
        cwd=repo_root,
    )
    commits = _parse_commits(raw)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head_sha": head_sha,
        "branch": branch,
        "commits": commits,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> int:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO,
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Max commits to include (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd().parent if Path.cwd().name == "backend" else Path.cwd(),
        help="Path to the repo root (default: parent of CWD if CWD is backend/, else CWD)",
    )
    args = parser.parse_args()

    try:
        meta = generate(
            output_path=args.output,
            limit=args.limit,
            repo_root=args.repo_root,
        )
    except RuntimeError as exc:
        logger.error("generate-release-meta failed: %s", exc)
        return 1

    logger.info(
        "Wrote %s — %d commits, head=%s, branch=%s",
        args.output, len(meta["commits"]), meta["head_sha"][:8], meta["branch"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
