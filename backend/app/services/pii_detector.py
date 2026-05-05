"""
Sensitive-data (PII) detector for incoming email bodies.

Per Jane and Gar in the 05/02 product call: when a client emails a Social
Security Number, EIN, or attaches a tax form to plain email, the firm must
*not* let the AI auto-respond like a routine question. Instead:

  - The thread is forced into escalation with a clear reason.
  - Severity is bumped (escalation engine maps "sensitive client data" to
    medium so it surfaces alongside compliance/regulatory issues).
  - Staff manually drafts the polite "please use our secure portal" reminder
    rather than letting Claude improvise.

This detector is intentionally *conservative* — false positives (escalating
something that wasn't actually PII) are far cheaper than false negatives
(letting a Social Security number slip through to Claude). Patterns are
anchored on word boundaries and validated with light context checks where
practical.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── Patterns ──────────────────────────────────────────────────────────────────
# Each pattern is paired with a human-readable label that ends up in the
# escalation reason string. Order matters: more specific patterns first.

# US Social Security Number: NNN-NN-NNNN with explicit dashes.
# Bare 9-digit numbers are too noisy (could be invoice IDs, phone numbers
# without separators, etc.) — we detect those separately with stricter context.
_SSN_DASHED = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Bare 9-digit numbers preceded by SSN-ish context words within ~24 chars.
# Catches: "my ssn is 123456789", "social security: 123456789".
_SSN_CONTEXTUAL = re.compile(
    r"\b(?:ssn|social[\s-]*security(?:\s+(?:number|no\.?|#))?)\b[^\d\n]{0,24}(\d{9})\b",
    re.IGNORECASE,
)

# US Employer Identification Number: NN-NNNNNNN with explicit dash, or
# 9 digits preceded by EIN/TIN/FEIN context.
_EIN_DASHED = re.compile(r"\b\d{2}-\d{7}\b")
_EIN_CONTEXTUAL = re.compile(
    r"\b(?:ein|fein|federal[\s-]*tax[\s-]*id|tax[\s-]*id|tin)\b[^\d\n]{0,24}(\d{9})\b",
    re.IGNORECASE,
)

# Tax-form-like attachment cues in the body. Plain text mentions of W-2/1099
# in a phrase like "attaching my W-2" or "see attached 1099" suggest the
# client pasted or attached actual tax-form data — also worth flagging.
_TAX_FORM_ATTACH = re.compile(
    r"\b(?:attach(?:ed|ing|ment)?|see\s+attached)\b[^\n]{0,40}\b"
    r"(?:w[-\s]?2|1099|1098|k[-\s]?1|schedule\s+[a-k])\b",
    re.IGNORECASE,
)

# Credit-card-shaped 13–16 digit runs with optional spaces/dashes.
# Less common in CPA contexts but worth catching when it appears.
_CREDIT_CARD = re.compile(
    r"\b(?:\d[ -]?){12,18}\d\b",
)


@dataclass(frozen=True)
class PiiHit:
    """One detected piece of sensitive data."""
    kind: str  # short token, e.g. "ssn", "ein", "tax_form_attached"
    label: str  # human-readable, e.g. "Social Security Number"


def detect_pii(*, subject: str | None, body: str | None) -> list[PiiHit]:
    """
    Scan an email's subject + body for sensitive-data patterns.

    Returns deduplicated hits ordered by detection priority. Empty list when
    nothing matches. Detection runs against the concatenation so context
    references like "see attached W-2" in the subject still register.
    """
    text = f"{subject or ''}\n{body or ''}"
    if not text.strip():
        return []

    hits: list[PiiHit] = []
    seen: set[str] = set()

    def _add(kind: str, label: str) -> None:
        if kind not in seen:
            seen.add(kind)
            hits.append(PiiHit(kind=kind, label=label))

    if _SSN_DASHED.search(text) or _SSN_CONTEXTUAL.search(text):
        _add("ssn", "Social Security Number")

    if _EIN_DASHED.search(text) or _EIN_CONTEXTUAL.search(text):
        _add("ein", "Employer Identification / Tax ID")

    if _TAX_FORM_ATTACH.search(text):
        _add("tax_form_attached", "Tax form (W-2/1099/etc.) sent via email")

    # Credit-card check runs last and only if nothing else fired — high false
    # positive rate (long invoice numbers, account numbers).
    if not hits and _CREDIT_CARD.search(text):
        # Light Luhn-ish length sanity: collapse non-digits and check 13–19 length
        for match in _CREDIT_CARD.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if 13 <= len(digits) <= 19:
                _add("credit_card", "Card number")
                break

    return hits


def summarize_pii(hits: list[PiiHit]) -> str:
    """
    Human-readable one-line summary suitable for an escalation reason. The
    severity engine in escalation.py looks for "sensitive client data" —
    keep that phrase verbatim so the mapping stays predictable.
    """
    if not hits:
        return ""
    labels = ", ".join(h.label for h in hits)
    return f"Sensitive client data detected ({labels}) — please direct the client to the secure portal."
