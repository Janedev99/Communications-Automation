# Deployment Guide

This document is the canonical guide for deploying the Jane Communication Automation portal to production. Follow it top-to-bottom for the first deploy. For subsequent deploys, only the sections marked with **[on every deploy]** apply.

## Architecture

Three Railway services:

| Service | Source | Notes |
|---|---|---|
| `backend` | `backend/Dockerfile` | FastAPI + Alembic + email poller. Single worker. |
| `frontend` | `frontend/Dockerfile` | Next.js 14 standalone output. |
| `postgres` | Railway plugin | Managed Postgres 16. |

The backend runs the email poller in-process. **Do not scale to multiple workers** — duplicate polling will cause double-processed emails. This is enforced by `--workers 1` in `backend/railway.json`.

## Required environment variables

These are set on the **Railway service** (not the repo). Copy from `.env.example` at the repo root — that file is the single source of truth and matches `backend/app/config.py` exactly.

### Backend service

**Required, must be set:**

| Variable | Where to get the value |
|---|---|
| `APP_ENV` | `production` |
| `APP_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Postgres service → Connect tab → "Postgres Connection URL" (must use `postgresql+psycopg2://` dialect — convert if needed) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → Settings → API Keys |
| `EMAIL_PROVIDER` | `msgraph` (M365) or `imap` |
| `CORS_ORIGINS` | The frontend service's public URL (no localhost in production) |
| `ADMIN_EMAIL` | Jane's email |
| `ADMIN_PASSWORD` | Strong password — Jane will change it on first login |

**Required when `EMAIL_PROVIDER=msgraph`:**

`MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`, `MSGRAPH_MAILBOX` — see the Setup Guide in the portal (Settings → Integrations → "Need help setting this up?").

**Required when `EMAIL_PROVIDER=imap`:**

`IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`. `IMAP_USERNAME` and `SMTP_USERNAME` **must match** — the config validator rejects mismatches.

**Recommended:**

| Variable | Default | Recommendation |
|---|---|---|
| `SHADOW_MODE` | `false` | Set to `true` for the first 24-48h |
| `DAILY_TOKEN_BUDGET` | `1000000` | Lower (e.g. `200000`) until you trust the cost profile |
| `SLACK_WEBHOOK_URL` | empty | Strongly recommend setting this so escalations don't get missed |
| `TRUSTED_PROXIES` | empty | Set to Railway's edge IP if you need to trust `X-Forwarded-For` |

### Frontend service

`NEXT_PUBLIC_API_URL` — **must be set as a Build Variable, not a Runtime Variable.** Next.js inlines `NEXT_PUBLIC_*` values at build time; runtime values have no effect. Set it to the public URL of the backend service.

## Pre-flight (local, before pushing)

1. Populate `.env` at the repo root with every value from the table above.
2. Run the preflight script:

   ```bash
   python scripts/preflight_check.py
   ```

   It validates: `APP_SECRET_KEY` is strong, `ANTHROPIC_API_KEY` is real (not placeholder), email provider creds match the chosen provider, `CORS_ORIGINS` has no localhost, `ADMIN_PASSWORD` isn't the example value. Exits non-zero on failure.

3. (Optional but recommended) Run on a fresh local Postgres to confirm the migration chain is clean:

   ```bash
   cd backend
   alembic upgrade head
   alembic current  # should print "010_system_settings (head)"
   ```

## Deploy sequence **[on every deploy]**

1. **Push to master.** Railway auto-deploys both services.
2. **Watch the backend logs.** Confirm:
   - `INFO:alembic.runtime.migration:Running upgrade ... -> 010_system_settings`
   - `Created admin user: jane@yourdomain.com` (first deploy only — script is idempotent)
   - `Uvicorn running on http://0.0.0.0:PORT`
3. **Run post-deploy verification:**

   ```bash
   python scripts/post_deploy_verify.py \
     --base-url https://YOUR-BACKEND.up.railway.app \
     --database-url "$DATABASE_URL"
   ```

   This checks `/health`, confirms `auto_send_enabled='false'` in `system_settings`, and confirms zero categories have `t1_eligible=true`.
4. **Open the frontend URL.** Log in with the admin credentials. Confirm the dashboard loads and `Settings → Integrations` shows all four integrations (with `Email Provider` and `Anthropic` healthy).

## First-deploy validation (do once, then never again)

5. **Set `SHADOW_MODE=true`** on the backend service. Redeploy.
6. **Send a test email** from a personal account to the configured mailbox. Within 60 seconds it should appear in the Emails page **with a category but no draft.**
7. **Flip `SHADOW_MODE=false`.** Redeploy.
8. **Send another test email.** Verify a draft is generated.
9. **Smoke-test the send flow:** approve the draft to a test recipient (e.g. your personal email). Confirm delivery and that the audit log shows the send event.
10. **Confirm the safety gates one more time:**
    - `Settings → Triage Rules` — every category should show "Manual review only" (no T1 toggles enabled).
    - `Settings → Integrations` — overall status green.
11. **Hand the URL to Jane.**

## Rolling back

Two paths, in order of preference:

1. **Promote the previous deploy** in the Railway dashboard. The "Deployments" tab on each service has a "Redeploy" button on each prior build. This rolls back the application code without touching the database.
2. **Database rollback.** Only do this if a migration was the cause and the previous app version is incompatible. Run `alembic downgrade -1` from a one-off shell on the backend service. The downgrade scripts for migrations 001–010 are present, but downgrades drop columns — back up the database first via Railway's snapshot tool.

If the email poller is the suspected cause, set `EMAIL_POLL_INTERVAL_SECONDS=99999` (effectively disable) and redeploy. Diagnose without traffic, then restore.

## Reference: critical safety gates

There are **two** independent gates blocking unattended email sends. Both must be opened to enable T1 auto-send:

1. **Global kill switch** — `system_settings.auto_send_enabled` must be `'true'`. Default `'false'` (set by migration 010).
2. **Per-category opt-in** — `tier_rules.t1_eligible` must be `true` for the email's category. Default `false` for every category (set by migration 009). Categories `complaint`, `urgent`, and `uncategorized` are hard-locked at the API layer and cannot be enabled.

If post-deploy verification finds either gate in an unexpected state, **do not share the URL** until you've confirmed the change was intentional.

## Troubleshooting

**Backend container restarts in a loop**

Check the logs for the failure. Most common causes:
- `ValueError: APP_SECRET_KEY is the development default` — the validator is doing its job. Set a real key.
- `alembic upgrade head` fails — usually a database connectivity issue. Check `DATABASE_URL` and that the Postgres service is running.
- `seed_admin.py` exits 1 — `ADMIN_PASSWORD` is empty.

**Drafts aren't generating**

Check `Settings → Integrations`:
- If Anthropic is "Not configured" — the API key is missing or placeholder.
- If Anthropic is "Degraded" with budget at 100% — daily token budget hit. Raise `DAILY_TOKEN_BUDGET` or wait until tomorrow.
- If Anthropic is healthy but drafts still missing — check `SHADOW_MODE` is `false` and `DRAFT_AUTO_GENERATE=true`.

**No emails arriving in the queue**

Check `Settings → Integrations → Email Provider`:
- "Not configured" — credentials missing.
- "Degraded" with "No successful poll" — the poller can't connect. For Graph: verify admin consent was granted on the application permissions. For IMAP: verify you're using an app password, not the account password.

**Frontend says "Failed to load"**

Almost always `NEXT_PUBLIC_API_URL` was set as a runtime variable instead of a build variable, or `CORS_ORIGINS` on the backend doesn't include the frontend's URL.
