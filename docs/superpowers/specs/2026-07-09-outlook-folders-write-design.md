# Folder routing Iteration B — reflect filing into Outlook (write)

**Iteration:** B of folder routing (Jane's "Email Changes.pdf" #6/#9, write half).
**Branch:** `FEAT/outlook-folders-write` (off `development`). Tier 2.
**Date:** 2026-07-09.

## Problem

Iteration A surfaced Jane's real Outlook folders in the app (read-only). Today,
filing a thread in the app only sets a DB label (`thread.saved_folder`, via
`auto_folder.py` after a successful send, and via the manual Save/Move dialogs).
Iteration B makes that filing **reflect into the real mailbox**: create a real
Outlook folder named for the client (under Inbox) if needed, and move the
thread's inbound messages into it — so the app's organization matches what Jane
sees in Outlook.

This is the **first feature that writes to the client's live mailbox** (creates
folders, moves messages), so it ships behind a flag and is designed to fail
safe.

## Decisions (locked with the user)

1. **Rollout: feature flag `OUTLOOK_FOLDER_SYNC`, default `false`.** Code ships
   dark; enabled deliberately after a supervised live test. Flag off = today's
   behavior exactly (DB label only, zero mailbox writes).
2. **What moves: inbound (client) messages only.** Sent replies stay in Outlook
   Sent Items (where Exchange already files them).
3. **Where: client folders live UNDER INBOX** (matches Jane's existing 427
   Inbox subfolders).
4. **Forward-only:** no backfill of existing in-app labels or historical mail;
   only new filing actions sync.
5. **HARD INVARIANT — never delete an Outlook folder.** No delete-folder method
   exists; a test asserts no `DELETE .../mailFolders` is ever issued. Removing an
   in-app folder label does NOT delete the Outlook folder.

## Architecture

### Provider write methods (`services/email_provider.py`)

Base `EmailProvider` gets no-op defaults so non-Graph providers degrade cleanly
(the feature is inert on IMAP):

- `find_or_create_folder(self, name: str) -> str | None` — returns the Graph
  folder id for a child of Inbox with `displayName == name` (case-insensitive
  match against the Inbox children from `list_mail_folders("inbox")`, reusing
  Iteration A's read + cache); creates it via
  `POST /mailFolders/inbox/childFolders {"displayName": name}` if absent.
  Base returns `None`.
- `move_message_to_folder(self, internet_message_id: str, folder_id: str) -> None`
  — resolves the stored internetMessageId to the Graph id (existing
  `_resolve_graph_message_id`), then `POST /messages/{graph_id}/move`
  `{"destinationId": folder_id}`. No-op if the message can't be resolved
  (already moved/deleted). Base is a no-op.

Only create + move are ever issued. **No delete.**

Note: `"inbox"` is a Graph well-known folder id (same alias family already used
for `deleteditems`/`junkemail`), so no Inbox-id lookup is needed.

### Sync service (`services/folder_sync.py`)

`sync_thread_to_outlook_folder(db, *, thread, folder_name, request_ip=None,
actor_id=None) -> None`:

1. Return immediately if `settings.outlook_folder_sync` is false, or the
   provider is not MSGraph, or `folder_name` is empty.
2. `folder_id = provider.find_or_create_folder(folder_name)`; return if `None`.
3. For each **inbound** message on the thread with a stored
   `message_id_header`, call `provider.move_message_to_folder(...)`.
4. Optionally write an audit row (`thread.outlook_folder_synced`) with the
   folder name + moved count.
5. **Never raises.** All Graph failures are logged and swallowed — a filing
   sync must never break the send or the save that triggered it (same contract
   as today's `auto_folder`).

### Wiring (existing filing triggers — no new user gestures)

- **`auto_folder.auto_save_to_client_folder`** (fires after a successful manual
  send AND T1 auto-send): after it sets the label, call
  `sync_thread_to_outlook_folder(db, thread=thread, folder_name=folder_name, ...)`.
- **Manual Save/Move** (the emails API endpoint that sets `saved_folder` on a
  thread): after the label is set, call the sync with the chosen folder. Moving
  to "No folder" / unfiling does NOT move anything in Outlook (we never move
  mail out or delete folders — forward-only, never-delete).

### Config

- `Settings.outlook_folder_sync: bool = False` (env `OUTLOOK_FOLDER_SYNC`).
- Document it in `.env.example` with the default-off + enable-after-test note.

## Data flow

`send / auto-send / manual save → sets thread.saved_folder (label) → folder_sync
→ (flag on + Graph) find_or_create_folder(name) → move each inbound message`.
Cached Inbox-children read keeps repeated syncs cheap.

## Poller interaction

The poller reads `mailFolders/Inbox/messages?isRead eq false`. Moved inbound
messages leave Inbox root, but they were already ingested + marked read, so the
poller never needed them again. New client mail still lands in Inbox root and
ingests normally. No change to the poller.

## Edge cases & error handling

- **Folder name collision** (two Inbox children with the same displayName): use
  the first match; log if ambiguous. Never create a duplicate when one exists.
- **Message already in the target folder / hard-deleted:** move resolves by
  internetMessageId; if unresolvable, the move is a logged no-op.
- **Flag off:** the service returns before any provider call — fully inert.
- **Graph/permission failure:** logged + swallowed; the triggering send/save
  still succeeds and the in-app label is still set.

## Testing

- **Provider:** `find_or_create_folder` — existing folder → no POST (returns
  matched id); missing → POST create; case-insensitive match. `move_message_to_folder`
  — resolves id + POSTs `/move` with `destinationId`; unresolvable id → no move.
  **Never DELETE** — assert no delete call across both.
- **Service:** flag off → zero provider calls; flag on + Graph → create + move
  inbound only (not outbound); non-Graph provider → no-op; a provider exception
  is swallowed (the function returns normally, caller unaffected).
- **Wiring:** `auto_folder` and the manual-save path invoke the sync with the
  right folder name when the flag is on, and not when off.
- **Live smoke (gated, user-driven):** with the flag ON in a controlled test,
  file a thread → confirm a folder appears under Inbox and the inbound message
  moved. On Jane's real mailbox this needs the user's explicit go; prefer a
  disposable test folder/thread first.

## Not changing

- The DB `saved_folder` label model, the Saved page, Iteration A's read
  endpoint/tree, the poller, send/attachment paths.
- No folder deletion — never implemented.

## Risk

Writes to the live mailbox — mitigated by: default-off flag (ships dark),
inbound-only moves, forward-only (no mass operation), swallow-and-log failures
(never breaks a send), and the never-delete invariant. Enable only after a
supervised live test.
