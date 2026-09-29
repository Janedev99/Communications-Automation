# Design — Outlook reply sync + "Start clean" to-do reset

**Date:** 2026-09-24 · **Tier:** 2 · **Stage:** 1 (architecture) · **Author role:** tech-cofounder
**Branches:** `FEAT/outlook-reply-sync` (A), `FEAT/start-clean-reset` (B, cut from `development` after A merges)
**Origin:** Gus's feedback on the client call with Sara, Gar, and Ami (reset button; Escalated should clear when Jane answers in Outlook).
**Decisions confirmed with RJ:** reset = cutoff timestamp (no row mutation); an Outlook reply resolves the escalation **and** retires stale drafts; the thread stays in the inbox.

---

## 0. Code findings that change the brief

1. **The "For review" and "Escalated" lanes are tier groupings, not to-do queues.** The t3 lane is `tier == t3_escalate OR status == escalated`, and the t2 lane is `tier == t2_review` (`api/emails.py:625-640`). Neither lane excludes `sent` or `closed`. The badges come from `threads_by_tier` (`api/dashboard.py:85-103`), which counts every status, including deleted and spam, while the list hides those (`emails.py:584-593`). Consequences:
   - A manually resolved escalation sets `categorized` but keeps tier t3, so the thread stays in the Escalated lane.
   - Feature A can't clear the lane with a status change alone.
   - After a Feature B reset, the lanes would fill up again with answered threads. See D1.
2. **App-sent mail is mostly stored under a local correlation id, not the real `internetMessageId`.** `/sendMail` returns a locally generated `<uuid@domain>`; only attachment sends go through `_send_via_draft` and get the real id. `auto_send.py` uses `<auto-{draft.id}@domain>`. So deduplicating Sent Items by `message_id_header` fails for most app sends (see §A.4 step 4).
3. **Graph sends carry no In-Reply-To or References headers.** App-sent replies likely get a new `conversationId`.
4. **The poller ingests only unread Inbox messages** (`email_provider.py:387-398`). Reply-sync covers only threads the app already holds.
5. **The mailbox is Jane's personal mailbox.** A move to a shared `office@` mailbox is planned. After it, Send-As replies land in the sender's own Sent Items unless `MessageCopyForSentAsEnabled` is on (R-A6).
6. *Pre-existing, out of scope:* when a new inbound message arrives on a thread with an open escalation, the status resets to `categorized` (`email_intake.py:~290`), and the engine returns the existing escalation without re-setting `escalated` (`services/escalation.py:~95-103`).
7. *Pre-existing:* the Escalations page "active" filter runs client-side after server pagination (`escalations/page.tsx:24-41`). Fixed in B.

## Decisions

| # | Decision | Recommendation |
|---|---|---|
| D1 | The t2 and t3 lanes hide `sent`/`closed` threads. Badges use the same predicate and also exclude deleted and spam. | t3 = `status==escalated OR (tier==t3 AND status NOT IN (sent, closed))`. t2 = `tier==t2 AND status NOT IN (sent, closed)`. |
| D2 | Thread status after an Outlook reply | `sent`. A `categorized` t2 thread with no draft would be re-drafted by `draft_catchup`. `sent→closed` is an allowed transition. |
| D3 | When the reply supersedes open work | Key on message time: act only if `sentDateTime >= latest inbound received_at`. `escalation.created_at` is the ingestion time, which lags the message time. |

---

# Feature A — Outlook reply sync

## A.1 Approach
Run a Graph delta query on `sentitems` with its own `SyncState` cursor (`delta:sentitems`). The first run captures a baseline only. For each new sent item that matches a thread by `conversationId`, is addressed to the client, and wasn't sent by the app:
- resolve open escalations,
- retire sendable drafts,
- set the thread to `sent`,
- store the reply as an outbound `EmailMessage`.

The feature is gated on `OUTLOOK_REPLY_SYNC` (default off). It is **read-only toward Outlook**.

## A.2 Data flow
```
poll_once()
  fetch_new_emails -> [delete-sync] -> Phase 1 ingest
  -> reply-sync (flag-gated, guarded; also on the no-new-mail early return)
  -> Phase 2 draft gen + maybe_auto_send ("already answered" guard)
```

