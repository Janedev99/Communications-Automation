# Jane Communication Automation

An email communication automation system built for Schiller CPA, a tax and accounting firm. The system captures incoming client emails, categorizes them using AI, generates draft responses, and provides a staff review interface before any email is sent.

---

## What It Does

**For the firm owner (Jane):**
- Automatically surfaces emails that need her personal attention (IRS audits, legal issues, complaints)
- Reduces time spent on routine client communication by 60-80%
- Full visibility into what staff are sending to clients

**For staff:**
- AI categorizes every incoming email (status update, document request, appointment, etc.)
- AI drafts a suggested response using the firm's knowledge base
- Staff review, edit, approve, and send -- no email goes out without human approval
- Escalation queue surfaces urgent items that need the owner's attention

**How it works:**
1. System polls the firm's Microsoft 365 mailbox every 60 seconds
2. New emails are categorized by AI (Claude) with 95%+ accuracy
3. Non-escalated emails get an AI-drafted response based on the firm's knowledge base
4. Staff review the draft in a web interface, edit if needed, and send
5. Emails matching escalation criteria (IRS notices, complaints, legal issues) go directly to Jane

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 |
| AI | Anthropic Claude Sonnet (categorization + draft generation) |
| Frontend | Next.js 14, TypeScript, Tailwind CSS, shadcn/ui |
| Email Integration | Microsoft Graph API (primary), IMAP/SMTP (fallback) |
| Auth | Server-side sessions, bcrypt, HttpOnly cookies |

---

## Project Structure

```
jane-communication-automation/
  backend/
    app/
      api/          # FastAPI route handlers
      models/       # SQLAlchemy ORM models
      schemas/      # Pydantic request/response schemas
      services/     # Business logic (categorizer, draft generator, email provider, etc.)
      utils/        # Audit logging
    alembic/        # Database migrations
    scripts/        # Seed scripts (admin user, demo data)
  frontend/
    src/
      app/          # Next.js App Router pages
      components/   # React components (emails, drafts, escalations, knowledge, layout)
      hooks/        # SWR data fetching hooks
      lib/          # API client, types, constants, utilities
```

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 16+
- Anthropic API key

### 1. Clone and configure

```bash
git clone <repo-url>
cd jane-communication-automation
cp .env.example .env
```

Edit `.env` and fill in:
- `ANTHROPIC_API_KEY` -- your Anthropic API key
- `DATABASE_URL` -- PostgreSQL connection string
- `ADMIN_PASSWORD` -- password for the admin account
- Microsoft Graph credentials (if using M365) or IMAP/SMTP credentials

### 2. Database setup

```bash
# Create the database
psql -U postgres -c "CREATE USER jane_user WITH PASSWORD 'jane_pass';"
psql -U postgres -c "CREATE DATABASE jane_automation OWNER jane_user;"
```

### 3. Backend

```bash
cd backend
python -m venv venv

# Windows
source venv/Scripts/activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
python scripts/seed_admin.py

# Optional: load demo data for testing
python scripts/seed_demo.py

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

API docs available at `http://localhost:8001/docs`

### 4. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Edit .env.local if your backend is on a different port

npm run dev
```

Open `http://localhost:3000` in your browser.

### 5. Login

Use the credentials from your `.env` file:
- Email: value of `ADMIN_EMAIL`
- Password: value of `ADMIN_PASSWORD`

---

## API Overview

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | Login with email/password |
| POST | `/api/v1/auth/logout` | End session |
| GET | `/api/v1/auth/me` | Get current user |
| POST | `/api/v1/auth/users` | Create user (admin) |
| GET | `/api/v1/auth/users` | List users (admin) |
| PUT | `/api/v1/auth/users/{id}` | Update user (admin) |

