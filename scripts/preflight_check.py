"""
preflight_check.py - run BEFORE deploying to catch misconfigured production env.

Loads the .env at the repo root (or path given via --env), validates the values
that matter for a safe production launch, and exits non-zero on failure.

Usage:
    python scripts/preflight_check.py
    python scripts/preflight_check.py --env path/to/.env.production
    python scripts/preflight_check.py --strict   # treat warnings as failures

Exit codes:
    0 - all checks passed (warnings may have been printed)
    1 - at least one check failed
    2 - invalid invocation (missing file, etc.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Output helpers ───────────────────────────────────────────────────────────

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}  [ok]{RESET}   {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}  [warn]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}  [fail]{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{title}")


# ── Env loader (no python-dotenv dependency) ─────────────────────────────────


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        print(f"ERROR: {path} not found.", file=sys.stderr)
        sys.exit(2)
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split("#", 1)[0].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        out[key.strip()] = value
    return out


# ── Checks (return list[str]: empty = pass, non-empty = fail messages) ───────

Result = tuple[str, list[str], list[str]]  # (label, errors, warnings)


def check_app_env(env: dict[str, str]) -> Result:
    label = "APP_ENV is set to production"
    val = env.get("APP_ENV", "")
    if val == "production":
        return label, [], []
    if val == "development":
        return label, [], ["APP_ENV=development - preflight is meant for production deploys; continuing as a dry run"]
    return label, [f"APP_ENV must be 'production' or 'development', got {val!r}"], []


def check_secret_key(env: dict[str, str]) -> Result:
    label = "APP_SECRET_KEY is strong and not the default"
    val = env.get("APP_SECRET_KEY", "")
    errs: list[str] = []
    if not val:
        errs.append("APP_SECRET_KEY is empty")
    elif val in ("change-me-to-a-long-random-string", "dev-secret-key-replace-in-production"):
        errs.append("APP_SECRET_KEY is still the example value")
    elif len(val) < 32:
        errs.append(f"APP_SECRET_KEY is only {len(val)} chars; recommend 64+ (token_hex(32) gives 64)")
    return label, errs, []


def check_database_url(env: dict[str, str]) -> Result:
    label = "DATABASE_URL is set and uses psycopg2 dialect"
    val = env.get("DATABASE_URL", "")
    errs: list[str] = []
    if not val:
        errs.append("DATABASE_URL is empty")
    elif not val.startswith("postgresql+psycopg2://"):
        errs.append(
            f"DATABASE_URL must start with 'postgresql+psycopg2://' - got {val.split('://', 1)[0]}://..."
        )
    elif "localhost" in val or "127.0.0.1" in val:
        errs.append("DATABASE_URL points at localhost - change it to your managed Postgres host")
    return label, errs, []


def check_anthropic_key(env: dict[str, str]) -> Result:
    label = "ANTHROPIC_API_KEY is a real key"
    val = env.get("ANTHROPIC_API_KEY", "")
    if not val:
        return label, ["ANTHROPIC_API_KEY is empty"], []
    if val.startswith("sk-ant-placeholder"):
        return label, ["ANTHROPIC_API_KEY is the placeholder value"], []
    if not val.startswith("sk-ant-"):
        return label, [f"ANTHROPIC_API_KEY does not look like a real Anthropic key (expected 'sk-ant-...')"], []
    return label, [], []


def check_email_provider(env: dict[str, str]) -> Result:
    label = "Email provider credentials are complete"
    provider = env.get("EMAIL_PROVIDER", "imap").lower()
    errs: list[str] = []
    if provider == "msgraph":
        for key in ("MSGRAPH_CLIENT_ID", "MSGRAPH_CLIENT_SECRET", "MSGRAPH_TENANT_ID", "MSGRAPH_MAILBOX"):
            if not env.get(key):
                errs.append(f"{key} is empty (required when EMAIL_PROVIDER=msgraph)")
    elif provider == "imap":
        for key in ("IMAP_HOST", "IMAP_USERNAME", "IMAP_PASSWORD", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"):
            if not env.get(key):
                errs.append(f"{key} is empty (required when EMAIL_PROVIDER=imap)")
        if env.get("IMAP_USERNAME", "").lower() != env.get("SMTP_USERNAME", "").lower():
            errs.append("IMAP_USERNAME and SMTP_USERNAME must match (SPF/DKIM alignment)")
    else:
        errs.append(f"EMAIL_PROVIDER must be 'msgraph' or 'imap', got {provider!r}")
    return label, errs, []


def check_cors(env: dict[str, str]) -> Result:
    label = "CORS_ORIGINS contains no localhost entries"
    val = env.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in val.split(",") if o.strip()]
    if not origins:
        return label, ["CORS_ORIGINS is empty"], []
    if any("localhost" in o or "127.0.0.1" in o for o in origins):
        return label, [f"CORS_ORIGINS contains localhost - set it to the production frontend URL only"], []
    return label, [], []


def check_admin_password(env: dict[str, str]) -> Result:
    label = "ADMIN_PASSWORD is set and not the example value"
    val = env.get("ADMIN_PASSWORD", "")
    if not val:
        return label, ["ADMIN_PASSWORD is empty (seed_admin.py will refuse to run)"], []
    if val in ("change-me-before-deploying", "admin123"):
        return label, ["ADMIN_PASSWORD is still the example/dev value"], []
    if len(val) < 12:
        return label, [], [f"ADMIN_PASSWORD is only {len(val)} chars; recommend 16+"]
    return label, [], []


def check_shadow_mode(env: dict[str, str]) -> Result:
    label = "SHADOW_MODE recommended for first deploy"
    val = env.get("SHADOW_MODE", "false").lower()
    if val == "true":
        return label, [], []
    return label, [], [
        "SHADOW_MODE=false - strongly recommended to set SHADOW_MODE=true for the "
        "first 24-48h while you validate the email pipeline (drafts won't auto-generate)"
    ]


def check_notifications(env: dict[str, str]) -> Result:
    label = "At least one notification channel is configured"
    if env.get("SLACK_WEBHOOK_URL") or env.get("NOTIFY_LOG_FILE"):
        return label, [], []
    return label, [], [
        "Neither SLACK_WEBHOOK_URL nor NOTIFY_LOG_FILE is set - escalation alerts "
        "will only land in stdout. Recommended: set SLACK_WEBHOOK_URL."
    ]


CHECKS: list[Callable[[dict[str, str]], Result]] = [
    check_app_env,
    check_secret_key,
    check_database_url,
    check_anthropic_key,
    check_email_provider,
    check_cors,
    check_admin_password,
    check_shadow_mode,
    check_notifications,
]


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env", help="Path to .env file")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    args = parser.parse_args()

    print(f"{DIM}Checking {args.env}{RESET}")
    env = load_env(args.env)

    section("Required configuration")
    total_errs = 0
    total_warns = 0
    for check in CHECKS:
        label, errs, warns = check(env)
        if errs:
            fail(label)
            for e in errs:
                print(f"          - {e}")
            total_errs += len(errs)
        elif warns:
            warn(label)
            for w in warns:
                print(f"          - {w}")
            total_warns += len(warns)
        else:
            ok(label)

    print()
    if total_errs:
        print(f"{RED}FAIL{RESET}: {total_errs} error(s), {total_warns} warning(s). Fix the errors before deploying.")
        return 1
    if total_warns and args.strict:
        print(f"{RED}FAIL (strict){RESET}: {total_warns} warning(s) treated as failures.")
        return 1
    if total_warns:
        print(f"{YELLOW}OK with warnings{RESET}: {total_warns} warning(s). Review them, then deploy.")
        return 0
    print(f"{GREEN}OK{RESET}: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
