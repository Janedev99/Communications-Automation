"""
T1 auto-send — sends an AI-generated draft for a Tier-1 thread without staff
review, gated by both `system_settings.auto_send_enabled` (DB flag) and
`config.shadow_mode` (env flag).

Called from the deferred draft-generation phase in email_intake. Each call:
  1. Re-reads the gates (per-call freshness; admin can pause anytime).
  2. Confirms the thread is still T1 and has a fresh, pending draft.
  3. Refuses to proceed if there are zero inbound messages on the thread —
     auto-replies must reference an inbound message (RFC threading + audit).
  4. Marks the draft approved (system reviewer).
  5. Calls the email provider to send.
  6. On success: marks draft+thread sent, records `thread.auto_sent_at`,
     audit-logs `thread.auto_sent`, fires `notify_auto_sent` for the high-
     visibility log channel. The success state is committed inside this
     function so a downstream rollback cannot un-record an email that
     actually left the system.
  7. On failure: rolls back the optimistic outbound message + draft state,
     persists `send_failed` in a clean transaction, audit-logs
     `thread.auto_send_failed`, fires `notify_auto_send_failed`.

Failures are non-fatal — they leave the draft in staff's queue with the
`send_failed` status so it shows up in the failure indicator on the inbox.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.services import system_settings as ss
from app.services.email_provider import get_email_provider
from app.services.notification import get_notification_service
from app.utils.audit import log_action

logger = logging.getLogger(__name__)


def is_auto_send_enabled(db: Session) -> tuple[bool, str | None]:
    """Return (enabled, reason_if_disabled). Public for integrations endpoint."""
    settings = get_settings()
    if settings.shadow_mode:
        return False, "shadow_mode env flag is on"
    if not ss.get_bool(db, ss.AUTO_SEND_ENABLED, default=False):
        return False, "auto_send_enabled DB flag is off"
    return True, None


def maybe_auto_send(db: Session, *, thread_id: uuid.UUID, draft_id: uuid.UUID) -> bool:
    """
    Try to auto-send the draft if the thread qualifies.

    Returns True if an auto-send attempt was made (success OR a recorded failure).
    Returns False if auto-send was skipped (gates off, wrong tier, missing inbound, etc.).

    The function manages its own commits so the persisted state always matches
    reality — even if the caller later rolls back. Callers should not commit
    based on this function's return value.

    Never raises — every error path either commits a `send_failed` audit record
    or returns False.
    """
    enabled, why = is_auto_send_enabled(db)
    if not enabled:
        logger.debug("auto_send: skipped — %s (thread=%s)", why, thread_id)
        return False

    thread = db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    ).scalar_one_or_none()
    if thread is None:
        logger.warning("auto_send: thread %s not found", thread_id)
        return False

    if thread.tier != ThreadTier.t1_auto:
        logger.debug(
            "auto_send: thread %s is tier=%s, not t1_auto — skipping",
            thread_id, thread.tier,
        )
        return False

    if thread.auto_sent_at is not None:
        # Already auto-sent (or attempted) — never retry from here. Staff can.
        return False

    draft = db.execute(
        select(DraftResponse).where(DraftResponse.id == draft_id)
    ).scalar_one_or_none()
    if draft is None or draft.status != DraftStatus.pending:
        logger.debug(
            "auto_send: draft %s not pending (status=%s) — skipping",
            draft_id, draft.status if draft else "missing",
        )
        return False

    # ── Defensive: refuse to send a context-free reply ────────────────────────
    inbound_messages = db.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == MessageDirection.inbound,
        ).order_by(EmailMessage.received_at.desc())
    ).scalars().all()

    if not inbound_messages:
        logger.error(
            "auto_send: thread %s has zero inbound messages — refusing to auto-send",
            thread_id,
        )
        return False

    # ── Build outbound headers ────────────────────────────────────────────────
    latest_inbound = inbound_messages[0]
    reply_to_message_id = latest_inbound.message_id_header
    parent_refs = (latest_inbound.raw_headers or {}).get("References", "")
    references_header = (
        f"{parent_refs} {reply_to_message_id}"
        if parent_refs else reply_to_message_id
    )

    reply_subject = thread.subject or "(no subject)"
    if reply_subject and not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    settings = get_settings()
    from_address = settings.msgraph_mailbox or settings.firm_owner_email
    firm_domain = from_address.split("@")[-1] if "@" in from_address else "localhost"
    outbound_message_id = f"<auto-{draft.id}@{firm_domain}>"

    # ── Mark approved + persist outbound message record (optimistic) ──────────
    draft.status = DraftStatus.approved
    draft.reviewed_by_id = None  # System
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.send_idempotency_key = draft.send_idempotency_key or secrets.token_hex(32)
    draft.send_attempts = (draft.send_attempts or 0) + 1

    outbound_msg = EmailMessage(
        thread_id=thread.id,
        message_id_header=outbound_message_id,
        sender=f"{settings.firm_name} <{from_address}>",
        recipient=thread.client_email,
        body_text=draft.body_text,
        received_at=datetime.now(timezone.utc),
        direction=MessageDirection.outbound,
        is_processed=True,
    )
    db.add(outbound_msg)
    db.flush()

    # Capture identifiers BEFORE the provider call so we can re-use them after
    # a rollback wipes the optimistic state.
    captured_recipient = thread.client_email
    captured_subject = reply_subject
    captured_category = thread.category.value
    captured_confidence = thread.category_confidence

    # ── Call provider ─────────────────────────────────────────────────────────
    provider = get_email_provider()
    try:
        provider.connect()
        actual_message_id = provider.send_email(
            to=thread.client_email,
            subject=reply_subject,
            body_text=draft.body_text,
            reply_to_message_id=reply_to_message_id,
            references_header=references_header,
            message_id=outbound_message_id,
        )
        # Defensive contract check — provider promises a non-empty Message-ID.
        # A None/empty return must NOT be treated as success.
        if not actual_message_id:
            raise RuntimeError(
                "email provider returned empty Message-ID; cannot confirm delivery"
            )
        if actual_message_id != outbound_message_id:
            outbound_msg.message_id_header = actual_message_id

    except Exception as exc:
        # ── Failure path — mirror api/drafts.py:send_draft rollback pattern ──
        logger.error(
            "auto_send: provider failed thread=%s draft=%s — %s",
            thread.id, draft.id, exc, exc_info=True,
        )
        db.rollback()

        # Re-fetch in clean transaction and persist send_failed + audit row
        try:
            fail_draft = db.execute(
                select(DraftResponse).where(DraftResponse.id == draft_id)
            ).scalar_one_or_none()
            fail_thread = db.execute(
                select(EmailThread).where(EmailThread.id == thread_id)
            ).scalar_one_or_none()
            if fail_draft is not None:
                fail_draft.status = DraftStatus.send_failed
                # Preserve any send_attempts increment for retry tracing
                fail_draft.send_attempts = (fail_draft.send_attempts or 0) + 1
            if fail_thread is not None:
                fail_thread.status = EmailStatus.draft_ready
                fail_thread.updated_at = datetime.now(timezone.utc)

            log_action(
                db,
                action="thread.auto_send_failed",
                entity_type="email_thread",
                entity_id=str(thread_id),
                details={
                    "draft_id": str(draft_id),
                    "error": str(exc)[:500],
                    "recipient": captured_recipient,
                },
            )
            db.commit()
        except Exception as inner:
            logger.error(
                "auto_send: could not persist send_failed for thread=%s draft=%s: %s",
                thread_id, draft_id, inner,
            )
            db.rollback()

        # Fire high-visibility notification (best-effort — never raises)
        try:
            get_notification_service().notify_auto_send_failed(
                thread_id=str(thread_id),
                draft_id=str(draft_id),
                client_email=captured_recipient,
                error=str(exc)[:500],
            )
        except Exception as note_exc:
            logger.error("auto_send: notify_auto_send_failed raised: %s", note_exc)

        return True  # we tried; failure is recorded

    # ── Success path — commit immediately ─────────────────────────────────────
    draft.status = DraftStatus.sent
    thread.status = EmailStatus.sent
    thread.updated_at = datetime.now(timezone.utc)
    thread.auto_sent_at = datetime.now(timezone.utc)

    log_action(
        db,
        action="thread.auto_sent",
        entity_type="email_thread",
        entity_id=str(thread.id),
        details={
            "draft_id": str(draft.id),
            "tier": thread.tier.value,
            "category": captured_category,
            "confidence": captured_confidence,
            "recipient": captured_recipient,
            "subject": captured_subject,
        },
    )

    try:
        db.commit()
    except Exception as commit_exc:
        # An email actually left the system but DB couldn't persist the success.
        # Loud failure — at least the email is in the audit log via notification.
        logger.error(
            "auto_send: DB commit failed AFTER provider sent email thread=%s — %s",
            thread.id, commit_exc, exc_info=True,
        )
        db.rollback()

    # Fire high-visibility notification (best-effort)
    try:
        get_notification_service().notify_auto_sent(
            thread_id=str(thread_id),
            draft_id=str(draft_id),
            client_email=captured_recipient,
            subject=captured_subject,
            category=captured_category,
            confidence=captured_confidence,
        )
    except Exception as note_exc:
        logger.error("auto_send: notify_auto_sent raised: %s", note_exc)

    logger.info(
        "auto_send: SUCCESS thread=%s draft=%s recipient=%s",
        thread.id, draft.id, captured_recipient,
    )
    return True
