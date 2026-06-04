# Schilmoeller & Schoenfield, PC — Staff Portal & AI Communications Agent
## User Guide & Integrations

**Audience:** Jane, firm staff, and whoever administers the portal.
**Date:** 2026-06-04

This guide covers day-to-day use of the portal and how to set up its
integrations. For migration/hosting/operations, see `docs/HANDOFF.md`; for
the technical deep-dive, see the repository `README.md`.

> **The best companion to this guide is inside the app.** The **Tutorials**
> page (sidebar → Tutorials) walks every major feature with live visual
> examples, and Settings → **Integrations** contains step-by-step setup
> guides with status indicators. This document deliberately contains no
> screenshots — the portal handles real client email, and screenshots of
> production data don't belong in a shareable file. The in-app tutorials use
> safe dummy data instead.

---

## Part 1 — Using the App

### 1.1 Getting started

- **Access:** the portal is a website — open the firm's portal URL in any
  browser and bookmark it. On a phone, use the same URL in the mobile
  browser (no app store install). *Note: the mobile layout works but is not
  yet optimized — a refinement is on the roadmap.*
- **Login:** email + password (an admin creates accounts under Settings).
  Sessions last 8 hours, then you log in again.
- **First visit:** head to the **Tutorials** page first — it's a guided tour
  of everything below, with interactive examples.
- **Password:** change it anytime under Settings → your profile section.

### 1.2 What the system does while you sleep

Every 60 seconds the portal checks the firm's mailbox. Each new email is:

1. **Categorized** by AI (document request, appointment, status update,
   complaint, …) with a confidence score
2. **Tiered**: T1 (routine, auto-eligible) / T2 (staff review — the default)
   / T3 (escalate to Jane)
3. **Drafted**: a suggested reply is written from the firm's knowledge base,
   past approved replies, and rejection feedback
4. **Escalated** if it matches the firm's escalation criteria (IRS notices,
   complaints, legal issues, …) — these go straight to Jane's queue

**Nothing is ever sent automatically.** Auto-send is held behind two
independent switches (an environment flag and an admin setting), and both
are OFF in production. Every email a client receives was approved by a
person first.

### 1.3 The Inbox (Emails page)

- **Statuses:** New → Categorized → Draft Ready → Sent / Resolved; plus
  Deleted and Spam (see below).
- **Filters & search:** filter by status, category, tier, assignment, or
  saved folder; full-text search covers subjects, summaries, senders, and
  message bodies.
- **Bulk actions:** select multiple threads to resolve, assign, delete,
  spam, recategorize, or save in one go.
- **Spam / Delete mirror to Outlook.** Deleting or spamming a thread in the
  portal also moves the real message to Deleted Items / Junk Email in the
  mailbox — and it can be recovered from Outlook if needed.
- **Keyboard shortcuts:** `j`/`k` walk the list, `Enter` opens, `a`/`r`
  approve/reject the active draft. Press `?` for the full list.
- **Outlook stays in sync.** Replying from Outlook (e.g. on your phone) is
  fine — the portal sees the conversation either way.

### 1.4 Reviewing and sending AI drafts

Open a thread → the right-hand panel holds the AI draft:

- **Read the AI's reasoning:** category, confidence meter, and a "what
  shaped this draft" indicator (past approvals, saved messages, rejection
  feedback for this category).
- **Edit** the draft text directly — your version is kept alongside the
  AI original.
- **Tone override:** regenerate in a different tone (professional /
  empathetic / urgent / direct).
- **Attachments:** attach files at any point while drafting (paperclip).
  Attachments survive regeneration, and you can also download any
  attachment a client sent — or one the firm sent — from the conversation
  bubbles.
- **Approve → Send.** Sending starts a 10-second countdown with an Undo
  button (you can disable the countdown per-user under Settings →
  Sending).
- **Your signature is added automatically at send** — you'll see exactly
  what will be appended in the dashed "Signature" preview under the editor.
  It's your personal signature (Settings → My Signature), or the company
  signature if you haven't set one.
- **Reject (with a reason)** when a draft misses the mark — the reason
  feeds back into future drafts for that category. Regenerate does a
  reject + fresh draft in one step.

### 1.5 Composing a new email

Click **Compose** (sidebar) for a Gmail-style compose window:

- Write it yourself, or switch to **"Draft with AI"** and describe what the
  email should say — the AI proposes a subject and body you can edit.
- To / Cc, attachments, and the same automatic signature handling as
  replies. Sent composes create a new conversation thread in the portal.

### 1.6 Saved folders

- When you send a reply, the conversation **auto-files into a folder named
  after the client** — "I dealt with it" filing without any clicks.
- You can also save threads or individual messages manually, with optional
  notes, into any folder. The **Saved** page lists folders with counts and
  supports cross-folder search.

### 1.7 Escalations (Jane's queue)

Emails flagged T3 land on the **Escalations** page, sorted by severity
(low → critical). Workflow: **Acknowledge** (claimed) → **Resolve** (with
notes). The dashboard and sidebar surface unattended high/critical items.

### 1.8 Knowledge Base — teaching the AI

The AI drafts from the **Knowledge** page's entries:

- **Response templates** — full example replies
- **Policies** — firm rules the AI must respect
- **Snippets** — reusable phrases

Categorize and tag entries; the draft generator pulls matching context per
email category. *Keeping this current improves drafts more than anything
else.* The AI also learns passively from your approvals, edits, saved
messages, and rejection reasons.

