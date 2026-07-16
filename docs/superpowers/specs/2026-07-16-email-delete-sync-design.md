# Bidirectional email delete sync (Outlook ↔ app)

**Date:** 2026-07-16
**Branch:** `FEAT/email-delete-sync`
**Source:** Client call 2026-07-10 — "I delete on my phone/Outlook but it lingers in the app to-do."

## Context

Deletion sync is currently **one-directional**:
- **App → Outlook (works):** `POST /emails/{id}/trash` and `/spam` call Graph
  `/messages/{id}/move` (→ deleteditems / junkemail) and flip `thread.status`
  to `deleted` / `spam`. Always-on.
- **Outlook → app (missing):** the poller (`email_intake.py`, 60s) only fetches
  **Inbox unread**, marks it read, and is strictly add-only. Nothing detects a
  message that left the Inbox, so deleting mail in Outlook leaves the app
  thread lingering in the to-do.

This iteration adds the **Outlook → app** direction. Folders remain out of it —
the hard invariant (folders never sync to Outlook) is untouched; this is
strictly about email deletions.

## Approach — delta reconciliation on Deleted Items + Junk

Detect **arrival in Deleted Items / Junk** (not departure from Inbox — a message
filed into a custom folder also leaves the Inbox and must NOT be treated as
deleted). Use Graph delta queries so each poll only sees what newly arrived.

1. **`sync_state` table (migration 022):** `key` (PK, str), `value` (text,
   nullable — the deltaLink), `updated_at`. Generic key/value for sync cursors.
   Keys: `delta:deleteditems`, `delta:junkemail`.
2. **Provider method** `MSGraphProvider.delta_folder_messages(folder, delta_link)`
   → `GET /mailFolders/{folder}/messages/delta?$select=internetMessageId`,
   following `@odata.nextLink` pages to the terminal `@odata.deltaLink`. Returns
   `(added_internet_message_ids, next_delta_link)`. Added to the `EmailProvider`
   ABC as a no-op default (IMAP inherits the no-op).
3. **Reconcile step** in the poller, after the existing fetch, gated on
   `EMAIL_DELETE_SYNC`: for Deleted Items → status `deleted`, Junk → `spam`.
   For each returned `internetMessageId`, look up the local `EmailMessage` by
   `message_id_header`; if found and its thread is in an **active** status
   (not already deleted/spam/closed), flip the thread status, bump `updated_at`,
   and write an `ActivityLog` entry (system actor) noting the Outlook-driven
   change. Unmatched ids (mail the app never ingested) are skipped.
4. **First-run baseline:** when no deltaLink is stored yet, walk to the deltaLink
   WITHOUT acting on the items (they are pre-existing deletions). Reconciliation
   only acts on deletions that happen after the feature is first enabled.

## Decisions

- **Flag-gated:** new `EMAIL_DELETE_SYNC` env (default **false**), mirroring
  `OUTLOOK_FOLDER_SYNC`. Ship dark; enable after smoke. App → Outlook delete
  stays always-on and unchanged.
- **Safety:** this direction only READS Outlook and changes a LOCAL status
  (reversible via the existing `PUT /emails/{id}/status` restore). It never
  deletes anything in Outlook — no risk of destroying mail.
- **Restores out of scope:** Deleted Items → Inbox in Outlook does NOT un-delete
  in the app (v2). `@removed` delta entries are ignored in v1.
- **msgraph-only:** the delta path is a no-op under the IMAP provider (prod uses
  Graph for delete/spam already).
- **Thread granularity:** a matched message flips its whole thread's status,
  consistent with how app → Outlook trash moves all inbound messages of a thread.

## Files

- `backend/alembic/versions/022_sync_state.py` — new table.
- `backend/app/models/email.py` — `SyncState` model.
- `backend/app/config.py` — `email_delete_sync` flag.
- `backend/app/services/email_provider.py` — `delta_folder_messages` on the ABC
  (no-op default) + `MSGraphProvider` (real impl).
- `backend/app/services/email_intake.py` — reconcile step + helper
  `reconcile_outlook_deletions(db, provider)`.
- `backend/tests/test_email_delete_sync.py` — new tests.
- `backend/tests/conftest.py` — extend `RecordingEmailProvider` with a
  programmable `delta_folder_messages`.

## Verification

- Unit tests (SQLite, no prod):
  - flag off → reconcile is a no-op.
  - first run (no stored deltaLink) → stores deltaLink, acts on nothing.
  - subsequent delta with an id matching an active thread → thread flips to
    deleted (deleteditems) / spam (junkemail) + ActivityLog written.
  - id with no local match → skipped, no error.
  - id matching an already-terminal thread → left unchanged.
  - deltaLink is persisted and re-read across runs.
- Manual smoke (flag ON, msgraph, against the mailbox, AFTER explicit prod
  migration approval): delete a known email in Outlook → within ~60s the app
  thread leaves the to-do (status deleted); junk a message → status spam.

## Out of scope

- Restores / un-delete (Outlook → app).
- Per-message (sub-thread) deletion granularity.
- IMAP delta (no-op).
- Any change to the existing app → Outlook delete/spam path.
