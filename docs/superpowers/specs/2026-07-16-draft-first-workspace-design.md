# Draft-first workspace + full-page compose

**Date:** 2026-07-16
**Branch:** `FEAT/draft-first-workspace`
**Source:** Client call 2026-07-10 (Jane + Sara)

## Context

Two related asks from the 2026-07-10 client call, both about giving Jane more
room to write:

1. **Swap the reply panes.** Today the received email is the big pane and the
   draft is the small one. Jane drafts substantial emails and wants the *draft*
   to be the large workspace, with the received email as a smaller reference.
2. **New-email compose should use the same big workspace as replying** — not the
   small Gmail-style floating dock. Composing should feel like "the same place
   on the screen" as replying.

Neither is part of the folder spec; this is its own iteration, sequenced after
the first-class-folders merge.

## Part 1 — Reply layout swap

File: `frontend/src/app/(dashboard)/emails/[threadId]/page.tsx`

- The `lg+` grid template changes from `1fr auto var(--draft-w)` to
  `1fr auto var(--conv-w)`, and the two panels reorder so the **draft renders in
  the left `1fr` (big) column** and the **received-email/conversation panel is
  the narrow, resizable right column**.
- The resizable pane is now the conversation, so the persisted width represents
  the conversation:
  - localStorage key renamed `jane_thread_draft_width` → `jane_thread_conv_width`
    (renaming avoids a stale draft-width value fighting the new layout on first
    load).
  - Defaults: `420` (default) / `320` (min) / `560` (max).
- Kept unchanged: the drag divider, arrow-key nudge, the mobile
  Conversation/Draft segmented control, and `data-print-region` on the
  received-email panel (Jane prints the email, not the editor).
- Divider math: the conversation stays the right column, so width =
  `grid.right − pointer.x` still computes the conversation width. Arrow keys:
  Left grows the draft (shrinks conversation), Right grows the conversation.

## Part 2 — Full-page compose

New route: `frontend/src/app/(dashboard)/emails/new/page.tsx`

- A dedicated full-width compose page: To / Cc / Subject, a large body editor
  that fills the content area, the existing Write-myself / Draft-with-AI mode
  toggle, attachments, signature preview, and Send + Cancel (→ `/emails`).
- The dock's form logic is extracted into a reusable `ComposeWorkspace`
  component (`frontend/src/components/emails/compose-workspace.tsx`) reusing the
  existing `composeEmail`, `composeDraft`, `useAttachments`, and
  `SignaturePreview` — no send/AI/attachment logic is rewritten.
- On send: success toast, revalidate `/api/v1/emails*` + `/api/v1/dashboard*`
  SWR caches (same as the dock does today), then `router.push("/emails")`.

### Retire the floating dock

- Delete `compose-dock.tsx` and `compose-context.tsx`; remove `ComposeProvider`
  from `app/(dashboard)/layout.tsx`.
- Rewire the two callers to navigate to `/emails/new` instead of
  `openCompose()`:
  - `components/layout/sidebar.tsx` (the New Email button)
  - `app/(dashboard)/emails/page.tsx` (the New Email button)
- Neither caller prefills any fields today, so no query-param prefill plumbing is
  added (YAGNI). If a future "email this client" flow needs prefill, add it via
  query params at that time.

## Verification

- `tsc --noEmit` and `next build` green.
- Browser smoke:
  - Reply page: draft is the big left pane, received email the narrow right
    pane; drag + arrow-key resize works; mobile tabs still switch panels.
  - New Email from the sidebar AND from the emails page both open the full-page
    compose.
  - Compose: manual write, Draft-with-AI, add/remove attachments, signature
    preview, and Send all work; sending returns to `/emails` and the list
    updates.
  - No dead "New Email" button and no leftover floating dock anywhere.

## Out of scope

- Reply-side compose behavior (unchanged — this only swaps pane sizes).
- Prefilled compose / "email this client" (no caller needs it yet).
- Any backend change (frontend-only iteration).