### 1.9 Analytics — monitoring the system

The **Analytics** page (sidebar) shows, over a 7/30/90-day range:

- **AI Token Usage** — today's usage against the daily budget (the bar goes
  amber at 70%, red at 90%), daily history, and how many days the budget
  ran out. When the budget is exhausted, drafting pauses until midnight UTC
  and categorization falls back to keyword rules — the page tells you if
  that's been happening.
- **Email Volume** — conversations per day, category mix, triage tiers
- **Draft Workflow** — how many drafts were generated/sent, the **edit
  rate** (how often staff change AI drafts — falling = the AI is learning),
  and rejections
- **Escalations** — open items and daily trend

### 1.10 Settings

| Section | Who | What |
|---|---|---|
| My Signature | everyone | Your personal signature, appended to everything **you** send. Leave blank to use the company signature. |
| Company signature | admin | The firm-level block — used for auto-sent mail and as everyone's fallback. |
| Sending | everyone | Disable/enable the 10-second send countdown (per-user, per-browser). |
| Team Members | admin | Create/deactivate accounts, set staff vs admin role. |
| Triage Rules | admin | Per-category T1 eligibility + confidence thresholds. Complaint/urgent/promotional are locked to review-only. |
| Integrations | admin | Live health of database, AI provider, email provider, notifications — plus the setup guides below. |
| RunPod | admin | Self-hosted GPU controls (dormant — the firm runs on Anthropic). |

---

## Part 2 — Integrations Setup (admin)

Everything below is configured with **environment variables** on the hosting
platform (see `.env.example` in the repository for the full annotated
list). The portal's Settings → **Integrations** page shows live status for
each and contains the same guides interactively.

### 2.1 Email — Microsoft 365 via Graph (production setup)

Uses an Azure app registration; no mailbox password involved.

1. Sign in to **portal.azure.com** with a Microsoft 365 **admin** account →
   "App registrations" → **New registration**. Single tenant; redirect URI
   blank.
2. In the app: **API permissions** → Add → Microsoft Graph → **Application
   permissions** → add `Mail.Read`, `Mail.Send`, `Mail.ReadWrite` → click
   **Grant admin consent** (required — without it the portal can't read
   mail).
3. **Certificates & secrets** → New client secret (≤24 months). Copy the
   value immediately — it's shown once. Note the **Application (client)
   ID** and **Directory (tenant) ID** from Overview.
4. Set the environment variables and redeploy:
   ```
   EMAIL_PROVIDER=msgraph
   MSGRAPH_TENANT_ID=<directory-tenant-id>
   MSGRAPH_CLIENT_ID=<application-client-id>
   MSGRAPH_CLIENT_SECRET=<the-secret-value>
   MSGRAPH_MAILBOX=jane@yourfirm.com
   ```
5. Within a minute or two the Integrations page should show **Healthy** and
   new mail starts appearing.

**Secret expiry:** client secrets expire (max 24 months) — calendar a
reminder; when it lapses, polling and sending stop until a new secret is
set.

### 2.2 Email — IMAP/SMTP (alternative)

Works with Gmail, free Outlook, etc., using an app password. Set
`EMAIL_PROVIDER=imap` plus the `IMAP_*`/`SMTP_*` variables (IMAP and SMTP
usernames **must match** — the portal refuses to boot otherwise, to protect
email deliverability).

**Caveat:** spam/delete mirroring to the mailbox works on Microsoft Graph
only — on IMAP, portal-side Delete/Spam does not move the real message.

### 2.3 AI — Anthropic (production setup)

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...      # console.anthropic.com → API Keys
DAILY_TOKEN_BUDGET=1000000        # daily cap; 0 disables
```

The budget caps spend per calendar day (UTC). The Analytics page tracks it.
An OpenAI-compatible self-hosted path also exists (`LLM_PROVIDER=
openai_compat` + a RunPod pod with auto start/stop orchestration) but is
dormant — see `.env.example` if it's ever revived.

### 2.4 Notifications — Slack and/or log file

Escalations and auto-send events can notify:

- `SLACK_WEBHOOK_URL` — create an Incoming Webhook in Slack pointed at an
  alerts channel and paste the URL
- `NOTIFY_LOG_FILE` — a file path for JSON-line notifications

Either, both, or neither — at least one is recommended so urgent items
aren't missed.

### 2.5 Verifying everything at once

Settings → **Integrations** shows four cards — Database, AI provider, Email
provider, Notifications — each with live status and configuration summary.
All green = the system is fully operational. The public health endpoint
(`<backend-url>/health`) is suitable for external uptime monitors.

---

## FAQ

**Does using Outlook directly break anything?** No — the portal polls the
same mailbox and threads conversations by their mail headers. Reply from
wherever is convenient.

**Why did a draft pause / categorization look "keyword-based" today?** The
daily AI token budget likely ran out — check Analytics. It resets at
midnight UTC.

**Who sees what?** Staff and admins see the same inbox, drafts, saved
folders, knowledge base, and analytics. Admin-only: user management, triage
rules, company signature, integrations, audit log, and the compliance
export.

**Where's the audit trail?** Every state-changing action (sends, approvals,
deletes, setting changes) is recorded — admins can browse it on the Audit
Log page or export thread data via the compliance endpoint.

**Something looks wrong — where do I start?** Settings → Integrations
(anything not green?), then Analytics (budget exhausted?), then the Audit
Log for what happened recently.