## A.3 Provider (`services/email_provider.py`)
- `SentItem` dataclass: graph_id, internet_message_id, conversation_id, sent_at (aware UTC), to, cc, subject.
- ABC no-ops: `delta_sent_messages(*, delta_link)` returns `[], delta_link`; `fetch_message_by_graph_id(graph_id)` returns `None`. IMAP inherits both, so it is always baseline and never acts.
- MSGraph:
  - Extract `_walk_delta(url)` from `delta_folder_messages`. That behaviour must stay unchanged.
  - `delta_sent_messages` uses `/mailFolders/sentitems/messages/delta?changeType=created&$select=id,internetMessageId,conversationId,sentDateTime,toRecipients,ccRecipients,subject`, with no body.
  - `fetch_message_by_graph_id` uses `GET /messages/{id}` and parses via `_graph_msg_to_raw` (a pure extraction from `fetch_new_emails`).
- **Pre-build spike (read-only):** confirm delta `$select` support, `changeType=created`, and that an Outlook Reply keeps the inbound `conversationId`.
  - **Result, 2026-09-30 (passed).** Run read-only against the production mailbox; only counts were recorded.
    - `$select` and `changeType=created` are accepted. Only the selected fields are returned, with no body and no `@removed` entries. Every item carries id, internetMessageId, conversationId, sentDateTime and toRecipients.
    - 21 of 22 recent Outlook "RE:" replies share a `conversationId` with an earlier inbound message. The one miss is most likely a reply whose original is no longer in the mailbox.
    - Baseline: 18,266 sent items in 37 pages at `odata.maxpagesize=500`, taking 227 s. The slowest page took 7.8 s, well inside the 30 s httpx timeout. Replaying the fresh deltaLink returns 0 items.
    - Rollout consequence: the first poll after `OUTLOOK_REPLY_SYNC=true` takes about 4 minutes and delays that one poll's ingest. Enable the flag outside office hours.

