# First-Class Folders — Design Spec

**Date:** 2026-07-10
**Status:** Approved design (Approach A), validated with the client on the 2026-07-10 call.
**Branch (implementation):** `FEAT/first-class-folders` (off `development`)
**Tier:** 2 (Standard)

## Goal

Make saved folders first-class entities so the app's own folders and Jane's
Outlook folders become one system: import all Outlook folders once, support
subfolders, let any folder be a save/move target, delete folders in-app, and
sync folder state to Outlook — all without ever deleting a folder in Outlook.

## Background — the current model

Saved folders are **not** stored. `GET /api/v1/emails/saved/folders` derives them
from the distinct `saved_folder` text values on `email_threads` and
`email_messages` where `is_saved = true` (`emails.py:1424`). A folder "exists"
only while ≥1 saved item points at it; deleting one nulls that label
(`emails.py:1482`). Outlook folders are shown separately via a live read-through
(`OutlookFolderTree` → `GET /api/v1/mailbox/folders?custom=true`), can't be
deleted in-app, and can't be true app folders.

Consequences that block the client's asks:
- An **empty** folder can't exist → can't import Outlook folders that have no
  in-app saved items yet.
- No **hierarchy** → no subfolders.
- No **registry** → no per-folder metadata (origin, Outlook id).

## Approach (chosen: A — registry table, keep name labels)

Introduce a `saved_folders` registry table. Emails keep referencing a folder by
**name** (the existing `saved_folder` string), so every current code path —
save, move, filter, and the folder-sync-to-Outlook write path shipped this week
(`find_or_create_folder` at mailbox root) — keeps working unchanged. The table
adds existence-of-empty-folders, nesting, and origin metadata on top.

Rejected — B (full foreign-key model): emails reference `folder_id`. More
"correct" (allows same-named subfolders under different parents) but requires
migrating every `saved_folder` string to a row + FK and rewriting every
name-based call site (save/move/filter/sync). Large blast radius, high
regression risk, no client-visible benefit for v1. Not chosen.

## Data model

New table **`saved_folders`** (Alembic migration `021`):

| column | type | notes |
|---|---|---|
| `id` | UUID, PK | server default uuid |
| `name` | TEXT, NOT NULL | the label emails point at; unique **case-insensitively** (enforced in app logic + a unique index on `name`) |
| `parent_id` | UUID, NULL, FK → `saved_folders.id` | `ON DELETE CASCADE`; NULL = top level |
| `source` | TEXT, NOT NULL, default `'app'` | `'app'` \| `'outlook'` |
| `outlook_folder_id` | TEXT, NULL | Graph folder id captured at import (for future matching) |
| `created_at` | TIMESTAMPTZ, NOT NULL | server default now |

Migration also **backfills** the registry with the current distinct
`saved_folder` labels (from saved threads + messages) as `source='app'`,
top-level, so nothing regresses on first deploy.

Emails: **no change** to `email_threads.saved_folder` / `email_messages.saved_folder`.

## Backend

All endpoints under the existing `/api/v1/emails` router unless noted.

### List — `GET /saved/folders` (extended)
Return the registry as a flat list with `id`, `name`, `parent_id`, `source`, and
`count` (in-app saved threads + messages whose `saved_folder == name`). Include
the unfiled bucket (`name=None`) as today. Defensive union: if a saved item
references a name absent from the registry (legacy), surface it as a top-level
`source='app'` row so items are never hidden. Counts reflect **in-app saved
items**, not Outlook mailbox counts.

### Create — `POST /saved/folders`  `{ name, parent_id? }`
Insert a registry row (`source='app'`). 409 if `name` already exists
(case-insensitive). `parent_id` optional (subfolder). Used by "New folder" and
"New subfolder".

### Delete — `DELETE /saved/folders/{name}` (extended, existing route)
1. Resolve the folder + all descendants (recursive via `parent_id`).
2. Delete those registry rows (DB cascade handles children).
3. Null `saved_folder` on every saved thread/message whose label is in that set
   (items stay saved, drop to "No folder").
**In-app only — never calls Graph.** Hard invariant: folder deletion never
touches Outlook. Idempotent; 204 even if the folder never existed.

