# Signature Closing Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI write a short, tone-appropriate, editable closing line at the end of the draft body, and reduce the stored signature to a name/title/firm block only — so a sent email reads `…last sentence.` → `Thanks so much,` (AI, editable in body) → `Jane M. Schilmoeller, CPA / …firm` (signature, appended at send).

**Architecture:** Two coordinated changes in the backend only. (1) In `app/services/draft_generator.py`, flip both AI generation paths (reply generator + compose) from "write no closing" to "write one tone-appropriate closing line, but still no name/title/signature". (2) Add idempotent, guarded migration `020` that strips the `Thanks so much, / Jane` closing from Jane's `users.signature`. The send-time `apply_signature()` mechanism is unchanged — it already treats a body-level closing as plain text (exact-suffix match on *known* signature blocks only), so it keeps guaranteeing exactly one signature.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Alembic, pytest with a mocked Anthropic client (`mock_anthropic` fixture; test env pins `LLM_PROVIDER=anthropic`). Run backend tests from `backend/` with `.\venv\Scripts\python.exe -m pytest`.

## Global Constraints

- Branch `FIX/signature-closing-split` (already created off `development`); spec committed at `099053b`.
- Backend-only iteration — no frontend files change.
- The AI closing must NOT include a name, title, company, or signature block — those are appended at send. This "no name/title" guard is load-bearing (prevents a doubled name).
- Preserve the exact substring `The sender's signature is appended` in the user-prompt reminder — an existing test asserts it.
- Keep the `{closing_rule}` and `{signoff_instruction}` format placeholders in the prompt templates — persona/greeting/signature-setting tests assert those placeholders exist.
- Migration `020` must be idempotent and guarded so it no-ops if Jane has already customized her signature (mirrors 017/018 guard style). It requires a prod DB write → **explicit user approval before running** (protocol from migration 019). Applying to prod is an execution/deploy step, not a code task.
- Do NOT bulk-regenerate existing drafts (token budget + standing rule).
- `LEGACY_DRAFT_SIGNATURE` and `company_signature` are untouched.

---

## File Structure

- **Modify** `backend/app/services/draft_generator.py`
  - Replace `_CLOSING_RULE_NO_CLOSING` (the constant, ~L155-160) with `_CLOSING_RULE_WITH_CLOSING`.
  - Update the `closing_rule = ...` assignment in `generate()` (~L525).
  - Update the `signoff_instruction` value built in `generate()` (~L555-559).
  - Update the compose closing rule inside `_COMPOSE_SYSTEM_PROMPT` (~L219-221).
- **Modify** `backend/tests/test_draft_signature_append.py`
  - Rewrite `test_system_prompt_always_forbids_model_closings` → `test_system_prompt_instructs_a_tone_appropriate_closing`.
  - Update the module docstring to describe the new contract.
  - `test_generation_never_appends_a_signature` and `test_user_prompt_signoff_instruction_is_sender_neutral` remain valid (verify no change needed).
- **Modify** `backend/tests/test_compose_draft.py`
  - Add `test_compose_prompt_instructs_a_closing`.
- **Modify** `backend/tests/test_per_user_signatures.py`
  - Add `test_apply_keeps_body_closing_and_single_signature` (pins the load-bearing invariant).
- **Create** `backend/alembic/versions/020_strip_jane_signature_closing.py`
- **Create** `backend/tests/test_migration_020_signature.py`

---

## Task 1: Flip the reply-generator closing rule + user-prompt reminder

**Files:**
- Modify: `backend/app/services/draft_generator.py` (`_CLOSING_RULE_NO_CLOSING` ~L155-160; `closing_rule` assignment ~L525; `signoff_instruction` ~L555-559)
- Test: `backend/tests/test_draft_signature_append.py`

**Interfaces:**
- Consumes: `get_draft_generator().generate(db, thread)` returns a draft whose `body_text` is exactly the model output; the system prompt is captured via `mock_anthropic.messages.create.call_args.kwargs["system"]`.
- Produces: a new module constant `_CLOSING_RULE_WITH_CLOSING: str`. The `_CLOSING_RULE_NO_CLOSING` name is removed.

- [ ] **Step 1: Rewrite the failing test**

In `backend/tests/test_draft_signature_append.py`, replace `test_system_prompt_always_forbids_model_closings` (L87-98) with:

```python
def test_system_prompt_instructs_a_tone_appropriate_closing(db_session, mock_anthropic):
    """The model is now told to write ONE brief tone-appropriate closing line,
    while still writing no name/title/signature of its own (that is appended
    at send)."""
    _, system_prompt = _run_generate(
        db_session,
        mock_anthropic,
        "Dear Tony, thanks for reaching out — we'll follow up shortly.",
    )

    # New contract: a closing line IS expected...
    assert "closing line" in system_prompt
    # ...but never a name/title/signature block.
    assert "Do NOT write any name, title" in system_prompt
    assert "appended automatically when the email is sent" in system_prompt
    # The retired no-closing rule must be gone.
    assert "Do NOT write any closing" not in system_prompt
```

Also update the module docstring (L1-13) — replace the sentence "so generation must produce a signature-LESS body and the system prompt must always tell the model to write no closing of its own" with: "so generation produces a body that carries only an editable closing line (no name/title); the name/title/firm signature is appended at send."

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_draft_signature_append.py::test_system_prompt_instructs_a_tone_appropriate_closing -v`
Expected: FAIL — old code still emits "Do NOT write any closing"; `"closing line"` / `"Do NOT write any name, title"` absent.

- [ ] **Step 3: Replace the closing-rule constant**

In `backend/app/services/draft_generator.py`, replace the constant (currently L155-160):

```python
_CLOSING_RULE_WITH_CLOSING = """\
CLOSING:
- End your reply with ONE brief closing line that fits the tone of the message \
(for example "Thanks so much," for a warm or professional reply, or "Best regards," \
for a more formal one). Put it on its own line after your final substantive sentence.
- Do NOT write any name, title, company, or signature block of your own. Write only \
the closing line itself — the sender's signature (name, title, firm) is appended \
automatically when the email is sent."""
```

Update the comment block just above it (currently L150-154) to read:

```python
# (migration 018), a signature is ALWAYS appended at send time — the sender's
# personal block, or the company block as fallback / for T1 auto-send (see
# services/signatures.py). The sender is unknown at generation time, so the
# model writes the CLOSING LINE only (editable, in the body); the name/title/
# firm block is owned by code and appended at send.
```

- [ ] **Step 4: Point the assignment at the new constant**

In `generate()` (~L523-525), replace:

```python
        # Signatures are a SEND-time concern since 018 (the sender is unknown
        # while the poller generates) — the model always writes no closing.
        closing_rule = _CLOSING_RULE_NO_CLOSING
```

with:

```python
        # Signatures are a SEND-time concern since 018 (the sender is unknown
        # while the poller generates) — the model writes only an editable
        # closing line; the name/title/firm block is appended at send.
        closing_rule = _CLOSING_RULE_WITH_CLOSING
```

- [ ] **Step 5: Update the user-prompt reminder**

In `generate()` (~L553-559), replace the `signoff_instruction` assignment:

```python
        # User-prompt closing reminder, consistent with the system-prompt
        # closing_rule above — one editable closing line, no name/signature.
        signoff_instruction = (
            "End with one brief closing line that fits the tone (for example "
            '"Thanks so much," or "Best regards,"). Do not add a name, title, or '
            "signature of your own. The sender's signature is appended "
            "automatically when the email is sent."
        )
```

(The substring `The sender's signature is appended` is preserved for the sender-neutral test.)

- [ ] **Step 6: Run the updated + neighboring tests**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_draft_signature_append.py -v`
Expected: PASS — all four tests green (`test_generation_never_appends_a_signature`, `test_system_prompt_instructs_a_tone_appropriate_closing`, `test_user_prompt_signoff_instruction_is_sender_neutral`, and any others in the file).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/draft_generator.py backend/tests/test_draft_signature_append.py
git commit -m "feat(backend): reply generator writes an editable tone-appropriate closing"
```

---

## Task 2: Flip the compose ("New Email") closing rule

**Files:**
- Modify: `backend/app/services/draft_generator.py` (`_COMPOSE_SYSTEM_PROMPT` ~L219-221)
- Test: `backend/tests/test_compose_draft.py`

**Interfaces:**
- Consumes: the existing compose test drives `POST /api/v1/emails/compose-draft` (see `test_compose_draft.py`) with a mocked Anthropic client and asserts on the returned JSON. The compose system prompt is captured via `mock_anthropic.messages.create.call_args.kwargs["system"]`.
- Produces: no new symbols — edits the `_COMPOSE_SYSTEM_PROMPT` string literal only.