### Email Threads
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/emails` | List threads (filterable, paginated) |
| GET | `/api/v1/emails/{id}` | Get thread with messages |
| POST | `/api/v1/emails/{id}/categorize` | Re-categorize a thread |

### Draft Responses
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/drafts` | List all drafts (cross-thread) |
| POST | `/api/v1/emails/{id}/generate-draft` | Generate AI draft |
| GET | `/api/v1/emails/{id}/drafts` | List drafts for thread |
| PUT | `/api/v1/emails/{id}/drafts/{draftId}` | Edit draft text |
| POST | `/api/v1/emails/{id}/drafts/{draftId}/approve` | Approve draft |
| POST | `/api/v1/emails/{id}/drafts/{draftId}/reject` | Reject draft |
| POST | `/api/v1/emails/{id}/drafts/{draftId}/send` | Send approved draft |

### Escalations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/escalations` | List escalations (filterable) |
| GET | `/api/v1/escalations/{id}` | Get escalation detail |
| PUT | `/api/v1/escalations/{id}/acknowledge` | Acknowledge |
| PUT | `/api/v1/escalations/{id}/resolve` | Resolve with notes |

### Knowledge Base
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/knowledge` | List entries |
| POST | `/api/v1/knowledge` | Create entry |
| PUT | `/api/v1/knowledge/{id}` | Update entry |
| DELETE | `/api/v1/knowledge/{id}` | Soft-delete entry |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/dashboard/stats` | Aggregated statistics |
| GET | `/api/v1/dashboard/health` | Health check (public) |

---

## Architecture

### Email Processing Pipeline

```
Incoming Email
      |
      v
  [Email Poller] -- polls M365/IMAP every 60s
      |
      v
  [Store in DB] -- deduplicate by Message-ID, group into threads
      |
      v
  [AI Categorizer] -- Claude classifies: category, confidence, escalation check
      |
      +--[Escalation detected]--> Create escalation record, notify Jane
      |
      +--[No escalation]--> [AI Draft Generator] -- Claude drafts a reply using knowledge base
                                    |
                                    v
                            [Staff Review UI] -- edit, approve, reject
                                    |
                                    v
                            [Send via M365/SMTP] -- outbound email with thread continuity
```

### Escalation Criteria

Emails are automatically escalated to the firm owner when they contain:
- Client complaints or dissatisfaction
- Legal or tax liability issues
- Pricing disputes or refund demands
- New client onboarding questions
- IRS notice or audit mentions
- Penalties or legal risk indicators

### AI Draft Generation

- Uses Claude Sonnet at temperature 0.3 for natural-sounding but consistent responses
- Retrieves relevant knowledge base entries by email category
- Includes full thread history (last 10 messages, capped at 6000 chars)
- Firm identity and communication rules baked into the system prompt
- Failure is non-fatal: if draft generation fails, the email is still categorized and stored

### Security

- All passwords bcrypt-hashed (12 rounds)
- Server-side sessions stored in PostgreSQL (8-hour TTL)
- HttpOnly, SameSite cookies (Secure flag in production)
- Every state-changing action is audit-logged
- Role-based access control (staff vs admin)
- No email is sent without human approval

---

## Database Schema

**8 tables:**
- `users` -- staff and admin accounts
- `sessions` -- server-side auth sessions
- `email_threads` -- conversation threads with status and AI metadata
- `email_messages` -- individual emails within threads
- `draft_responses` -- AI-generated drafts with review workflow state
- `escalations` -- escalated items requiring owner attention
- `knowledge_entries` -- firm knowledge base for AI context
- `audit_log` -- complete audit trail of all actions

---

## Configuration

All configuration is via environment variables (`.env` file). Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | required |
| `ANTHROPIC_API_KEY` | Claude API key | required |
| `EMAIL_PROVIDER` | `msgraph` or `imap` | `imap` |
| `EMAIL_POLL_INTERVAL_SECONDS` | Polling frequency | `60` |
| `DRAFT_AUTO_GENERATE` | Auto-generate drafts on intake | `true` |
| `DRAFT_TEMPERATURE` | Claude temperature for drafts | `0.3` |
| `SESSION_TTL_HOURS` | Login session duration | `8` |

See `.env.example` for the full list with descriptions.

---

## License

Proprietary. Built for Schiller CPA.
