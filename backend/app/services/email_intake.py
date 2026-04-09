"""
Email intake service.

Responsibilities:
  1. Poll the configured email provider for new messages
  2. Deduplicate by message_id_header (unique constraint in DB)
  3. Group messages into threads (by In-Reply-To/References or provider thread ID)
  4. Store EmailThread + EmailMessage records
  5. Trigger categorization for each new inbound message
  6. Trigger escalation check on categorization result

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


def process_single_email(db: Session, raw: RawEmail) -> None:
    """
    Process one raw email: store it, categorize, check escalation.
    Called from both the polling loop and tests.
    """
    thread = _find_or_create_thread(db, raw)
    message = _store_message(db, thread, raw)

    if message is None:
        return  # Already processed

    # Categorize
    categorizer = get_categorizer()
    body = raw.body_text or raw.body_html or ""
    result = categorizer.categorize(
        sender=raw.sender,
        subject=raw.subject,
        body=body,
    )

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

    # Auto-generate AI draft if not escalated and auto-generation is enabled.
    # Escalated threads go to Jane — no auto-draft. Staff can manually trigger
    # draft generation after Jane has reviewed an escalated thread.
    # Failure here is non-fatal: the email is already categorized and stored.
    if not escalation and settings.draft_auto_generate:
        try:
            from app.services.draft_generator import get_draft_generator
            generator = get_draft_generator()
            draft = generator.generate(db, thread)
            logger.info(
                "Auto-generated draft %s for thread=%s",
                draft.id, thread.id,
            )
        except Exception as exc:
            logger.error(
                "Draft generation failed for thread %s (non-fatal): %s",
                thread.id, exc, exc_info=True,
            )
            # Thread remains in 'categorized' state; staff can trigger manually

    logger.info(
        "Processed email: thread=%s message=%s category=%s escalated=%s",
        thread.id, message.id, result.category, result.escalation_needed,
    )


def poll_once() -> int:
    """
    Run a single poll cycle: fetch new emails and process each one.
    Returns the number of new emails processed.
    """
    provider = get_email_provider()
    try:
        provider.connect()
        raw_emails = provider.fetch_new_emails()
    except Exception as exc:
        logger.error("Email poll failed during fetch: %s", exc, exc_info=True)
        return 0

    if not raw_emails:
        logger.debug("No new emails found")
        return 0

    logger.info("Polling: found %d new email(s)", len(raw_emails))
    processed = 0

    for raw in raw_emails:
        db = SessionLocal()
        try:
            process_single_email(db, raw)
            db.commit()
            # Mark as read only after successfully storing
            try:
                provider.mark_as_read(raw.message_id)
            except Exception as exc:
                logger.warning("Could not mark message as read: %s", exc)
            processed += 1
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed to process message_id=%s: %s", raw.message_id, exc, exc_info=True
            )
        finally:
            db.close()

    return processed


async def start_polling_loop() -> None:
    """
    Async polling loop. Runs forever, polling every EMAIL_POLL_INTERVAL_SECONDS.
    Designed to be launched as an asyncio background task from the FastAPI lifespan.
    """
    interval = settings.email_poll_interval_seconds
    logger.info("Email polling started — interval: %ds", interval)

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
