"""
Email intake service.

Responsibilities:
  1. Poll the configured email provider for new messages
  2. Deduplicate by message_id_header (unique constraint in DB)
  3. Group messages into threads (by In-Reply-To/References or provider thread ID)
  4. Store EmailThread + EmailMessage records
  5. Bounce detection (T1.9) — bounce emails are stored but skipped for AI
  6. Trigger categorization for each new inbound message
  7. Trigger escalation check on categorization result
  8. Generate AI drafts in a SEPARATE transaction after poll commits (T1.8)
  9. Track last_successful_poll_at + last_successful_llm_at (T1.13)

This module also exposes `start_polling_loop()` which is called once
from the FastAPI lifespan as a background asyncio task.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.email import (
    CategorizationSource,
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    SyncState,
    ThreadTier,
)
from app.models.escalation import Escalation, EscalationStatus
from app.services.categorizer import get_categorizer
from app.services.email_provider import RawEmail, SentItem, get_email_provider
from app.services.escalation import get_escalation_engine
from app.services.tier_engine import decide_tier
from app.utils.audit import log_action

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Module-level health timestamps (T1.13) ────────────────────────────────────
# These are module-level because the polling loop runs in a background thread.
# They are read by the dashboard health endpoint (no locking needed for V1 — only
# one writer, reads are eventually consistent which is fine for a health probe).
last_successful_poll_at: datetime | None = None
# Renamed from last_successful_anthropic_at when the LLM provider became
# pluggable (anthropic | openai_compat / RunPod). The dashboard health field
# was renamed in lockstep (`llm_reachable` instead of `anthropic_reachable`).
last_successful_llm_at: datetime | None = None


def _record_successful_poll() -> None:
    global last_successful_poll_at
    last_successful_poll_at = datetime.now(timezone.utc)


def _record_successful_llm_call() -> None:
    global last_successful_llm_at
    last_successful_llm_at = datetime.now(timezone.utc)


# ── Bounce detection (T1.9) ───────────────────────────────────────────────────

_BOUNCE_SENDER_RE = re.compile(
    r"^(mailer-daemon@|postmaster@|[^@]+@[^@]*bounce[^@]*@)",
    re.IGNORECASE,
)
_BOUNCE_SUBJECT_RE = re.compile(
    r"^(undeliverable:|delivery status notification|mail delivery failed|failure notice)",
    re.IGNORECASE,
)


def _is_bounce(sender: str, subject: str) -> bool:
    """
    Return True if this email looks like a bounce/delivery-failure notification.

    Bounces are stored with is_bounce=True but skipped for categorization and
    draft generation.
    """
    # Normalise: extract just the address part for sender matching
    addr_match = re.search(r"<([^>]+)>", sender)
    sender_addr = addr_match.group(1).strip() if addr_match else sender.strip()

    if _BOUNCE_SENDER_RE.match(sender_addr):
        return True
    if _BOUNCE_SUBJECT_RE.match(subject.strip()):
        return True
    return False


# ── Sender / thread helpers ────────────────────────────────────────────────────

def _extract_sender_parts(sender: str) -> tuple[str, str]:
    """
    Parse "Display Name <email@domain>" → (name, email).
    Falls back to ("", sender) if no angle brackets found.
    """
    match = re.match(r'^(.*?)\s*<([^>]+)>$', sender.strip())
    if match:
        name = match.group(1).strip().strip('"')
        address = match.group(2).strip()
        return name, address
    # Plain email address, no display name
    return "", sender.strip()


def _find_or_create_thread(db: Session, raw: RawEmail) -> EmailThread:
    """
    Find an existing thread for this message or create a new one.

    Thread matching priority:
    1. Provider thread ID (exact match)
    2. In-Reply-To / References header (match by message_id_header of a sibling)
    3. New thread
    """
    # 1. Provider thread ID
    if raw.provider_thread_id:
        existing = db.execute(
            select(EmailThread).where(
                EmailThread.provider_thread_id == raw.provider_thread_id
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    # 2. In-Reply-To or References
    reply_refs: list[str] = []
    if raw.in_reply_to:
        reply_refs.append(raw.in_reply_to.strip())
    if raw.references:
        reply_refs.extend(raw.references.split())

    for ref_id in reply_refs:
        ref_id = ref_id.strip()
        if not ref_id:
            continue
        existing_msg = db.execute(
            select(EmailMessage).where(EmailMessage.message_id_header == ref_id)
        ).scalar_one_or_none()
        if existing_msg:
            return db.execute(
                select(EmailThread).where(EmailThread.id == existing_msg.thread_id)
            ).scalar_one()

    # 3. Create new thread
    _, client_email = _extract_sender_parts(raw.sender)
    client_name, _ = _extract_sender_parts(raw.sender)

    thread = EmailThread(
        subject=raw.subject,
        client_email=client_email or raw.sender,
        client_name=client_name or None,
        status=EmailStatus.new,
        category=EmailCategory.uncategorized,
        provider_thread_id=raw.provider_thread_id,
    )
    db.add(thread)
    db.flush()
    return thread


def _store_message(db: Session, thread: EmailThread, raw: RawEmail) -> EmailMessage | None:
    """
    Persist a RawEmail as an EmailMessage.  Returns None if already stored (duplicate).
    """
    existing = db.execute(
        select(EmailMessage).where(
            EmailMessage.message_id_header == raw.message_id
        )
    ).scalar_one_or_none()

    if existing is not None:
        logger.debug("Skipping duplicate message_id=%s", raw.message_id)
        return None

    # Serialize attachment metadata to plain dicts (JSON-safe)
    attachment_data = (
        [a.to_dict() for a in raw.attachments] if raw.attachments else None
    )

    message = EmailMessage(
        thread_id=thread.id,
        message_id_header=raw.message_id,
        sender=raw.sender,
        recipient=raw.recipient,
        to_recipients=raw.to_recipients or None,
        cc_recipients=raw.cc_recipients or None,
        body_text=raw.body_text,
        body_html=raw.body_html,
        received_at=raw.received_at,
        direction=MessageDirection.inbound,
        is_processed=False,
        raw_headers=raw.raw_headers,
        attachments=attachment_data if attachment_data else None,
    )
    db.add(message)
    db.flush()
    return message


def _should_generate_draft(
    *,
    escalated: bool,
    tier: ThreadTier,
    category: EmailCategory,
    draft_auto_generate: bool,
) -> bool:
    """Whether to auto-generate an AI draft for a newly-processed thread.

    - Escalated or T3 → no (a human handles these).
    - Promotional / automated mail → no (no reply needed; saves AI credits).
    - Otherwise gated only by ``draft_auto_generate``.

    Note: shadow_mode does NOT appear here. Drafts are generated even in shadow
    mode — shadow_mode gates only auto-SEND (see auto_send.maybe_auto_send), so a
    T1 thread gets a draft for review when auto-send is off and is auto-sent only
    when auto-send is enabled.
    """
    return (
        not escalated
        and tier != ThreadTier.t3_escalate
        and category != EmailCategory.promotional
        and draft_auto_generate
    )


def process_single_email(db: Session, raw: RawEmail) -> uuid.UUID | None:
    """
    Process one raw email: store it, categorize, check escalation.

    Returns thread_id if a draft should be generated (not escalated, auto-generate
    enabled, not a bounce), otherwise None.

    Called from both the polling loop and tests.

    T1.8: Draft generation is NOT performed here. The caller collects the list of
    thread_ids that need drafts and generates them in separate transactions after
    this function's transaction commits.
    """
    # T1.9: Bounce detection — store but skip AI processing
    is_bounce = _is_bounce(raw.sender, raw.subject)

    thread = _find_or_create_thread(db, raw)
    message = _store_message(db, thread, raw)

    if message is None:
        return None  # Already processed

    if is_bounce:
        logger.info(
            "Bounce email detected from %s subject=%r — stored, skipping AI",
            raw.sender, raw.subject,
        )
        # Mark as processed so it doesn't get retried
        message.is_processed = True
        db.flush()
        return None

    # Categorize
    categorizer = get_categorizer()
    body = raw.body_text or raw.body_html or ""
    result = categorizer.categorize(
        sender=raw.sender,
        subject=raw.subject,
        body=body,
    )

    # Record successful Anthropic call for health tracking (T1.13).
    # ONLY when Claude actually answered — rules-fallback results don't count
    # as evidence Anthropic is reachable, otherwise the integrations health
    # page lies during a Claude outage.
    if result.source == CategorizationSource.claude:
        _record_successful_llm_call()

    # Update thread with categorization
    thread.category = result.category
    thread.category_confidence = result.confidence
    thread.ai_summary = result.summary
    thread.suggested_reply_tone = result.suggested_reply_tone
    thread.categorization_source = result.source
    thread.status = EmailStatus.categorized
    thread.updated_at = datetime.now(timezone.utc)

    # Phase 3: tier decision (T1 / T2 / T3)
    tier_decision = decide_tier(db, result=result, source=result.source)
    thread.tier = tier_decision.tier
    thread.tier_set_at = datetime.now(timezone.utc)
    thread.tier_set_by = "system"

    # Mark message processed
    message.is_processed = True

    db.flush()

    # Audit
    log_action(
        db,
        action="email.categorized",
        entity_type="email_thread",
        entity_id=str(thread.id),
        details={
            "category": result.category.value,
            "confidence": result.confidence,
            "escalation_needed": result.escalation_needed,
            "source": result.source.value,
            "tier": tier_decision.tier.value,
            "tier_reason": tier_decision.reason,
            "message_id": str(message.id),
        },
    )

    # Check escalation
    engine = get_escalation_engine()
    escalation = engine.process(db, thread, result)
    if escalation:
        log_action(
            db,
            action="escalation.created",
            entity_type="escalation",
            entity_id=str(escalation.id),
            details={
                "thread_id": str(thread.id),
                "severity": escalation.severity.value,
                "reason": escalation.reason,
            },
        )

    logger.info(
        "Processed email: thread=%s message=%s category=%s escalated=%s",
        thread.id, message.id, result.category, result.escalation_needed,
    )

    # T1.8: Return thread_id for deferred draft generation only if appropriate.
    # T3 (escalated) skips draft generation. T1 + T2 both get drafts; T1 may
    # additionally trigger auto-send in a future enhancement (currently shadow-only).
    should_generate_draft = _should_generate_draft(
        escalated=escalation is not None,
        tier=tier_decision.tier,
        category=result.category,
        draft_auto_generate=settings.draft_auto_generate,
    )
    return thread.id if should_generate_draft else None


def _generate_draft_for_thread(thread_id: uuid.UUID) -> None:
    """
    Generate an AI draft for a single thread in its own DB session (T1.8).

    Errors are caught per-thread and stored as draft_generation_failed on the
    thread record so staff can see which threads need manual drafts.

    Phase 3: After a draft is generated for a T1 thread, attempt auto-send
    (gated by system_settings.auto_send_enabled + config.shadow_mode).
    """
    db = SessionLocal()
    try:
        thread = db.execute(
            select(EmailThread).where(EmailThread.id == thread_id)
        ).scalar_one_or_none()

        if thread is None:
            logger.warning("Draft generation: thread %s not found", thread_id)
            return

        from app.services.draft_generator import get_draft_generator
        generator = get_draft_generator()
        draft = generator.generate(db, thread)
        db.commit()

        # Draft generation only happens when Claude responded successfully.
        # Mark Anthropic reachable for health tracking.
        _record_successful_llm_call()

        logger.info(
            "Auto-generated draft %s for thread=%s",
            draft.id, thread.id,
        )

        # Phase 3: T1 auto-send. The function manages its own commits so the
        # persisted state always matches reality even if we rollback below.
        if thread.tier == ThreadTier.t1_auto:
            from app.services.auto_send import maybe_auto_send
            try:
                maybe_auto_send(db, thread_id=thread.id, draft_id=draft.id)
            except Exception as exc:
                # maybe_auto_send is contractually never-raises, but be defensive.
                logger.error(
                    "auto_send wrapper unexpectedly raised for thread=%s: %s",
                    thread.id, exc, exc_info=True,
                )
    except Exception as exc:
        db.rollback()
        logger.error(
            "Draft generation failed for thread %s (non-fatal): %s",
            thread_id, exc, exc_info=True,
        )
        # T2.5: Mark thread as draft_generation_failed so staff can see it
        try:
            thread = db.execute(
                select(EmailThread).where(EmailThread.id == thread_id)
            ).scalar_one_or_none()
            if thread is not None:
                thread.draft_generation_failed = True  # type: ignore[attr-defined]
                thread.draft_generation_failed_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
                db.commit()
        except Exception as inner_exc:
            logger.error(
                "Failed to mark draft_generation_failed for thread %s: %s",
                thread_id, inner_exc,
            )
    finally:
        db.close()


# ── Outlook → app delete sync ─────────────────────────────────────────────────
# Each entry: (provider logical folder, sync_state cursor key, target status a
# matched thread is flipped to). Deleted Items → deleted; Junk → spam.
_DELETE_SYNC_FOLDERS: list[tuple[str, str, EmailStatus]] = [
    ("deleted_items", "delta:deleteditems", EmailStatus.deleted),
    ("junk_email", "delta:junkemail", EmailStatus.spam),
]

# Statuses we never overwrite from an Outlook-side deletion: already-terminal
# (deleted/spam) so we don't churn, and closed (resolved) so a tidy-up delete in
# Outlook doesn't rewrite a thread staff already resolved.
_DELETE_SYNC_SKIP_STATUSES = frozenset(
    {EmailStatus.deleted, EmailStatus.spam, EmailStatus.closed}
)


def _apply_outlook_deletions(
    db: Session, internet_message_ids: list[str], target_status: EmailStatus
) -> int:
    """
    Flip every local thread that owns one of ``internet_message_ids`` to
    ``target_status`` (unless already terminal). Returns the number of threads
    changed. Writes an audit entry per thread (system actor). Does NOT commit —
    the caller owns the transaction.
    """
    if not internet_message_ids:
        return 0
    rows = (
        db.execute(
            select(EmailMessage.thread_id).where(
                EmailMessage.message_id_header.in_(internet_message_ids)
            )
        )
        .scalars()
        .all()
    )
    changed = 0
    for thread_id in set(rows):
        thread = db.get(EmailThread, thread_id)
        if thread is None or thread.status in _DELETE_SYNC_SKIP_STATUSES:
            continue
        old_status = thread.status
        thread.status = target_status
        thread.updated_at = datetime.now(timezone.utc)
        log_action(
            db,
            action=f"email.{target_status.value}_via_outlook_sync",
            entity_type="email_thread",
            entity_id=str(thread.id),
            details={
                "old_status": old_status.value,
                "new_status": target_status.value,
                "source": "outlook_delete_sync",
            },
            user_id=None,
        )
        changed += 1
    return changed


def reconcile_outlook_deletions(provider) -> int:
    """
    Reflect mail Jane deleted/junked in Outlook back into the app: delta-query
    Deleted Items + Junk, and flip matching local threads to deleted/spam so
    they leave the to-do. Gated by the caller on ``settings.email_delete_sync``.

    First run per folder (no stored deltaLink) is baseline-only: it captures the
    cursor without acting, so pre-existing deletions aren't retroactively
    applied. Each folder is reconciled in its own transaction so one failing
    folder can't roll back the other. Returns the number of threads updated.
    """
    total_changed = 0
    for folder, cursor_key, target_status in _DELETE_SYNC_FOLDERS:
        db = SessionLocal()
        try:
            state = db.get(SyncState, cursor_key)
            prior_link = state.value if state else None
            try:
                ids, next_link = provider.delta_folder_messages(
                    folder=folder, delta_link=prior_link
                )
            except Exception as exc:
                logger.warning(
                    "Delete-sync: delta fetch failed for %s: %s", folder, exc
                )
                continue

            # Baseline run (no prior cursor): capture the deltaLink only.
            if prior_link is not None:
                total_changed += _apply_outlook_deletions(db, ids, target_status)

            if next_link:
                if state is None:
                    db.add(SyncState(key=cursor_key, value=next_link))
                else:
                    state.value = next_link
                    state.updated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(
                "Delete-sync: reconcile failed for %s: %s", folder, exc, exc_info=True
            )
        finally:
            db.close()
    return total_changed


# ── Outlook → app reply sync (FEAT/outlook-reply-sync, Feature A) ─────────────
# A reply Jane (or any user with mailbox access) sends directly from Outlook —
# bypassing the app entirely — is otherwise invisible to it: the escalation
# stays open and a stale AI draft can still get sent later. This mirrors that
# reply back: resolve the thread's open escalations, retire its sendable
# drafts, and flip it to `sent` (D2). READ-only toward Outlook throughout — no
# Graph writes, no auto_save_to_client_folder. Gated on
# `settings.outlook_reply_sync` (default off).

_REPLY_SYNC_CURSOR_KEY = "delta:sentitems"

# Draft states an Outlook reply can retire. Mirrors the states staff review —
# anything not yet a terminal send/reject.
_RETIRABLE_DRAFT_STATUSES = frozenset(
    {DraftStatus.pending, DraftStatus.edited, DraftStatus.approved, DraftStatus.send_failed}
)

# Escalation states still "open" from Jane's point of view.
_OPEN_ESCALATION_STATUSES = (EscalationStatus.pending, EscalationStatus.acknowledged)

# Thread statuses an Outlook reply must NOT overwrite — already-terminal
# (sent/closed) so a redundant reply doesn't churn `updated_at`, and
# deleted/spam so a tidy-up reply after Jane trashed/junked a thread doesn't
# resurrect it. Mirrors _DELETE_SYNC_SKIP_STATUSES. Escalation resolution and
# draft retirement (steps 6-7) still run regardless of thread status — a
# deleted/junked thread's stale drafts still get retired (A.8 edge case).
_REPLY_SYNC_SKIP_STATUSES = frozenset(
    {EmailStatus.sent, EmailStatus.closed, EmailStatus.deleted, EmailStatus.spam}
)

# App-send detection window (A.4 step 4): most app sends carry a locally
# generated correlation id rather than the real internetMessageId (see design
# doc §0.2), so idempotency alone can't catch "this is our own reply echoing
# back from Sent Items." A reply within this window of an app-recorded
# outbound message, sharing a recipient, is treated as that same send.
_APP_SEND_WINDOW = timedelta(minutes=10)


def _as_utc(dt: datetime) -> datetime:
    """Coerce a naive datetime to aware UTC. A.8: all reply-sync comparisons
    use aware UTC — SQLite (tests) round-trips naive datetimes as-is."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _apply_outlook_reply(db: Session, provider, item: SentItem) -> str:
    """
    Reconcile one Sent Items delta entry against local state. Returns an
    outcome label for the caller's per-outcome counters. Does NOT commit —
    ``reconcile_outlook_replies`` owns the transaction (each item runs inside
    its own savepoint, so one bad item can't derail the rest of the batch).

    See design doc §A.4 for the numbered steps this follows.
    """
    # 1. Match the thread by conversationId.
    if not item.conversation_id:
        return "skipped_no_thread"
    thread = db.execute(
        select(EmailThread).where(
            EmailThread.provider_thread_id == item.conversation_id
        )
    ).scalar_one_or_none()
    if thread is None:
        return "skipped_no_thread"

    inbound_messages = db.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == MessageDirection.inbound,
        ).order_by(EmailMessage.received_at.desc())
    ).scalars().all()
    if not inbound_messages:
        # A thread with no inbound message at all isn't one reply-sync should
        # ever touch — there's nothing for this reply to be answering.
        return "skipped_no_thread"

    # 2. Recipient guard — to∪cc must intersect the client's own address (the
    # thread record) or one of the thread's inbound senders. Blocks forwards:
    # a forward to a third party shares the conversationId but not a
    # recipient with the client, so it never resolves the escalation or
    # retires the drafts.
    reply_recipients = {a.strip().lower() for a in (item.to + item.cc) if a}
    known_senders = {
        _extract_sender_parts(m.sender)[1].strip().lower() for m in inbound_messages
    }
    if thread.client_email:
        known_senders.add(thread.client_email.strip().lower())
    if not reply_recipients & known_senders:
        return "skipped_not_to_client"

    # 3. Idempotency — this exact message is already stored (a re-emitted
    # delta entry, or we already processed it on a prior poll).
    if item.internet_message_id:
        existing_msg = db.execute(
            select(EmailMessage).where(
                EmailMessage.message_id_header == item.internet_message_id
            )
        ).scalar_one_or_none()
        if existing_msg is not None:
            return "skipped_idempotent"

    sent_at = _as_utc(item.sent_at)

    # 4. App-send detection — an outbound message already on the thread,
    # within the window and sharing a recipient, is almost certainly the
    # same send echoing back from Sent Items rather than a separate reply.
    outbound_messages = db.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == MessageDirection.outbound,
        )
    ).scalars().all()
    for ob in outbound_messages:
        ob_sent_at = _as_utc(ob.received_at)
        if abs(ob_sent_at - sent_at) > _APP_SEND_WINDOW:
            continue
        ob_recipients = {
            a.strip().lower()
            for a in (ob.to_recipients or ([ob.recipient] if ob.recipient else []))
            if a
        }
        if ob_recipients & reply_recipients:
            return "skipped_app_send"

    # 5. Supersede (D3) — key on message time, not escalation.created_at
    # (which lags ingestion). If the client wrote again after this reply was
    # sent, the thread's work is still open; don't resolve/retire/close it.
    latest_inbound_at = _as_utc(inbound_messages[0].received_at)
    if latest_inbound_at > sent_at:
        return "skipped_superseded"

    # 6. Resolve every open escalation on the thread.
    open_escalations = db.execute(
        select(Escalation).where(
            Escalation.thread_id == thread.id,
            Escalation.status.in_(_OPEN_ESCALATION_STATUSES),
        )
    ).scalars().all()
    for esc in open_escalations:
        esc.status = EscalationStatus.resolved
        esc.resolved_at = sent_at
        esc.resolved_by_id = None
        esc.resolution_notes = "Replied in Outlook"
        log_action(
            db,
            action="escalation.resolved_via_outlook_reply",
            entity_type="escalation",
            entity_id=str(esc.id),
            details={"thread_id": str(thread.id)},
            user_id=None,
        )

    # 7. Retire every sendable draft — a client answered in Outlook shouldn't
    # also receive a stale AI draft later. skip_locked so a concurrent manual
    # send wins the race instead of erroring out.
    retirable_drafts = db.execute(
        select(DraftResponse)
        .where(
            DraftResponse.thread_id == thread.id,
            DraftResponse.status.in_(_RETIRABLE_DRAFT_STATUSES),
        )
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for draft in retirable_drafts:
        draft.status = DraftStatus.rejected
        # NULL reason (not "Replied in Outlook") — this isn't Jane's feedback
        # on draft quality, so it must stay out of get_negative_patterns.
        draft.rejection_reason = None
        draft.reviewed_by_id = None
        draft.reviewed_at = datetime.now(timezone.utc)
        log_action(
            db,
            action="draft.retired_via_outlook_reply",
            entity_type="draft_response",
            entity_id=str(draft.id),
            details={"thread_id": str(thread.id)},
            user_id=None,
        )

    # 8. Active statuses become `sent` (D2); closed/deleted/spam/sent are left
    # untouched. Tier is unchanged — D1's lane predicate (services/todo_queue)
    # is what actually clears the to-do lane for a `sent` thread. Never calls
    # auto_save_to_client_folder — this path is read-only toward Outlook.
    if thread.status not in _REPLY_SYNC_SKIP_STATUSES:
        thread.status = EmailStatus.sent
        thread.updated_at = datetime.now(timezone.utc)
        log_action(
            db,
            action="email.sent_via_outlook_reply",
            entity_type="email_thread",
            entity_id=str(thread.id),
            details={"conversation_id": item.conversation_id},
            user_id=None,
        )

    # 9. Store the outbound message, isolated in its own savepoint: a fetch
    # failure (Graph error) or IntegrityError (a race with an app send that
    # landed the same message_id_header between step 3's check and here)
    # must not undo steps 6-8 — the escalation is genuinely resolved and the
    # drafts are genuinely stale regardless of whether a copy of the reply
    # itself gets stored.
    try:
        with db.begin_nested():
            raw = provider.fetch_message_by_graph_id(item.graph_id)
            if raw is None:
                raise LookupError(f"message {item.graph_id} not fetchable")
            outbound = EmailMessage(
                thread_id=thread.id,
                message_id_header=raw.message_id,
                sender=raw.sender or thread.client_email,
                recipient=item.to[0] if item.to else None,
                to_recipients=item.to or None,
                cc_recipients=item.cc or None,
                body_text=raw.body_text,
                body_html=raw.body_html,
                received_at=sent_at,
                direction=MessageDirection.outbound,
                is_processed=True,
                raw_headers={
                    **(raw.raw_headers or {}),
                    "X-AutoComms-Source": "outlook-reply-sync",
                },
            )
            db.add(outbound)
            db.flush()
    except Exception as exc:
        logger.warning(
            "Reply-sync: could not store outbound copy for thread=%s graph_id=%s: %s",
            thread.id, item.graph_id, exc,
        )
        return "applied_message_unstored"

    return "applied"


def reconcile_outlook_replies(provider) -> dict[str, int]:
    """
    Reflect an Outlook-only reply back into the app: delta-query Sent Items
    on its own cursor (``delta:sentitems``), and for each new sent item that
    matches a local thread, resolve open escalations, retire sendable
    drafts, and flip the thread to `sent`. Gated by the caller on
    ``settings.outlook_reply_sync``.

    First run (no stored deltaLink) is baseline-only: it captures the cursor
    without acting, mirroring ``reconcile_outlook_deletions`` so pre-existing
    Sent Items aren't retroactively applied. Each item is processed inside
    its own savepoint (mirrors delete-sync's per-folder transaction, scoped
    down to per-item here since one item's side effects — escalation
    resolve, draft retire, message store — are independent of the next) so
    one bad item can't derail the rest of the batch or poison the whole run.
    The cursor advances once every item in the batch has been attempted
    (success, skip, or caught error) and the whole run commits — never after
    an unhandled failure that could leave things half-applied. Returns
    per-outcome counters (e.g. ``{"applied": 2, "skipped_idempotent": 1}``).
    """
    counters: dict[str, int] = {}
    db = SessionLocal()
    try:
        state = db.get(SyncState, _REPLY_SYNC_CURSOR_KEY)
        prior_link = state.value if state else None
        try:
            items, next_link = provider.delta_sent_messages(delta_link=prior_link)
        except Exception as exc:
            logger.warning("Reply-sync: delta fetch failed: %s", exc)
            db.rollback()
            return counters

        # Baseline run (no prior cursor): capture the deltaLink only.
        if prior_link is not None:
            for item in items:
                try:
                    with db.begin_nested():
                        outcome = _apply_outlook_reply(db, provider, item)
                except Exception as exc:
                    outcome = "error"
                    logger.error(
                        "Reply-sync: unexpected error processing graph_id=%s: %s",
                        getattr(item, "graph_id", "?"), exc, exc_info=True,
                    )
                counters[outcome] = counters.get(outcome, 0) + 1

        if next_link:
            if state is None:
                db.add(SyncState(key=_REPLY_SYNC_CURSOR_KEY, value=next_link))
            else:
                state.value = next_link
                state.updated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Reply-sync: reconcile failed: %s", exc, exc_info=True)
    finally:
        db.close()
    return counters


def poll_once() -> int:
    """
    Run a single poll cycle: fetch new emails and process each one.

    T1.8: Categorization is committed per-email in one transaction.
    Draft generation runs in separate per-thread transactions AFTER
    all categorization commits are done.

    Returns the number of new emails processed.
    """
    provider = get_email_provider()
    try:
        provider.connect()
        raw_emails = provider.fetch_new_emails()
    except Exception as exc:
        logger.error("Email poll failed during fetch: %s", exc, exc_info=True)
        return 0

    # T1.13: Record a successful poll cycle now — we successfully connected and
    # fetched (even if zero new emails). This prevents false "stalled" health
    # alerts during legitimately quiet periods (nights, weekends, etc.).
    _record_successful_poll()

    # Outlook → app delete-sync: reflect mail Jane deleted/junked in Outlook
    # back into the app. Runs every cycle (independent of new-mail volume, so a
    # quiet inbox still reconciles) and is fully guarded so it can never break
    # the core poll. Gated on the flag; default off = one-way behaviour.
    if settings.email_delete_sync:
        try:
            reflected = reconcile_outlook_deletions(provider)
            if reflected:
                logger.info(
                    "Delete-sync: reflected %d Outlook deletion(s) locally", reflected
                )
        except Exception as exc:
            logger.error("Delete-sync: unexpected error: %s", exc, exc_info=True)

    processed = 0
    # Collect thread_ids that need AI draft generation (T1.8)
    threads_needing_drafts: list[uuid.UUID] = []

    if not raw_emails:
        logger.debug("No new emails found")
    else:
        logger.info("Polling: found %d new email(s)", len(raw_emails))

        # Phase 1: Categorize + commit each email individually
        for raw in raw_emails:
            db = SessionLocal()
            try:
                thread_id = process_single_email(db, raw)
                db.commit()
                # Mark as read only after successfully storing
                try:
                    provider.mark_as_read(raw.message_id)
                except Exception as exc:
                    logger.warning("Could not mark message as read: %s", exc)
                processed += 1
                if thread_id is not None:
                    threads_needing_drafts.append(thread_id)
            except Exception as exc:
                db.rollback()
                logger.error(
                    "Failed to process message_id=%s: %s", raw.message_id, exc, exc_info=True
                )
            finally:
                db.close()

    # Outlook → app reply-sync: reflect a reply Jane sent directly from
    # Outlook back into the app (resolve escalations, retire stale drafts,
    # mark the thread sent). Runs every cycle — including when there was no
    # new inbound mail this poll — same "independent of new-mail volume"
    # contract as delete-sync above, and after Phase 1 ingest so a reply-sync
    # match never races a same-cycle inbound message for this thread. Fully
    # guarded so it can never break the core poll. Gated on the flag; default
    # off = current behaviour (an Outlook-only reply is invisible to the app).
    if settings.outlook_reply_sync:
        try:
            outcomes = reconcile_outlook_replies(provider)
            if outcomes:
                logger.info("Reply-sync: %s", outcomes)
        except Exception as exc:
            logger.error("Reply-sync: unexpected error: %s", exc, exc_info=True)

    # Phase 2: Generate drafts in separate per-thread transactions (T1.8)
    # This runs AFTER all categorization commits, decoupled from the poll transaction.
    for thread_id in threads_needing_drafts:
        _generate_draft_for_thread(thread_id)

    return processed


async def start_polling_loop() -> None:
    """
    Async polling loop. Runs forever, polling every EMAIL_POLL_INTERVAL_SECONDS.
    Designed to be launched as an asyncio background task from the FastAPI lifespan.
    """
    interval = settings.email_poll_interval_seconds
    logger.info("Email polling started — interval: %ds", interval)

    # Record initial timestamp so health check doesn't immediately flag as unhealthy
    _record_successful_poll()

    while True:
        try:
            # Run the synchronous poll in the default thread pool
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(None, poll_once)
            if count:
                logger.info("Poll cycle: processed %d email(s)", count)
        except asyncio.CancelledError:
            logger.info("Email polling loop cancelled — shutting down")
            break
        except Exception as exc:
            logger.error("Unexpected error in polling loop: %s", exc, exc_info=True)

        await asyncio.sleep(interval)
