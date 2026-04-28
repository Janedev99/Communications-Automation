"""
post_deploy_verify.py - run AFTER deploy to confirm the live system is healthy
and the safety gates that prevent unattended email sends are still in place.

Performs three checks:

  1. GET <base-url>/health returns 200
  2. Direct DB query: system_settings.auto_send_enabled == 'false'
  3. Direct DB query: count(tier_rules where t1_eligible=true) == 0

Usage:
    python scripts/post_deploy_verify.py \\
        --base-url https://api.jane.example.com \\
        --database-url postgresql+psycopg2://user:pass@host:5432/db

If --database-url is omitted, the script reads it from the DATABASE_URL env var
(or the .env file at the repo root). If --base-url is omitted, it defaults to
http://localhost:8000.

Exit codes:
    0 - all checks passed; safe to share the URL with users
    1 - at least one check failed; investigate before going live
    2 - invalid invocation (missing tools, etc.)

Override the safety expectation with --allow-auto-send if (and only if) you
intentionally enabled T1 auto-send. The script will still run the check but
will not fail when auto_send_enabled='true' is observed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}  [ok]{RESET}   {msg}")


def fail(msg: str) -> None:
    print(f"{RED}  [fail]{RESET} {msg}")


def info(msg: str) -> None:
    print(f"{DIM}    {msg}{RESET}")


# ── .env fallback loader (shared with preflight, kept duplicated to avoid an
# inter-script import dependency) ────────────────────────────────────────────


def load_env_value(key: str) -> str:
    if key in os.environ:
        return os.environ[key]
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return ""
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            v = v.split("#", 1)[0].strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            return v
    return ""


# ── Checks ───────────────────────────────────────────────────────────────────


def check_health(base_url: str, timeout: float) -> bool:
    label = f"GET {base_url.rstrip('/')}/health returns 200"
    url = base_url.rstrip("/") + "/health"
    try:
        req = Request(url, headers={"User-Agent": "post-deploy-verify/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read(4096).decode("utf-8", errors="replace")
        if status == 200:
            ok(label)
            info(body[:200])
            return True
        fail(label)
        info(f"got status {status}")
        return False
    except HTTPError as e:
        fail(label)
        info(f"HTTP {e.code}: {e.reason}")
        return False
    except URLError as e:
        fail(label)
        info(f"connection error: {e.reason}")
        return False
    except Exception as e:
        fail(label)
        info(f"unexpected error: {e}")
        return False


def check_safety_gates(database_url: str, allow_auto_send: bool) -> bool:
    """Run the two SQL checks that guard against unattended email sends."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        fail("sqlalchemy is not installed - run from the backend/ venv or `pip install sqlalchemy psycopg2-binary`")
        return False

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
    except Exception as e:
        fail("could not create database engine")
        info(str(e))
        return False

    all_ok = True

    label_a = "system_settings.auto_send_enabled == 'false'"
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value FROM system_settings WHERE key = 'auto_send_enabled'")
            ).fetchone()
        if row is None:
            fail(label_a)
            info("row missing - migration 010 may not have run; check `alembic current`")
            all_ok = False
        else:
            value = row[0]
            if value == "false":
                ok(label_a)
            elif allow_auto_send:
                ok(f"{label_a} (got 'true' - accepted via --allow-auto-send)")
            else:
                fail(label_a)
                info(f"got value={value!r} - rerun with --allow-auto-send if this is intentional")
                all_ok = False
    except Exception as e:
        fail(label_a)
        info(str(e))
        all_ok = False

    label_b = "count(tier_rules where t1_eligible=true) == 0"
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT COUNT(*) FROM tier_rules WHERE t1_eligible = true")
            ).fetchone()
        count = int(row[0]) if row else -1
        if count == 0:
            ok(label_b)
        elif allow_auto_send:
            ok(f"{label_b} (got {count} - accepted via --allow-auto-send)")
        else:
            fail(label_b)
            info(f"got count={count} - at least one category has T1 enabled. Rerun with --allow-auto-send if intentional")
            all_ok = False
    except Exception as e:
        fail(label_b)
        info(str(e))
        all_ok = False

    return all_ok


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--database-url", default=None, help="Postgres URL (defaults to DATABASE_URL env / .env)")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout (seconds)")
    parser.add_argument(
        "--allow-auto-send",
        action="store_true",
        help="Don't fail if auto_send_enabled='true' or any category has t1_eligible=true",
    )
    parser.add_argument("--skip-db", action="store_true", help="Skip the database safety gate checks")
    args = parser.parse_args()

    print(f"\nVerifying deploy at {args.base_url}\n")

    health_ok = check_health(args.base_url, args.timeout)

    db_ok = True
    if not args.skip_db:
        db_url = args.database_url or load_env_value("DATABASE_URL")
        if not db_url:
            fail("no database URL - pass --database-url or set DATABASE_URL")
            db_ok = False
        else:
            print()
            db_ok = check_safety_gates(db_url, args.allow_auto_send)

    print()
    if health_ok and db_ok:
        print(f"{GREEN}OK{RESET}: deploy is healthy and safety gates are in place.")
        return 0
    print(f"{RED}FAIL{RESET}: at least one check failed. Do not share the URL until fixed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
