"""
Shared recipient parsing / validation utilities.

Used by:
  - compose_email (api/emails.py) — parses To/Cc form fields
  - forward_message (api/emails.py) — parses To/Cc form fields
  - update_draft (api/emails.py) — validates PUT draft recipient edits
  - get_reply_all_recipients (api/drafts.py) — computes the reply-all set

Pure functions only (no FastAPI imports) so the module is trivially unit
testable — validation errors surface as InvalidRecipient (a ValueError
subclass) and callers map that to HTTP 422 at the router layer.
"""
from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Hard ceiling on To + Cc combined across every recipient-accepting endpoint
# (compose, forward, draft PUT, reply-all). Prevents an accidental
# reply-all-to-a-huge-list mistake from becoming an unbounded send.
MAX_RECIPIENTS = 50


class InvalidRecipient(ValueError):
    """Raised when a recipient string/list contains a malformed address, an
    empty required field, or exceeds MAX_RECIPIENTS."""


def parse_recipient_list(raw: str | None) -> list[str]:
    """
    Split a comma/semicolon-separated recipient string into validated,
    de-duplicated addresses (case-insensitive de-dupe, order preserved).

    Raises InvalidRecipient on any malformed address. Returns [] for empty
    or None input — callers decide whether an empty result is acceptable
    (e.g. Cc is optional, To is usually not).
    """
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[;,]", raw):
        addr = part.strip()
        if not addr:
            continue
        if not EMAIL_RE.match(addr):
            raise InvalidRecipient(f"Invalid email address: {addr!r}")
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            out.append(addr)
    return out


def parse_recipient_items(items: list[str] | None) -> list[str]:
    """
    Validate a list of already-split recipient strings (e.g. from a JSON
    request body) element-wise, applying the same regex + de-dupe rules as
    parse_recipient_list. Implemented by re-joining and re-splitting so both
    entry points share one validation path.
    """
    if not items:
        return []
    return parse_recipient_list(",".join(items))


def enforce_recipient_cap(to: list[str], cc: list[str]) -> None:
    """Raise InvalidRecipient if To + Cc together exceed MAX_RECIPIENTS."""
    total = len(to) + len(cc)
    if total > MAX_RECIPIENTS:
        raise InvalidRecipient(
            f"Too many recipients ({total}); the limit is {MAX_RECIPIENTS} "
            "across To and Cc combined."
        )


def own_addresses(settings) -> set[str]:
    """
    Return the set of email addresses that belong to the firm's own mailbox
    (lowercased, empties dropped). Used to exclude ourselves from a computed
    reply-all recipient set — replying to a thread should never re-add the
    firm's own mailbox as a To/Cc target.
    """
    candidates = [
        settings.msgraph_mailbox,
        settings.imap_username,
        settings.smtp_username,
        settings.firm_owner_email,
    ]
    return {addr.strip().lower() for addr in candidates if addr and addr.strip()}


def compute_reply_all(latest_inbound_message, settings) -> tuple[list[str], list[str]]:
    """
    Compute the reply-all recipient set from the latest inbound message.

    to = [sender] + (inbound.to_recipients - self - sender)
    cc = inbound.cc_recipients - self - to

    NULL inbound to_recipients/cc_recipients (legacy rows polled before this
    field existed) degrade to ([sender], []) — the same default a plain reply
    has always used. Case-insensitive de-dupe against self + sender + each
    other; order preserved (sender first, then original To order, then
    original Cc order).

    Raises InvalidRecipient if the combined result exceeds MAX_RECIPIENTS.
    """
    from app.services.email_intake import _extract_sender_parts

    _, sender_email = _extract_sender_parts(latest_inbound_message.sender or "")
    sender_email = sender_email.strip()
    self_addrs = own_addresses(settings)

    to_list: list[str] = []
    seen_to: set[str] = set()
    if sender_email and sender_email.lower() not in self_addrs:
        to_list.append(sender_email)
        seen_to.add(sender_email.lower())

    for addr in latest_inbound_message.to_recipients or []:
        addr = (addr or "").strip()
        if not addr:
            continue
        key = addr.lower()
        if key in self_addrs or key in seen_to:
            continue
        seen_to.add(key)
        to_list.append(addr)

    cc_list: list[str] = []
    seen_cc: set[str] = set()
    for addr in latest_inbound_message.cc_recipients or []:
        addr = (addr or "").strip()
        if not addr:
            continue
        key = addr.lower()
        if key in self_addrs or key in seen_to or key in seen_cc:
            continue
        seen_cc.add(key)
        cc_list.append(addr)

    enforce_recipient_cap(to_list, cc_list)
    return to_list, cc_list
