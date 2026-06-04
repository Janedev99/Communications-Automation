# Jane Communication Automation

An AI-assisted email platform built for **Schilmoeller & Schoenfield, PC** (a tax and accounting firm). The system polls the firm's mailbox, categorizes every incoming email with AI, drafts suggested replies from the firm's knowledge base, and provides a staff review interface — no email leaves the firm without human approval. It also supports composing new outbound email, attachments in both directions, spam/delete management synced to Outlook, and a per-client saved-folder system.

---

## What It Does

**For the firm owner (Jane):**
- Surfaces emails that need her personal attention (IRS notices, legal issues, complaints) in an escalation queue
- Cuts time spent on routine client communication — most emails arrive with a ready-to-review AI draft
- Full visibility: audit log of every action, dashboard KPIs, sent-mail history threaded per client

**For staff:**
- AI categorizes every incoming email (document request, appointment, status update, …) with a confidence score and triage tier
- AI drafts a reply using the firm's knowledge base, past approved drafts, and rejection feedback — signed with Jane's configured signature
- Review → edit → approve → send workflow, with a 10-second undo countdown (per-user toggleable)
- Compose brand-new outbound emails (with optional AI drafting from an instruction)
- Attach files while drafting or replying; download attachments from any inbound *or* sent message
- Spam / Delete actions that mirror to the Outlook mailbox; Resolved status for finished threads
- Saved folders per client — sent replies auto-file into the client's folder
- Full-text search, bulk actions, and an interactive tutorials page

**Core pipeline:**
1. Poller fetches new mail from the Microsoft 365 mailbox (every 60s)
2. AI categorizes: category, confidence, summary, suggested tone, escalation check
3. Tier engine assigns a triage tier (T1 auto-eligible / T2 review / T3 escalate) from per-category rules
4. Non-escalated threads get an AI-drafted reply (knowledge base + feedback-loop context)
5. Staff review in the web UI; escalations route to Jane
6. Approved drafts send through the same mailbox with proper threading headers

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 |
| AI | **Anthropic Claude (primary)** via a pluggable LLM layer; optional OpenAI-compatible endpoint (RunPod / vLLM / OpenAI) with a built-in RunPod pod orchestrator; deterministic rules-engine fallback when no LLM is reachable |
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui |
| Email Integration | Microsoft Graph API (production), IMAP/SMTP (fallback option) |
| Auth | Server-side sessions (PostgreSQL), bcrypt, HttpOnly cookies, CSRF tokens |
| Deployment | Railway (Dockerfile builds) or docker-compose (Postgres + backend + frontend + Caddy) |

---

## Project Structure

```
jane-autocomms/
  backend/
    app/
      api/          # FastAPI routers (~60 endpoints across 12 routers)
      models/       # SQLAlchemy ORM models (13 tables)
      schemas/      # Pydantic request/response schemas
      services/     # Business logic (21 modules — see below)
      utils/        # Audit logging, sanitization
    alembic/        # Database migrations (001 → 017)
    scripts/        # Seed scripts (admin user, demo data), diagnostics
    tests/          # Pytest suite (in-memory SQLite, mocked providers)
  frontend/
    src/
      app/          # Next.js App Router pages (login + 13 dashboard pages)
      components/   # React components by domain (emails, drafts, escalations, …)
      hooks/        # SWR data-fetching hooks
      lib/          # API client, types, preferences, utilities
  docs/             # Handoff & operations documentation
  docker-compose.yml
```

Key backend services: `email_intake` (polling pipeline), `email_provider` (Graph/IMAP abstraction), `categorizer`, `tier_engine`, `draft_generator`, `draft_feedback` (learning loop), `escalation`, `auto_send` (gated by shadow mode + system setting), `auto_folder`, `ai_budget` (daily token cap), `llm_client` (provider abstraction), `runpod_orchestrator`/`runpod_watchdog` (optional self-hosted GPU lifecycle), `rules_engine` (no-LLM fallback), `pii_detector`, `notification` (Slack/log).

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 16+
- An Anthropic API key (or an OpenAI-compatible endpoint)

### 1. Clone and configure

```bash
git clone <repo-url>
cd jane-autocomms
cp .env.example .env
```

Edit `.env` — the file is fully commented. Minimum to run:
- `DATABASE_URL` — PostgreSQL connection string
- `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=sk-ant-...`
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — first admin account
- Email provider credentials (`EMAIL_PROVIDER=msgraph` + the four `MSGRAPH_*` vars, or IMAP/SMTP)

### 2. Database

