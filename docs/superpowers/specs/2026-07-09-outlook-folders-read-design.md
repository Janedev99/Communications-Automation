# Outlook folders → in-app (read-only) — design

**Iteration:** A of folder routing (Jane's "Email Changes.pdf" #6/#9, read half).
**Branch:** `FEAT/outlook-folders-read` (off `development`). Tier 2.
**Date:** 2026-07-09.

## Problem

Today the app's "folders" are DB-only labels (`thread.saved_folder`, set by
`auto_folder.py`). Jane organizes primarily in Outlook, where she already has
427 client subfolders under Inbox. Her feedback asks for real Outlook-folder
integration. This iteration delivers the **read half**: reflect Jane's actual
Outlook folder structure inside the portal. The **write half** (auto-create a
folder in Outlook on send + move the message there) is a separate later
iteration (B).

## Feasibility (verified live, 2026-07-09)

A read-only Graph probe confirmed the app registration is granted
**`Mail.ReadWrite` + `Mail.Send`** (token `roles` claim), and
`GET /users/{mailbox}/mailFolders` returns 200. So listing (and later
creating/moving) folders needs **no new Azure consent**. The mailbox has 11
top-level folders; **Inbox has 427 child folders**.

## Decisions (locked with the user)

1. **Build order:** READ path first (this spec), WRITE path second. Read ships
   safely with zero mailbox mutation.
2. **(Applies to B)** auto-created client folders will live **under Inbox**,
   matching Jane's existing structure.
3. **(Applies to B)** **forward-only** — no retroactive backfill/mass-move of
   existing in-app labels.
4. **HARD INVARIANT (both iterations): the feature NEVER deletes an Outlook
   folder.** No code path issues `DELETE /mailFolders/{id}`. Existing folders
   are only ever read (A) and, later, added to via find-or-create + message
   move (B). (The unrelated "Delete email" feature moves *messages* to Deleted
   Items — unchanged.)

## Scope of Iteration A (read-only)

**In:** list Jane's Outlook folder tree via Graph and surface it in the portal
(Saved page) so she can see her real structure reflected, with counts.

**Out (later / not this iteration):** creating folders, moving messages,
changing how filing/auto-folder works, viewing the messages inside a folder,
and any folder deletion (never).

## Architecture

### Backend

- **`MSGraphProvider.list_mail_folders(parent_id: str | None = None)`**
  (`services/email_provider.py`). `parent_id=None` → `GET /mailFolders`
  (top level); otherwise → `GET /mailFolders/{parent_id}/childFolders`.
  Follows `@odata.nextLink` pagination. `$select=id,displayName,`
  `childFolderCount,totalItemCount,unreadItemCount`. Returns a list of plain
  dicts/dataclasses:
  `{id, display_name, child_folder_count, total_item_count, unread_item_count}`.
  **Read-only** — issues only GET. The base `EmailProvider.list_mail_folders`
  returns `[]` (IMAP and any non-Graph provider degrade cleanly).

- **Endpoint `GET /api/v1/mailbox/folders?parent=<id>`** (new
  `api/mailbox.py`, or folded into an existing emails/folders router —
  implementer picks the closest existing pattern). Auth required (same
  dependency as other v1 routes). `parent` omitted → top level. Returns
  `{folders: [...]}` in the provider's shape. **Lazy**: the client requests one
  level at a time, so the 427 Inbox children are only fetched when Inbox is
  expanded — never all at once.

- **Cache:** a small in-process TTL cache keyed by `parent` (~120s) so repeated
  expands/opens don't re-hit Graph. Cache is best-effort; a miss just calls
  Graph. (No new table — read-through cache only.)

- **Errors:** Graph failure → 502 with a clear message; the frontend shows an
  inline error in the folders panel without breaking the rest of the page.
  Provider not Graph → 200 with `{folders: []}`.

### Frontend

- **Saved page** gains an **"Outlook folders"** section: a lazy-expanding
  **tree** (`components/emails/outlook-folder-tree.tsx` or similar). Each node
  shows `displayName` + item/unread counts; a node with `childFolderCount > 0`
  is expandable and fetches its children on first expand
  (`GET /api/v1/mailbox/folders?parent=<id>`).
- A **search/filter** box above the tree (essential at 400+ folders) filters
  the currently-loaded nodes by name. Server-side search across *all* folders is
  **out of scope** for V1 — the filter matches already-loaded nodes only, with a
  hint to expand for more.
- **States:** skeleton while a level loads; empty ("No subfolders"); inline
  error with retry; the read-only tree never mutates anything.
- Clicking a folder does **not** open its messages (out of scope).

### Data flow

`Saved page → GET /api/v1/mailbox/folders[?parent] → MSGraphProvider.list_mail_folders → Graph`
(cached per level). One level per request; expand fetches the next level.

## Testing

- **Provider (`list_mail_folders`):** mocked Graph — top-level vs child fetch,
  `@odata.nextLink` pagination across ≥2 pages, empty result, non-Graph
  provider returns `[]`, and **only GET is issued** (assert no POST/DELETE).
- **Endpoint:** auth required (401/403 unauth); shape `{folders: [...]}`;
  `parent` passthrough; provider-not-graph → `{folders: []}`; Graph error → 502.
- **No-delete invariant:** a test asserting the folders code never calls a
  `DELETE .../mailFolders` URL (guards the hard invariant for A and as a
  standing guard when B lands).
- **Frontend:** not unit-tested (no FE test suite); verified via tsc/lint/build
  + a browser read smoke against the real mailbox.

## Not changing

- `auto_folder.py` and the DB `saved_folder` label mechanism (untouched in A;
  revisited in B).
- The poller, send paths, delete/spam message moves.
- Any folder deletion — never implemented.

## Risk

Read-only → no mailbox mutation risk. Only cost is Graph read latency at 400+
folders, mitigated by lazy per-level loading + a short server-side cache.