### Import from Outlook — `POST /saved/folders/import-from-outlook`
One-time (re-runnable) pull. Walk the custom Outlook folder tree recursively
(reuse `MSGraphProvider.list_mail_folders(parent_id)`, root + children, excluding
the built-in defaults already filtered by `custom` mode), depth-capped at 6 to
avoid pathological trees. For each folder, **upsert by case-insensitive name**:
insert if absent, else update `source='outlook'`, `outlook_folder_id`, and
`parent_id` (resolved from the parent Outlook folder's registry row). Idempotent
— a second run creates no duplicates. Returns `{ imported, updated, total }`.
No-op (returns zeros) when the provider isn't MSGraph.

### Sync to Outlook — `POST /saved/folders/sync-to-outlook`
Push app folders into Outlook: for each registry folder, call
`find_or_create_folder(name)` (the create-at-root path shipped this week).
Additive/create-only. **Never deletes.** Returns `{ created, existing, total }`.
No-op when the provider isn't MSGraph or `OUTLOOK_FOLDER_SYNC` semantics gate it
(reuse the existing flag guard pattern).

## Frontend

### Rail (Saved page)
Replace the split rail (app `FolderRailItem` list + live `OutlookFolderTree`)
with **one registry-driven tree**:
- Build the tree from `GET /saved/folders` using `parent_id`.
- Render with the compact rows + shared filter box already unified this week.
- Every folder row: hover **delete icon** → confirm dialog (per the delete-
  confirmation standard) → `DELETE /saved/folders/{name}` (in-app only).
- Every folder row: hover **"+" (new subfolder)** → create dialog pre-filled with
  that folder as `parent_id`.
- Top-level "New folder" gains an optional parent picker.
Outlook folders appear here **after** the one-time import (below). The live
read-through `OutlookFolderTree` component is retired.

### Save / Move dialog
The folder picker lists the full registry tree, **searchable** (there are
hundreds after import). Selecting any folder — app or imported-Outlook — files
by name; when `OUTLOOK_FOLDER_SYNC` is on, filing flows to the matching Outlook
folder via the existing folder-sync path.

### Settings → Folders section
Two buttons with result toasts:
- **Import from Outlook** → `import-from-outlook` (`n imported / n updated`).
- **Sync to Outlook** → `sync-to-outlook` (`n created`).
Copy makes clear neither ever deletes anything in Outlook.

## Error handling

- Graph failures in import/sync are surfaced as a toast (partial success
  reported); they never corrupt the registry (upserts are per-folder,
  best-effort, logged).
- Create conflict → 409 with a human message ("A folder named X already exists").
- Delete is idempotent and always 204.

## Testing (TDD)

- Migration: table created; backfill produces one registry row per existing
  distinct label.
- List: registry + counts; legacy label-only folder still surfaces; unfiled
  bucket intact.
- Create: inserts; case-insensitive 409; subfolder sets `parent_id`.
- Delete: removes folder + descendants, nulls labels on affected items, items
  stay saved; **asserts no Graph DELETE** (mirror existing folder-sync test).
- Import: recursive walk, upsert idempotency (2nd run = 0 imported), parent
  linkage, non-MSGraph no-op, **never DELETE/PATCH a folder**.
- Sync: create-only, idempotent, non-MSGraph no-op, **never DELETE**.

## Hard invariants

- **Never issue a Graph `DELETE` on a mail folder.** Test-asserted across delete,
  import, and sync.
- Folder deletion is **in-app only**.

## Out of scope (explicit)

- **Bidirectional EMAIL deletion sync** (Outlook ↔ app for messages) — a separate
  follow-up the client asked for on the 2026-07-10 call, to be built *after* this.
- **Same-named subfolders under different parents** — v1 treats folder names as
  app-wide unique (matches how the app already works).
- **Outlook mailbox item counts** — the rail shows in-app saved-item counts, not
  Outlook's folder totals.

## Assumptions

- The one-time import is user-triggered from Settings (not auto-run on load);
  after it runs, folders persist in the registry. Re-import updates in place.
- `MSGraphProvider.list_mail_folders` already excludes built-in defaults in
  `custom` mode and returns root + child levels; recursion composes those calls.
