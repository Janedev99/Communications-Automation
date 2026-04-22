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
  9. Track last_successful_poll_at + last_successful_anthropic_at (T1.13)

This module also exposes `start_polling_loop()` which is called once
from the FastAPI lifespan as a background asyncio task.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.email import EmailCategory, EmailMessage, EmailStatus, EmailThread, MessageDirection
from app.services.categorizer import get_categorizer
from app.services.email_provider import RawEmail, get_email_provider
from app.services.escalation import get_escalation_engine
from app.utils.audit import log_action

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Module-level health timestamps (T1.13) ────────────────────────────────────
# These are module-level because the polling loop runs in a background thread.
# They are read by the dashboard health endpoint (no locking needed for V1 — only
# one writer, reads are eventually consistent which is fine for a health probe).
last_successful_poll_at: datetime | None = None
last_successful_anthropic_at: datetime | None = None


def _record_successful_poll() -> None:
    global last_successful_poll_at
    last_successful_poll_at = datetime.now(timezone.utc)


def _record_successful_anthropic_call() -> None:
    global last_successful_anthropic_at
    last_successful_anthropic_at = datetime.now(timezone.utc)


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

    # Record successful Anthropic call for health tracking (T1.13)
    # Only if we reached this point without error (categorizer returns fallback on errors)
    if result.confidence > 0.0 or not result.escalation_needed:
        _record_successful_anthropic_call()

    # Update thread with categorization
    thread.category = result.category
    thread.category_confidence = result.confidence
    thread.ai_summary = result.summary
    thread.suggested_reply_tone = result.suggested_reply_tone
    thread.status = EmailStatus.categorized
    thread.updated_at = datetime.now(timezone.utc)

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

    # T1.8: Return thread_id for deferred draft generation only if appropriate
    should_generate_draft = (
        not escalation
        and settings.draft_auto_generate
        and not settings.shadow_mode  # T2.4: Shadow mode disables auto-draft
    )
    return thread.id if should_generate_draft else None


def _generate_draft_for_thread(thread_id: uuid.UUID) -> None:
    """
    Generate an AI draft for a single thread in its own DB session (T1.8).

    Errors are caught per-thread and stored as draft_generation_failed on the
    thread record so staff can see which threads need manual drafts.
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

        # Record successful Anthropic call for health tracking
        _record_successful_anthropic_call()

        logger.info(
            "Auto-generated draft %s for thread=%s",
            draft.id, thread.id,
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

    if not raw_emails:
        logger.debug("No new emails found")
        return 0

    logger.info("Polling: found %d new email(s)", len(raw_emails))
    processed = 0
    # Collect thread_ids that need AI draft generation (T1.8)
    threads_needing_drafts: list[uuid.UUID] = []

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