## A.4 Reconcile (`services/email_intake.py`)
`_apply_outlook_reply(db, provider, item) -> outcome label`, no commit:
1. Match the thread by `provider_thread_id == conversation_id`, picking the most recently created match if more than one thread shares that conversationId, else `skipped_no_thread`. Uses `.scalars().first()` rather than `scalar_one_or_none()` — the latter raises `MultipleResultsFound` on a genuine (if rare) duplicate `conversationId`, which is a *deterministic* error that would otherwise stall the cursor on every poll (fixed post-QA: N1(b)).
2. Recipient guard: to∪cc must intersect the client email and the inbound senders, else `skipped_not_to_client`. This blocks forwards.
3. Idempotency: skip if an `EmailMessage` already has `message_id_header == internet_message_id`.
3b. Idempotency for an item that was already applied but never got a stored `EmailMessage` (an `applied_message_unstored` outcome on a prior poll — step 3 above can't catch it, since no row exists to find): skip if reply-sync's own audit trail (`email.sent_via_outlook_reply` / `escalation.resolved_via_outlook_reply` / `draft.retired_via_outlook_reply`, each now carrying `graph_id` and `internet_message_id` in `details`) already has an entry for this thread + `graph_id` (added post-QA: N1(b)). Without this, a batch redelivered while the cursor is held back (e.g. by a *different*, erroring item in the same batch) would re-run escalation-resolve / draft-retire / status-flip every poll and silently override any legitimate staff action taken in between — e.g. staff reopening the thread to `pending_review` and writing a fresh draft, which a naive replay would re-reject and flip back to `sent`.
4. App-send detection: skip if an outbound message **at or after the latest inbound message's `received_at`** falls within ±10 minutes of `sent_at` and shares a recipient. The `received_at >= latest inbound` qualifier matters: an older app-sent reply from a *prior* round must not falsely dedupe a genuine new Outlook reply to a *later* client follow-up just because the two happen to land within ±10 minutes of each other in absolute time — only a message that could plausibly be answering the same inbound message counts (fixed post-QA; originally compared absolute time only).
5. Supersede (D3): skip if the latest inbound `received_at` is after `sent_at`.
6. Resolve every pending or acknowledged escalation: `resolved`, `resolved_at=sent_at`, `resolved_by_id=None`, notes "Replied in Outlook". Audit `escalation.resolved_via_outlook_reply` (system actor).
7. Retire drafts in pending, edited, approved, or send_failed, using `with_for_update(skip_locked=True)`: set `rejected`, `rejection_reason=None`, `reviewed_by_id=None`, `reviewed_at=now`. Audit `draft.retired_via_outlook_reply`. A NULL reason keeps these out of `get_negative_patterns`, so the AI learns nothing from them.
8. Active statuses become `sent` (D2); closed, deleted, spam, and sent stay as they are. Tier is unchanged. Do **not** call `auto_save_to_client_folder`. Audit `email.sent_via_outlook_reply`.
9. Store the outbound message via `fetch_message_by_graph_id` inside `begin_nested()`, with `raw_headers={"X-AutoComms-Source":"outlook-reply-sync"}` and the same attachment-metadata serialization intake uses for inbound messages. Sender falls back to the mailbox address (`settings.msgraph_mailbox`), never `thread.client_email` — this message was sent BY the firm, not the client. A fetch failure or IntegrityError (e.g. a race landing the same `message_id_header` between step 3's check and this flush) doesn't undo steps 6-8; the item's outcome is `applied_message_unstored` instead of `applied`.

`reconcile_outlook_replies(provider)` mirrors `reconcile_outlook_deletions`: each item runs in its own savepoint (so one bad item can't derail the rest of the batch), and counters are kept per outcome. The cursor normally advances only when the **whole batch** finished with zero `error` outcomes — Graph's delta cursor has no "retry just this item" mechanism, so a batch containing an errored item leaves the cursor untouched and the entire batch is retried next poll (fixed post-QA; originally advanced regardless of per-item errors). Replaying the batch is safe because every step is idempotent, INCLUDING for an `applied_message_unstored` item (step 3b's audit-based check, added post-QA — the original design called this idempotent without the audit fallback, which was true for `applied` items but not for `applied_message_unstored` ones). A *transient* error resolves itself once the cursor is free to advance past a clean batch; a *deterministic* error (e.g. the `MultipleResultsFound` case step 1 now avoids) would otherwise hold the cursor forever, so a consecutive-poll error streak (its own `SyncState` row, `delta:sentitems:error_streak`) forces the cursor forward anyway after 3 polls in a row each had an error, logging the failed `graph_id`s at ERROR for manual follow-up (added post-QA: N1(a)).

`maybe_auto_send` guards: return False if the thread has an outbound message with `received_at >= latest inbound received_at`, **or** if `thread.status in (sent, closed)` (added post-QA — the outbound-message guard alone misses the `applied_message_unstored` case, where reply-sync flips the thread to `sent` but stores no outbound row).

Phase 2 of `poll_once` (draft generation) re-reads each thread's status before generating: a thread Phase 1 queued as needing a draft may have been flipped to `sent`/`closed`/`deleted`/`spam` by reply-sync running in between (same poll cycle) — that thread is skipped rather than given a duplicate draft (added post-QA).

## A.5 Config
`outlook_reply_sync: bool = False`, set by env `OUTLOOK_REPLY_SYNC`.

## A.6 D1 lanes
New `services/todo_queue.py` with `lane_clause(tier)`, used by both `emails.py` list_threads and `dashboard.py` badges.

## A.7 Migration
None.

## A.8 Edge cases
- First enable is baseline only.
- A large Sent Items folder uses a body-less baseline with the page cap.
- Re-emits are no-ops.
- Forwards are skipped.
- If the client writes after the reply, the work stays open.
- If Jane edits the subject, there may be no match (accepted).
- App sends are skipped.
- Deleted or junked threads keep their status, but their drafts are retired.
- A concurrent manual send is protected by `skip_locked`.
- IMAP is a no-op.
- All comparisons use aware UTC (`_as_utc`).

## A.9 Risks
| ID | Risk | Mitigation |
|---|---|---|
| R-A1 | Duplicate client reply | Retire all sendable drafts; `maybe_auto_send`'s outbound-message AND thread-status guards; reply-sync runs after Phase 1 but before Phase 2, and Phase 2 re-reads thread status per-item so a same-cycle reply-sync match is never given a duplicate draft (fixed post-QA — originally only the outbound-message guard existed, missing the `applied_message_unstored` case, and Phase 2 trusted Phase 1's stale snapshot) |
| R-A2 | A forward wrongly resolves an escalation | Recipient guard; audit-logged; reversible |
| R-A3 | A long first baseline | No bodies selected; large pages; log duration |
| R-A4 | Graph delta `$select`/`changeType` behaves differently | Spike; idempotent logic |
| R-A5 | Duplicate outbound rows | Idempotency + ±10 minute window (qualified to at-or-after the latest inbound message — fixed post-QA) |
| R-A6 | Shared-mailbox move | HANDOFF checklist: `MessageCopyForSentAsEnabled` |
| R-A7 | Live mailbox | GET only; test asserts no Graph writes |
| R-A8 | `_graph_msg_to_raw` refactor breaks intake | Pure extraction; existing provider tests stay green |
| R-A9 | A deterministically-failing item stalls the cursor forever, and replaying an `applied_message_unstored` item overrides a legitimate staff action taken in the interim | Error-streak cap (3 polls) forces the cursor forward + logs ERROR with the failed `graph_id`s; step 3b's audit-based idempotency check; step 1's thread lookup no longer raises on a duplicate `conversationId` (added post-QA: N1) |

## A.10 Tests
New file `tests/test_outlook_reply_sync.py`, plus additions in `test_auto_send.py` and a D1 lane test. Covers:
- the flag off,
- the baseline,
- the cursor,
- escalation resolve,
- the status change to `sent` with tier kept,
- draft retirement for all four statuses,
- retired drafts excluded from negative patterns,
- 409 on approve/send of a retired draft,
- outbound storage,
- idempotency,
- the app-send window,
- forwards,
- a client writing after the reply,
- the D3 regression,
- an unmatched conversation,
- closed or deleted threads,
- a body-fetch failure,
- a delta failure,
- IMAP no-op,
- the auto-send guard,
- the lane predicate and badge/list parity,
- Graph delta parsing,
- the walker extraction being unchanged,
- the error-streak forcing the cursor forward after N polls (added post-QA: N1(a)),
- a replayed `applied_message_unstored` item not overriding a staff reopen + new draft (added post-QA: N1(b)).

## A.11 Rollout
1. Merge to `development` with the flag off.
2. Run the spike.
3. Set `OUTLOOK_REPLY_SYNC=true` on Railway and check for the "baseline captured" log line.
4. Smoke test on a test thread.
5. Roll back by unsetting the flag.
6. Merging to `main` only with RJ's approval.

---

# Feature B — "Start clean" reset (cutoff timestamp)

## B.1 Approach
Store `todo_cutoff_at` in `system_settings`. The to-do surfaces hide threads that have no activity at or after the cutoff. No rows are changed. Undo restores the previous cutoff. Analytics, All, search, folders, Sent, AI learning, and the audit log ignore the cutoff.

## B.2 Visibility predicate
A thread is visible if any of these is true:
```
thread.created_at >= cutoff
OR EXISTS inbound EmailMessage with received_at >= cutoff
OR EXISTS Escalation with created_at >= cutoff
```
- It deliberately does not key on `updated_at`, which is bumped by many unrelated actions.
- Escalation rows are visible if `created_at >= cutoff` or their thread is visible. Drafts follow the same rule.

## B.3 Where it applies (all through `services/todo_queue.py`)
| Surface | Location |
|---|---|
| t2 and t3 lane lists | `api/emails.py:625-640` |
| Lane badges (via `todo_counts`, also excludes deleted/spam) | `api/dashboard.py:85-103` |
| Pending escalations total (sidebar dot, dashboard card) | `dashboard.py:139-148` |
| High/critical badge | `dashboard.py:119-125` |
| Drafts-pending-review card | `dashboard.py:151-155` |
| Escalations page: server-side `active=true` + visibility, with `include_hidden` | `api/escalations.py:57-93`; `escalations/page.tsx:24-41` |
| Draft catch-up skips hidden threads | `services/draft_catchup.py:57-100` |

**Unchanged:** analytics, search, All, saved, sent_only, status dropdown, draft_feedback, get_thread_escalation, audit log.

## B.4 Endpoints (`api/system_settings.py`, admin + CSRF on writes)
- Keys `todo_cutoff_at` and `todo_cutoff_previous` (ISO UTC, or `""`). They are **not** in `_PATCHABLE_KEYS`.
- `GET /system-settings/todo-reset` returns `{cutoff_at, set_by_name, set_at, can_undo, would_hide:{escalations, reviews}}`.
- `POST /system-settings/todo-reset` sets the cutoff to server time, saves the previous value, and audits `todo_reset.applied` with the counts.
- `DELETE /system-settings/todo-reset` restores the previous value and audits `todo_reset.undone`. It returns 409 when there is nothing to undo.
- `/dashboard/stats` exposes `todo_cutoff_at`.

## B.5 Frontend
- Admin-only "To-do list" section in `settings/page.tsx` containing `components/settings/todo-reset-card.tsx`.
- The card shows the current state, a "Start clean" button that opens `ConfirmDialog` with live counts, and Undo.
- After a reset or undo it calls `mutate` on dashboard stats.
- Optional lane notice when a cutoff is set.
- The Escalations page switches to the server-side active filter.

## B.6 Migration
None.

## B.7 Edge cases
- Reset twice, then undo: restores the first cutoff.
- A new inbound message on a hidden thread brings it back.
- Old open escalations stay hidden but open, and Feature A still resolves them.
- Staff see the filtered lanes but can't reset.
- Preview and confirm counts may drift slightly; the audit log records the actual counts.
- No cutoff: same behaviour as today (apart from D1).

## B.8 Risks
- **R-B1:** Jane thinks work was deleted. Mitigated by the dialog copy, the lane notice, Undo, and All.
- **R-B2:** a count and a list disagree. Mitigated by one predicate module and a parity test.
- **R-B3:** analytics differs from the to-do. Intended and documented.
- **R-B4:** timezone problems. Mitigated by server time and aware UTC.
- **R-B5:** EXISTS cost. Measure with EXPLAIN before adding an index.

## B.9 Tests
New file `tests/test_todo_reset.py`. Covers:
- no cutoff,
- old threads hidden,
- All and search unaffected,
- a new inbound message resurfacing a thread,
- a new escalation being visible,
- an `updated_at` bump not resurfacing a thread,
- badge/list parity,
- escalation and severity counts,
- the drafts count,
- the server-side active view,
- analytics and draft_feedback unaffected,
- catch-up skipping hidden threads,
- admin + CSRF required,
- server time and audit counts,
- undo and the 409,
- the keys not being patchable.

## B.10 Rollout
- There is no flag; nothing happens until an admin presses the button.
- Smoke test on a prod snapshot, not the shared prod DB.
- Merging to `main` only with RJ's approval.

## Sequencing
A (including D1), then B on `FEAT/start-clean-reset` after A merges.

## Out of scope
- In-Reply-To/References fallback.
- Backfilling real internetMessageIds.
- Staff mailbox Sent Items.
- Finding 0.6.
- A bulk-mutation reset.

---

# Feature B — implementation notes (2026-09-30)

- Line references in B.3 had drifted; the code was followed (dashboard stats now read every to-do number from `services/todo_queue.todo_counts`).
- `lane_clause` / `badge_clause` gained an optional `cutoff` argument rather than a parallel module. t1_auto is not a to-do lane and ignores the cutoff.
- `GET /escalations?active=true` applies the cutoff; `include_hidden=true` bypasses it. Other views (resolved, all statuses, get-by-id) ignore it.
- Undo is one level deep: it consumes `todo_cutoff_previous`, so a second Undo returns 409.
- Audit details: `todo_reset.applied` records `hidden_escalations`, `hidden_reviews`, `hidden_escalated_threads`, `hidden_drafts_pending`; `todo_reset.undone` records `restored_escalations`, `restored_reviews`.
- R-B5: EXPLAIN QUERY PLAN (SQLite) shows both EXISTS subqueries use `ix_email_messages_thread_id` and `ix_escalations_thread_id`; no new index added. Re-check on Postgres against a prod snapshot.
