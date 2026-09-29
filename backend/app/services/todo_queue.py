"""
To-do lane visibility predicate (D1: FEAT/outlook-reply-sync design doc §0/§A.6).

The "For review" (t2_review) and "Escalated" (t3_escalate) tabs are what
staff mentally model as a to-do list, but `tier` and `status` are stored
independently and neither previously excluded `sent` (answered) or `closed`
(resolved) threads — a thread stayed in its lane forever even after someone
replied to it. That mattered once Feature A could resolve an escalation and
flip a thread to `sent` from an Outlook reply alone: without also filtering
the lane, the badge and list wouldn't reflect it.

`lane_clause(tier)` is the single predicate for "is this thread in tier's
to-do lane right now" — used by both the thread list (api/emails.py) and the
dashboard badges (api/dashboard.py) so the two can never disagree. Feature B
(services.todo_queue will grow a cutoff-timestamp predicate) layers stricter
visibility on top of this without changing it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import and_, exists, func, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailMessage,
    EmailStatus,
    EmailThread,
    MessageDirection,
    ThreadTier,
)
from app.models.escalation import Escalation, EscalationStatus
from app.services import system_settings as ss

logger = logging.getLogger(__name__)

# Feature B ("Start clean"): the reset is a cutoff timestamp in
# `system_settings`, never a row mutation. `todo_cutoff_previous` holds the
# value to restore on Undo ("" = there was no cutoff before); its absence
# means there is nothing to undo. Neither key is PATCH-able (see
# api/system_settings._PATCHABLE_KEYS) — they are only written by the
# dedicated /system-settings/todo-reset endpoints.
CUTOFF_KEY = "todo_cutoff_at"
CUTOFF_PREVIOUS_KEY = "todo_cutoff_previous"

# A thread in this status no longer needs action from a to-do lane's point of
# view: `sent` means someone (staff, auto-send, or an Outlook reply — see
# services/email_intake._apply_outlook_reply) answered it; `closed` means
# staff explicitly wrapped it up.
ANSWERED_STATUSES = (EmailStatus.sent, EmailStatus.closed)

# Trash-management terminal states. The thread list's default filter already
# excludes these (api/emails.py:list_threads), but the dashboard badge counts
# don't go through that filter, so it excludes them explicitly to stay in
# sync with what the list actually shows.
BADGE_EXCLUDED_STATUSES = (EmailStatus.deleted, EmailStatus.spam)


def parse_cutoff(raw: str | None) -> datetime | None:
    """Parse a stored cutoff into an aware-UTC datetime; blank/garbage = None.

    A naive stored value is taken as UTC (R-B4). An unparseable value is
    logged and treated as "no cutoff" — failing open shows more work, never
    silently hides it.
    """
    if raw is None or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        logger.warning("todo_queue: ignoring unparseable cutoff %r", raw)
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_cutoff(db: Session) -> datetime | None:
    """The active "Start clean" cutoff (aware UTC), or None when unset."""
    return parse_cutoff(ss.get_setting(db, CUTOFF_KEY))


def visible_clause(cutoff: datetime | None) -> ColumnElement[bool]:
    """
    B.2 — is this thread on the to-do surfaces given `cutoff`?

    Visible iff the thread was created, received an INBOUND message, or was
    escalated at/after the cutoff. Deliberately not keyed on `updated_at`,
    which unrelated actions (assign, save, categorize...) bump. `None` = no
    reset = everything is visible.
    """
    if cutoff is None:
        return true()
    new_inbound = exists().where(
        EmailMessage.thread_id == EmailThread.id,
        EmailMessage.direction == MessageDirection.inbound,
        EmailMessage.received_at >= cutoff,
    )
    new_escalation = exists().where(
        Escalation.thread_id == EmailThread.id,
        Escalation.created_at >= cutoff,
    )
    return or_(EmailThread.created_at >= cutoff, new_inbound, new_escalation)


def _thread_visible_for(thread_id_col, cutoff: datetime) -> ColumnElement[bool]:
    return thread_id_col.in_(select(EmailThread.id).where(visible_clause(cutoff)))


def escalation_visible_clause(cutoff: datetime | None) -> ColumnElement[bool]:
    """Escalation rows: created at/after the cutoff, or on a visible thread."""
    if cutoff is None:
        return true()
    return or_(
        Escalation.created_at >= cutoff,
        _thread_visible_for(Escalation.thread_id, cutoff),
    )


def draft_visible_clause(cutoff: datetime | None) -> ColumnElement[bool]:
    """Drafts follow the same rule as escalations."""
    if cutoff is None:
        return true()
    return or_(
        DraftResponse.created_at >= cutoff,
        _thread_visible_for(DraftResponse.thread_id, cutoff),
    )


def lane_clause(
    tier: ThreadTier, cutoff: datetime | None = None
) -> ColumnElement[bool]:
    """
    Return the to-do-lane visibility predicate for `tier`, restricted to
    threads visible under `cutoff` (Feature B; None = no reset).

    t3_escalate: `status == escalated` (kept unconditionally — a status-only
    escalation that drifted from tier, e.g. a bulk re-categorize, must never
    silently disappear from the tab) OR (`tier == t3_escalate` AND not
    answered/closed).

    t2_review: `tier == t2_review` AND not answered/closed.

    Any other tier (t1_auto): no to-do-lane concept applies — it never
    reaches a human queue — so this falls back to a plain tier match, kept
    only so callers that iterate all tiers uniformly don't need a special
    case.
    """
    if tier == ThreadTier.t3_escalate:
        base: ColumnElement[bool] = or_(
            EmailThread.status == EmailStatus.escalated,
            and_(
                EmailThread.tier == ThreadTier.t3_escalate,
                EmailThread.status.notin_(ANSWERED_STATUSES),
            ),
        )
    elif tier == ThreadTier.t2_review:
        base = and_(
            EmailThread.tier == ThreadTier.t2_review,
            EmailThread.status.notin_(ANSWERED_STATUSES),
        )
    else:
        # t1_auto is never a to-do lane, so the reset does not apply to it.
        return EmailThread.tier == tier
    return and_(base, visible_clause(cutoff))


def badge_clause(
    tier: ThreadTier, cutoff: datetime | None = None
) -> ColumnElement[bool]:
    """
    `lane_clause(tier, cutoff)` plus the deleted/spam exclusion the dashboard
    badges need (see `BADGE_EXCLUDED_STATUSES`) so a badge count always
    matches what the corresponding lane list shows.
    """
    return and_(
        lane_clause(tier, cutoff),
        EmailThread.status.notin_(BADGE_EXCLUDED_STATUSES),
    )


_OPEN_ESCALATION_STATUSES = (EscalationStatus.pending, EscalationStatus.acknowledged)


@dataclass(frozen=True)
class TodoCounts:
    """Every to-do number the dashboard/sidebar shows, from one predicate set."""

    t2_review: int
    t3_escalate: int
    # status == pending only (sidebar dot / "Open Escalations" card)
    pending_escalations: int
    # pending + acknowledged — what the Escalations page's active view lists
    active_escalations: int
    # unresolved escalations by severity (High/critical badge)
    escalations_by_severity: dict[str, int] = field(default_factory=dict)
    drafts_pending_review: int = 0


def todo_counts(db: Session, cutoff: datetime | None = None) -> TodoCounts:
    """
    Single source for the to-do badges (R-B2): the lane counts use
    `badge_clause` (the list's predicate plus deleted/spam), escalation and
    draft counts use their own visibility clauses under the same cutoff.
    """
    lanes = db.execute(
        select(
            func.count(EmailThread.id).filter(
                badge_clause(ThreadTier.t2_review, cutoff)
            ),
            func.count(EmailThread.id).filter(
                badge_clause(ThreadTier.t3_escalate, cutoff)
            ),
        )
    ).one()

    esc_visible = escalation_visible_clause(cutoff)
    pending, active = db.execute(
        select(
            func.count(Escalation.id).filter(
                Escalation.status == EscalationStatus.pending
            ),
            func.count(Escalation.id).filter(
                Escalation.status.in_(_OPEN_ESCALATION_STATUSES)
            ),
        ).where(esc_visible)
    ).one()

    severity_rows = db.execute(
        select(Escalation.severity, func.count(Escalation.id))
        .where(Escalation.status != EscalationStatus.resolved, esc_visible)
        .group_by(Escalation.severity)
    ).all()

    drafts = db.execute(
        select(func.count(DraftResponse.id)).where(
            DraftResponse.status.in_([DraftStatus.pending, DraftStatus.edited]),
            draft_visible_clause(cutoff),
        )
    ).scalar_one()

    return TodoCounts(
        t2_review=lanes[0],
        t3_escalate=lanes[1],
        pending_escalations=pending,
        active_escalations=active,
        escalations_by_severity={sev.value: n for sev, n in severity_rows},
        drafts_pending_review=drafts,
    )