```bash
psql -U postgres -c "CREATE USER jane_user WITH PASSWORD 'jane_pass';"
psql -U postgres -c "CREATE DATABASE jane_automation OWNER jane_user;"
```

### 3. Backend

```bash
cd backend
python -m venv venv
source venv/Scripts/activate      # Windows
source venv/bin/activate          # macOS/Linux

pip install -r requirements.txt
alembic upgrade head
python scripts/seed_admin.py      # idempotent
python scripts/seed_demo.py       # optional demo data

uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1
```

Interactive API docs: `http://localhost:8001/docs`

> Local development convention: the backend runs on **port 8001** (the frontend's default `NEXT_PUBLIC_API_URL` points there).

### 4. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # adjust if backend isn't on :8001
npm run dev
```

Open `http://localhost:3000` and log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

---

## API Overview

All routes are prefixed `/api/v1`. The full, always-current reference is the OpenAPI UI at `/docs`. By router:

| Router | Highlights |
|--------|-----------|
| `auth` | Login/logout, current user, change password, user management (admin) |
| `emails` | Thread list/detail, full-text search, compose new email (multipart, optional AI draft + attachments), attachment & inline-image download, status/assign/save/unsave, saved folders, bulk actions (close/assign/delete/spam/…), compliance export (admin) |
| `drafts` | Cross-thread draft list, generate/approve/revert/reject/regenerate, send (multipart with attachments, idempotency-keyed) |
| `escalations` | Queue list/detail, acknowledge, resolve with notes |
| `dashboard` | KPI stats, recent activity, public health check, system status |
| `knowledge` | Knowledge-base CRUD (soft delete) |
| `tier_rules` | Per-category T1 eligibility + confidence thresholds (admin) |
| `audit_log` | Filterable immutable audit trail (admin) |
| `system_settings` | Runtime toggles: `auto_send_enabled`, `draft_signature` (admin) |
| `integrations` | Health + config snapshot for DB / LLM / email provider / notifications (admin) |
| `runpod` | Pod wake, login draft-sweep, stop, status, cost history |
| `feedback` | Preview of the AI feedback context per category |

State-changing endpoints require a CSRF token (issued at login) alongside the session cookie.

---

## Architecture

### Email Processing Pipeline

```
Incoming Email
      |
      v
[Email Poller] ── polls M365 Graph (or IMAP) every 60s
      |
      v
[Store in DB] ── dedupe by Message-ID, group into threads (provider thread id → reply headers → new)
      |
      v
[AI Categorizer] ── category, confidence, summary, suggested tone   (rules-engine fallback if LLM down)
      |
      +──[Escalation detected]──> Escalation record → Jane's queue → notification (Slack/log)
      |
      v
[Tier Engine] ── T1 auto-eligible / T2 review / T3 escalate (per-category rules table)
      |
      v
[AI Draft Generator] ── knowledge base + feedback loop + configured signature
      |
      +──[T1 + auto_send_enabled + not SHADOW_MODE]──> auto-send   (OFF in production today)
      |
      v
[Staff Review UI] ── edit / approve / reject(reason) / regenerate / attach files
      |
      v
[Send via Graph] ── threading headers, attachments, idempotency key
      |
      v
[Auto-folder] ── sent thread files into the client's saved folder
```

### AI behavior

- **Categorization** and **draft generation** both run through the pluggable `llm_client` (Anthropic or OpenAI-compatible).
- Drafts use temperature 0.3, thread history capped at 10 messages / 6000 chars, and a prompt-injection guard (client content is fenced in `<CLIENT_EMAIL>` tags the model is told never to obey).
- The **feedback loop** feeds each draft prompt: past approved drafts (positive examples), staff-saved messages (curated style), and rejection reasons (negative patterns) — PII-filtered.
- **Signature**: Jane's signature lives in `system_settings.draft_signature` and is appended in code after generation (the model is forbidden from writing its own closing).
- **Greeting**: drafts address the sender by the name they signed their email with — never initials derived from the email address.
- **Budget**: every call counts against `DAILY_TOKEN_BUDGET` (default 1M tokens/day, resets at UTC midnight). Over budget → categorization falls back to the rules engine; drafting waits for the next day.
- **RunPod (optional)**: when `RUNPOD_POD_ID` is set, the orchestrator cold-starts a self-hosted GPU pod for drafting and a watchdog idle-stops it (default 5 min idle, 10 h/day cap), with automatic Claude fallback.

### Security

- bcrypt password hashing; server-side sessions in PostgreSQL (8-hour TTL, hourly cleanup)
- HttpOnly + SameSite cookies (Secure in production); CSRF double-submit on every mutation
- Login rate-limiting with trusted-proxy-aware client IPs
- Role-based access (staff vs admin); admin-only surfaces guarded server-side
- Immutable audit log of every state-changing action
- No client email content is stored as attachment binaries — attachments stream on-demand from the provider
- **No email is auto-sent in production** (`SHADOW_MODE=true` + `auto_send_enabled=false`)

---

## Database Schema

**13 tables** (Alembic migrations 001–017):

| Table | Purpose |
|-------|---------|
| `users` | Staff and admin accounts |
| `sessions` | Server-side auth sessions |
| `email_threads` | Conversation threads — status, category, tier, assignment, saved-folder |
| `email_messages` | Individual emails — direction, bodies, attachment metadata (JSON) |
| `draft_responses` | AI drafts — review workflow state, versioning, AI/token metadata, send idempotency |
| `escalations` | Items requiring the owner's attention — severity, acknowledge/resolve workflow |
| `knowledge_entries` | Firm knowledge base (templates / policies / snippets) used as AI context |
| `audit_log` | Immutable action trail |
| `tier_rules` | Per-category triage configuration (T1 eligibility + confidence threshold) |
| `system_settings` | Runtime key/value toggles (`auto_send_enabled`, `draft_signature`) |
| `ai_budget_usage` | Daily AI token accumulator |
| `runpod_state` | RunPod pod lifecycle persistence |
| `runpod_daily_usage` | Day-by-day pod uptime and cost history |

---

## Configuration

Everything is environment variables — see **`.env.example`** for the complete, commented list. The most important:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | required |
| `LLM_PROVIDER` | `anthropic` (production) or `openai_compat` | `openai_compat` |
| `ANTHROPIC_API_KEY` | Anthropic key (when provider is `anthropic`) | required for Anthropic |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | OpenAI-compat endpoint; `LLM_API_KEY` doubles as the RunPod account key for the orchestrator | empty |
| `EMAIL_PROVIDER` | `msgraph` (production) or `imap` | `imap` |
| `MSGRAPH_*` | Azure app registration (client id/secret, tenant, mailbox) | empty |
| `SHADOW_MODE` | **Gates auto-send only** — drafts still generate; nothing sends without a human | `false` (`true` in production) |
| `DAILY_TOKEN_BUDGET` | Daily AI token cap (0 = unlimited) | `1000000` |
| `EMAIL_POLL_INTERVAL_SECONDS` | Mailbox poll frequency | `60` |
| `RUNPOD_POD_ID` | Enables the pod orchestrator (empty = disabled) | empty |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Bootstrap admin account (`seed_admin.py`) | — |
| `APP_SECRET_KEY` | Session crypto key — boot fails in production on the dev default | dev value |

---

## Deployment

### Railway (current production)

Both services build from their own `Dockerfile` with a `railway.json`:

- **Backend** start command: `sh -c 'alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1'` — migrations run on every deploy. Health check: `/health`.
- **Frontend**: Next.js standalone build; `NEXT_PUBLIC_API_URL` must be set as a **Docker build arg** (it's inlined at build time), not a runtime variable.
- Postgres via the Railway plugin (`DATABASE_URL` injected).

> **Verify after every deploy** that the new commit is actually live — a past incident had production silently running a stale build while migrations lagged behind master.

### docker-compose (self-hosting)

`docker-compose.yml` at the repo root stands up Postgres 16, the backend, the frontend, and a Caddy reverse proxy (TLS termination, ports 80/443). The backend container applies migrations on start.

### Single-worker requirement

The email poller, session cleanup, and RunPod watchdog run inside the application process (lifespan tasks). **Deploy with exactly one worker** — multiple workers mean duplicate polling loops and concurrent writes for the same messages.

- Correct: `uvicorn app.main:app --workers 1`
- Wrong: `--workers 4` / multi-worker Gunicorn

To scale horizontally later, extract the poller into a dedicated single-instance process first.

---

## Operations Quick Reference

- **Auto-send is OFF in production** — two independent gates must both open: `SHADOW_MODE=false` (env) **and** `auto_send_enabled=true` (Settings UI / system_settings). Do not change without the firm's explicit sign-off.
- **Token budget exhausted?** AI calls 429 / fall back to rules until UTC midnight. Bulk reprocessing eats the budget fast.
- **Poller health** is visible at `GET /dashboard/health` (public) and on Settings → Integrations (admin).
- **Tests**: `cd backend && venv/Scripts/python -m pytest tests/ -q` — in-memory SQLite, mocked email/LLM providers, no real sends, safe to run anywhere.

See `docs/` for the full handoff and operations guide.

---

## License

Proprietary. Built for Schilmoeller & Schoenfield, PC.