- [ ] **Step 1: Add the failing test**

In `backend/tests/test_compose_draft.py`, add this test. It reuses the module's existing `_arm_llm` helper and `DRAFT_URL` constant, and captures the compose system prompt from the mocked Anthropic call (the same `.call_args.kwargs["system"]` pattern used elsewhere):

```python
def test_compose_prompt_instructs_a_closing(logged_in_admin, mock_anthropic):
    """Compose drafts now end with an editable tone-appropriate closing line,
    still without a name/title/signature (appended at send)."""
    _arm_llm(mock_anthropic, '{"subject": "Hi", "body": "Hi Sam, quick note."}')
    resp = logged_in_admin.post(
        DRAFT_URL,
        json={"instruction": "Send Sam a quick note.", "recipient": "sam@example.com"},
    )
    assert resp.status_code == 200, resp.text

    system_prompt = mock_anthropic.messages.create.call_args.kwargs["system"]
    assert "closing line" in system_prompt
    assert "Do NOT write a name, title, or signature" in system_prompt
    assert "Do NOT write any closing" not in system_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_compose_draft.py::test_compose_prompt_instructs_a_closing -v`
Expected: FAIL — the compose prompt still says "Do NOT write any closing".

- [ ] **Step 3: Edit the compose closing rule**

In `backend/app/services/draft_generator.py`, replace lines L219-221 inside `_COMPOSE_SYSTEM_PROMPT`:

```python
- End with ONE brief closing line appropriate to the tone (for example \
"Thanks so much," or "Best regards,"), on its own line after your final \
substantive sentence.
- Do NOT write a name, title, or signature block of your own — the sender's \
signature is appended automatically when the email is sent.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_compose_draft.py -v`
Expected: PASS — new test green, existing compose test (`"Schilmoeller" not in data["body"]`) still green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/draft_generator.py backend/tests/test_compose_draft.py
git commit -m "feat(backend): compose drafts write an editable tone-appropriate closing"
```

---

## Task 3: Pin the apply_signature invariant (body closing + one signature)

**Files:**
- Test: `backend/tests/test_per_user_signatures.py`

**Interfaces:**
- Consumes: `apply_signature(db, body, signature) -> str` from `app.services.signatures`; module fixture `_isolate_signature_settings` pins `COMPANY_SIG`/`LEGACY_SIG`; constant `PERSONAL_SIG = "Thanks,\n\nGus\nSchilmoeller & Schoenfield, PC"`.
- Produces: no code — a characterization test that guards the load-bearing invariant now that closings are expected in the body.

- [ ] **Step 1: Add the test**

In `backend/tests/test_per_user_signatures.py`, add after `test_apply_never_touches_staff_typed_closings` (L112):

```python
def test_apply_keeps_body_closing_and_single_signature(db_session):
    """New contract: the AI writes an editable closing line in the body. It is
    plain text (not a known signature block), so apply_signature keeps it and
    still appends exactly ONE signature — the name is not duplicated."""
    body = "Here is your answer.\n\nThanks so much,"
    out = apply_signature(db_session, body, PERSONAL_SIG)

    # Closing line survives verbatim in the body.
    assert "Here is your answer.\n\nThanks so much," in out
    # Exactly one signature appended; the signer's name appears once.
    assert out.endswith(PERSONAL_SIG)
    assert out.count("Gus") == 1
    # Re-applying is idempotent (no second signature).
    assert apply_signature(db_session, out, PERSONAL_SIG) == out
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_per_user_signatures.py::test_apply_keeps_body_closing_and_single_signature -v`
Expected: PASS immediately — this pins existing behavior (`apply_signature` matches only known blocks by exact suffix; a body closing is untouched). If it FAILS, stop: the send path would double- or mis-sign and the design assumption is wrong.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_per_user_signatures.py
git commit -m "test(backend): pin apply_signature keeps body closing + single signature"
```

---

## Task 4: Migration 020 — strip the closing from Jane's stored signature

**Files:**
- Create: `backend/alembic/versions/020_strip_jane_signature_closing.py`
- Create: `backend/tests/test_migration_020_signature.py`

