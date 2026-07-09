# Signature closing split — design

**Iteration:** 2 of Jane's "Email Changes.pdf" feedback (item 7).
**Branch:** `FIX/signature-closing-split` (off `development`). Tier 2.
**Date:** 2026-07-09.

## Problem

Jane's feedback asks for the opposite split of what the app does today:

- **Today:** the AI is forbidden from writing any closing
  (`_CLOSING_RULE_NO_CLOSING`), and the closing lives *inside* the stored
  signature — Jane's personal signature (`users.signature`, seeded via
  migration 017 → migrated to her user row in 018) begins with
  `Thanks so much,\n\nJane`. The name/title/firm block follows.
- **Wanted:** the signature is a **name/title/firm block only**, and the AI
  generates a short, **editable** closing line in the draft **body**.

Because the closing already lives in the body (which is editable) and the
signature is appended at send, no new field or storage is required — the body
holds the closing.

## Ground truth (verified in code, 2026-07-09)

- `draft_generator.py` has **two** generation paths, each with its own
  no-closing rule:
  1. Reply generator — `_CLOSING_RULE_NO_CLOSING` (system prompt) plus a
     matching user-prompt reminder (~line 555).
  2. Compose / "New Email" — `_COMPOSE_SYSTEM_PROMPT` with an inline no-closing
     rule (lines 219–221).
- `signatures.py`:
  - `signature_for_sender()` — personal signature, else company block; `None`
    user (T1 auto-send) → company block.
  - `apply_signature()` — strips any trailing *known* signature block
    (the one being appended, the company block, or the preserved
    `legacy_draft_signature`) before appending, so bodies never double-sign.
    Exact-suffix match only.
- `company_signature` (system_settings) is already clean — firm block only,
  no closing, no personal name. Used for T1 auto-send + fallback.
- Jane's `users.signature` (prod) — the closing to remove is the leading
  `Thanks so much,\n\nJane\n\n`; everything from `Jane M. Schilmoeller, CPA`
  down is the block that stays.

## Decisions (locked with the user)

1. **Closing style — tone-appropriate, AI-chosen.** The prompt instructs the
   model to end with ONE brief closing line that fits the draft's tone
   (e.g. `Thanks so much,` for warm/professional, `Best regards,` for formal).
   No config table, no new storage. Staff edit it in the body if they want.
2. **Jane's live signature — stripped by a migration (`020`).** Idempotent,
   guarded, rewrites `users.signature` for `jane@schilcpa.com` to the
   name/title/firm block only. Reproducible on Coolify via its own
   `alembic upgrade`. Requires a prod DB write → explicit approval before
   running (same protocol as 019).
3. **Existing drafts — left as-is, no bulk regeneration.** Standing rule:
   don't auto-rerun regeneration on old drafts; also protects the daily token
   budget. Old drafts end on the last sentence with no closing — still valid;
   self-heal as the queue drains / on manual regenerate.

## Changes

### 1. Prompt flip — both generation paths (`app/services/draft_generator.py`)

- Replace `_CLOSING_RULE_NO_CLOSING` with `_CLOSING_RULE_WITH_CLOSING`:
  - End the reply with exactly **one** brief closing line appropriate to the
    draft's tone (e.g. `Thanks so much,`, `Best regards,`, `Warm regards,`).
  - Still do **NOT** write any name, title, company, or signature block — those
    are appended automatically at send. (This "no name/title" guard is what
    prevents a doubled name now that a closing is expected.)
- Update the user-prompt reminder (~line 555) to match.
- Update the compose path's inline rule (`_COMPOSE_SYSTEM_PROMPT`,
  lines 219–221) the same way, so replies and New-Email drafts behave
  identically.

### 2. Migration `020_strip_jane_signature_closing`

- Idempotent + guarded (mirrors 018's approach — bake the known prod value,
  no app-config import).
- `upgrade()`: `UPDATE users SET signature = <name/title/firm block>`
  `WHERE email = 'jane@schilcpa.com' AND signature = <exact old value with closing>`.
  Guarding on the exact old value means: if Jane has already edited her
  signature, the migration no-ops (won't clobber her change) — same spirit as
  017/018's `ON CONFLICT DO NOTHING` / `WHERE signature IS NULL` guards.
- `downgrade()`: restore the closing-prefixed form under the same guard.
- Does not touch `company_signature` or `legacy_draft_signature`.

### 3. Existing drafts

No code. `apply_signature`'s existing strip logic already prevents
double-signing for any legacy-baked draft; new closings in the body are plain
text it never treats as a signature (exact-suffix match on known blocks only).

## Tests

- **Prompt (both paths):** the system prompt now contains the closing
  instruction; the "no name/title/signature" guard text survives; the compose
  prompt matches.
- **`apply_signature` invariant (hard pin):** a body that now ends in a closing
  line (e.g. `…\n\nThanks so much,`) + a name/title/firm signature yields
  exactly ONE signature, the closing line is preserved in the body, and the
  name is not duplicated. Re-applying is idempotent.
- **Migration 020:** the repo has no alembic test-runner harness (017/018/019
  are untested), so 020 is verified two ways: (a) unit tests — the new value is
  exactly the old minus the closing prefix (drift guard), the guarded transform
  fires only on an exact-seed match, it is idempotent, and it leaves a
  customized signature untouched; (b) at apply time, an inspector / `SELECT`
  check against the target DB confirms the closing is gone and the
  name/title/firm block remains (same verify-don't-trust step used for 019).

## Not changing

- Send-time signature mechanism / resolution chain.
- `company_signature` (already clean).
- Read-only-signature-in-editor UX.
- T1 auto-send (AI closing + firm-only company block reads correctly).
- Greeting / sign-off brand-context rules.

## Risk

The model sometimes ignored the *old* "no closing" rule, so `apply_signature`
was the real guarantee against double-signing. This change makes closings
**expected**, so the test suite must pin the "exactly one signature, name not
duplicated" invariant hard — that's the load-bearing safety net, not the
prompt.
