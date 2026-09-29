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

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models.email import EmailStatus, EmailThread, ThreadTier

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


def lane_clause(tier: ThreadTier) -> ColumnElement[bool]:
    """
    Return the to-do-lane visibility predicate for `tier`.

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
        return or_(
            EmailThread.status == EmailStatus.escalated,
            and_(
                EmailThread.tier == ThreadTier.t3_escalate,
                EmailThread.status.notin_(ANSWERED_STATUSES),
            ),
        )
    if tier == ThreadTier.t2_review:
        return and_(
            EmailThread.tier == ThreadTier.t2_review,
            EmailThread.status.notin_(ANSWERED_STATUSES),
        )
    return EmailThread.tier == tier


def badge_clause(tier: ThreadTier) -> ColumnElement[bool]:
    """
    `lane_clause(tier)` plus the deleted/spam exclusion the dashboard badges
    need (see `BADGE_EXCLUDED_STATUSES`) so a badge count always matches what
    the corresponding lane list shows.
    """
    return and_(lane_clause(tier), EmailThread.status.notin_(BADGE_EXCLUDED_STATUSES))