**Interfaces:**
- Consumes: alembic `op.get_bind()`; `users` table with columns `email`, `signature`.
- Produces: module-level constants `_JANE_EMAIL: str`, `_CLOSING_PREFIX: str`, `_OLD_SIGNATURE: str`, `_NEW_SIGNATURE: str` (= `_OLD_SIGNATURE.removeprefix(_CLOSING_PREFIX)`), and a pure function `strip_jane_closing(bind) -> None` that both `upgrade()` and the test call. `revision = "020"`, `down_revision = "019"`.

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/020_strip_jane_signature_closing.py`:

```python
"""strip the closing lines from Jane's personal signature

Revision ID: 020
Revises: 019
Create Date: 2026-07-09

Iteration 2 (signature closing split): the AI now writes an editable closing
line in the draft body, so the stored signature must be the name/title/firm
block ONLY — otherwise a sent email double-closes (AI closing + signature
closing). Jane's `users.signature` (seeded in 017, migrated into her row in
018) still begins with "Thanks so much,\\n\\nJane\\n\\n"; this removes exactly
that prefix.

Guarded + idempotent: the UPDATE only fires when the stored value still equals
the exact seeded text, so if Jane has already customized her signature the
migration no-ops and never clobbers her change (same spirit as 017/018 guards).
`_NEW_SIGNATURE` is derived from `_OLD_SIGNATURE` by removing `_CLOSING_PREFIX`,
so the two can never drift apart.
"""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

_JANE_EMAIL = "jane@schilcpa.com"

_CLOSING_PREFIX = "Thanks so much,\n\nJane\n\n"

# The exact value seeded in 017 and migrated into Jane's row in 018.
_OLD_SIGNATURE = """Thanks so much,

Jane

Jane M. Schilmoeller, CPA
Business Growth and Profitability Advisor

Schilmoeller & Schoenfield, PC
3131 Eastside Street, Suite 430
Houston, Texas  77098

Office:  (713) 527-9281 Ext 1
Direct Line:  (346) 415-6330
Fax: (346) 415-6337"""

# Name/title/firm block only — old value minus the leading closing.
_NEW_SIGNATURE = _OLD_SIGNATURE[len(_CLOSING_PREFIX):]


def _set_signature(bind, *, where_value: str, new_value: str) -> None:
    bind.execute(
        sa.text(
            "UPDATE users SET signature = :new "
            "WHERE email = :email AND signature = :old"
        ),
        {"new": new_value, "old": where_value, "email": _JANE_EMAIL},
    )


def strip_jane_closing(bind) -> None:
    """Rewrite Jane's signature old→new, only if it still equals the seed."""
    _set_signature(bind, where_value=_OLD_SIGNATURE, new_value=_NEW_SIGNATURE)


def upgrade() -> None:
    strip_jane_closing(op.get_bind())


def downgrade() -> None:
    _set_signature(op.get_bind(), where_value=_NEW_SIGNATURE, new_value=_OLD_SIGNATURE)
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_migration_020_signature.py`:

```python
"""Migration 020 — strip Jane's signature closing.

The repo has no alembic test-runner harness (017/018/019 are untested), so we
verify the two things that actually matter: (1) the new value is exactly the
old value minus the closing prefix (drift guard), and (2) the guarded UPDATE
transforms only an exact-seed match and no-ops otherwise.

The migration module name starts with a digit and `alembic/versions` is not an
importable package, so we load it by file path via importlib. `strip_jane_closing`
takes any object with `.execute(text, params)` — a Connection in the migration,
the test Session here (a bare Engine has no `.execute()` in SQLAlchemy 2.0, so we
pass `db_session`, never `db_session.get_bind()`).
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa

from app.models.user import User, UserRole

_MIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "020_strip_jane_signature_closing.py"
)
_spec = importlib.util.spec_from_file_location("migration_020", _MIG_PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_new_signature_is_old_minus_closing_prefix():
    assert mig._OLD_SIGNATURE.startswith(mig._CLOSING_PREFIX)
    assert mig._NEW_SIGNATURE == mig._OLD_SIGNATURE[len(mig._CLOSING_PREFIX):]
    # Sanity: the name/title block survives, the closing is gone.
    assert mig._NEW_SIGNATURE.startswith("Jane M. Schilmoeller, CPA")
    assert "Thanks so much," not in mig._NEW_SIGNATURE
    assert mig._NEW_SIGNATURE.endswith("Fax: (346) 415-6337")


def _make_user(db, email, signature):
    u = User(
        id=uuid.uuid4(),
        email=email,
        name="Test",
        hashed_password="x",
        role=UserRole.staff,
        signature=signature,
    )
    db.add(u)
    db.commit()
    return u


def test_strip_transforms_exact_seed_and_is_idempotent(db_session):
    email = f"jane+{uuid.uuid4().hex}@schilcpa.com"
    # Point the migration at this throwaway address for the test.
    orig_email = mig._JANE_EMAIL
    mig._JANE_EMAIL = email
    try:
        _make_user(db_session, email, mig._OLD_SIGNATURE)

        mig.strip_jane_closing(db_session)
        db_session.commit()
        row = db_session.execute(
            sa.select(User).where(User.email == email)
        ).scalar_one()
        db_session.refresh(row)
        assert row.signature == mig._NEW_SIGNATURE

        # Idempotent: running again does nothing (no exact-seed match now).
        mig.strip_jane_closing(db_session)
        db_session.commit()
        db_session.refresh(row)
        assert row.signature == mig._NEW_SIGNATURE
    finally:
        mig._JANE_EMAIL = orig_email


def test_strip_leaves_a_customized_signature_untouched(db_session):
    email = f"jane+{uuid.uuid4().hex}@schilcpa.com"
    custom = "Cheers,\n\nJane\n\nJane M. Schilmoeller, CPA"
    orig_email = mig._JANE_EMAIL
    mig._JANE_EMAIL = email
    try:
        _make_user(db_session, email, custom)
        mig.strip_jane_closing(db_session)
        db_session.commit()
        row = db_session.execute(
            sa.select(User).where(User.email == email)
        ).scalar_one()
        db_session.refresh(row)
        assert row.signature == custom  # not the seed → untouched
    finally:
        mig._JANE_EMAIL = orig_email
```

> Implementer note: `strip_jane_closing` reads `mig._JANE_EMAIL` at call time (the tests monkeypatch it to a throwaway address), so the migration's `_set_signature` must reference the module global `_JANE_EMAIL` — not capture it as a default argument.

- [ ] **Step 3: Run tests to verify they fail (then pass)**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_migration_020_signature.py -v`
Expected: the value-relationship test passes once the migration file exists; the DB tests pass once the model fields are correct. If `import` of the digit-prefixed module fails, apply the `importlib.util.spec_from_file_location` fallback from the notes.

- [ ] **Step 4: Confirm the migration is the single head**

Run: `.\venv\Scripts\python.exe -m alembic heads`
Expected: `020 (head)` only (no branching). Do NOT run `alembic upgrade` here — applying to the prod DB is a gated deploy step (see Final Verification).

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/020_strip_jane_signature_closing.py backend/tests/test_migration_020_signature.py
git commit -m "feat(backend): migration 020 strips the closing from Jane's signature"
```

---

## Final Verification (merge gate — run after all tasks)

- [ ] **Full backend suite green:**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all pass (no new failures vs the 443 baseline; +new tests). Investigate any failure before proceeding.

- [ ] **Update the spec's test note (honesty):** in `docs/superpowers/specs/2026-07-09-signature-closing-split-design.md`, adjust the "Migration 020" test bullet to reflect that the repo has no alembic runner harness — 020 is verified by (a) the value-relationship + guard tests above and (b) an inspector/`SELECT` check at apply time (as done for 019). Commit the doc tweak.

- [ ] **Hand back for user browser smoke** (standing rule — no auto-merge before smoke): regenerate a draft on any thread → confirm it ends with a closing line and no duplicate name; approve → send-confirm still lists recipients; (optionally) the sent body shows `closing` + single signature. Real send is user-driven only.

- [ ] **Gated prod migration:** on explicit user approval, apply 020 to the Railway prod DB (`alembic upgrade head`) and verify with a `SELECT signature FROM users WHERE email='jane@schilcpa.com'` (via the app's engine/inspector) that the closing is gone and the name/title/firm block remains. The client's Coolify instance picks up 020 on its own deploy.

- [ ] **Merge gate → development** (`--no-ff`), push + verify BOTH remotes, delete branch everywhere. Master promotion only on explicit approval.
