"""
Read every inbound EmailMessage with body_text and characterize the
signature / quoted-history shapes the corpus actually contains.

Output: a report that tells us:
  - How many messages have an obvious sign-off ("Thank you,", "Best,"...)
  - How many have a "Sent from my <device>" footer
  - How many have an Outlook "**From:**" reply header
  - How many have ">" prefix quotes (Apple/iOS style)
  - How many have a Gmail "On <date>, ... wrote:" intro
  - How many have legal disclosure markers
  - What patterns appear that aren't covered by the current detector
    (uncategorized "trailing block" — short lines after a sign-off that
    look signature-shaped but the firm doesn't appear in the corpus
    vocabulary yet)
  - The top 20 "last block" lines (likely-signature content) so we can
    eyeball what the corpus calls a signature

Run from backend/ as:
  python scripts/analyze_email_corpus.py
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

# Mirror the recategorize script's env override pattern — but for analysis
# we just need DB access, not LLM.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import SessionLocal
from app.models.email import EmailMessage, MessageDirection


# Patterns roughly mirroring the JS detectors (signature-detection.ts + the
# message-body quote-boundary detector) so we can simulate their decisions
# from Python without spinning up a JS runtime.

SIGN_OFF_RE = re.compile(
    r"^(?:Best|Thanks|Thank you|Sincerely|Regards|Cheers|Kindly|Cordially|"
    r"Respectfully|Warmly|Warm regards|Best regards|Kind regards|"
    r"All the best|Take care|Many thanks)[,!.\s]*$",
    re.IGNORECASE,
)

RFC3676 = re.compile(r"(?:^|\n)-- ?\n([\s\S]+)$")
# Mirror the TS SENT_FROM (Sent from my | with | by)
SENT_FROM = re.compile(
    r"\n(Sent (?:from my|with|by) [^\n]{1,80})\s*$",
    re.IGNORECASE,
)
DIVIDER = re.compile(r"\n(?:_{8,}|-{8,})\n([\s\S]+)$")

# Strong signature signals — at least one must be present in the trailing
# block for the sign-off fallback to fire.
_STRONG_PATTERNS = [
    re.compile(r"[\w.+\-]+@[\w-]+\.[\w.\-]+"),  # email
    re.compile(r"\(\d{3}\)\s*\d{3}[\s.\-]?\d{4}|\d{3}[\s.\-]\d{3}[\s.\-]\d{4}"),
    re.compile(r"\+\d{1,3}[\s\-]?\d{3,}"),
    re.compile(r"https?://|www\.", re.IGNORECASE),
    re.compile(r"^\d+\s+\w"),  # street address
    re.compile(r"\b\d{5}(?:-\d{4})?\s*$"),  # ZIP-trailing
    re.compile(r"^(?:tel|phone|mobile|cell|fax|direct|office|ext)[:.\s]", re.IGNORECASE),
    re.compile(
        r"\b(?:CPA|EA|JD|Esq\.?|Director|Manager|Partner|Associate|Officer|"
        r"VP|Vice President|Chief|CEO|CFO|COO|CTO|President|Founder|Owner|"
        r"Head of|Senior|Principal|Lead|Attorney|Counsel|Accountant|Advisor|"
        r"Consultant|Analyst)\b"
    ),
    re.compile(
        r"\b(?:LLC|L\.L\.C\.?|Inc\.?|Corp\.?|Ltd\.?|LLP|PLLC|PC|Group|Partners|"
        r"Associates|Capital|Advisors|Consulting|Solutions|Holdings|"
        r"Schoenfield|Schilmoeller)\b"
    ),
]


def has_strong_signature_signal(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    return any(p.search(t) for p in _STRONG_PATTERNS)

DISCLOSURE_MARKERS = [
    re.compile(r"^IRS Circular 230\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Confidentiality Notice\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^CONFIDENTIALITY NOTICE\b", re.MULTILINE),
    re.compile(r"^PRIVILEGED AND CONFIDENTIAL\b", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"^This (?:e-?mail|message)\s.{0,80}(?:intended|confidential|privileged)",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"^Get Outlook for (?:iOS|Android|Windows|Mac)\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^DISCLAIMER:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^NOTICE:", re.IGNORECASE | re.MULTILINE),
]

# Quote-boundary patterns from findQuoteBoundary in message-body.tsx
GT_PREFIX_RE = re.compile(r"^\s*> ")
OUTLOOK_FROM_RE = re.compile(r"^\s*\*\*From:")
GMAIL_INTRO_RE = re.compile(r"^On .+, .+ wrote:\s*$")
# Bare Gmail/Proton intro that isn't followed by ">" prefix quoting.
# Recognised as a standalone quote boundary in the updated detector.


def find_quote_boundary(lines: list[str]) -> int:
    """Returns line index where quoted history starts (or len(lines))."""
    for i, line in enumerate(lines):
        trimmed = line.lstrip()
        if trimmed.startswith("> ") or trimmed == ">":
            start = i
            while start > 0 and GMAIL_INTRO_RE.match(lines[start - 1].rstrip()):
                start -= 1
            while start > 0 and lines[start - 1].strip() == "":
                start -= 1
            return start
        if trimmed.startswith("**From:**") or trimmed.startswith("From: "):
            start = i
            while start > 0 and lines[start - 1].strip() == "":
                start -= 1
            return start
        # Standalone Gmail-style intro (no following ">" lines, e.g. Proton)
        if GMAIL_INTRO_RE.match(line.rstrip()) and i < len(lines) - 1:
            start = i
            while start > 0 and lines[start - 1].strip() == "":
                start -= 1
            return start
    return len(lines)


def classify_message(body_text: str) -> dict:
    """Run all the heuristics and return a dict describing the outcome."""
    text = body_text.replace("\r\n", "\n")
    lines = text.split("\n")
    flags = {
        "has_signoff_anywhere": False,
        "has_rfc3676": bool(RFC3676.search(text)),
        "has_sent_from": bool(SENT_FROM.search(text)),
        "has_divider": bool(DIVIDER.search(text)),
        "has_disclosure": any(pat.search(text) for pat in DISCLOSURE_MARKERS),
        "has_gt_quote": any(GT_PREFIX_RE.match(ln) for ln in lines),
        "has_outlook_from": any(OUTLOOK_FROM_RE.match(ln) for ln in lines),
        "has_gmail_intro": any(GMAIL_INTRO_RE.match(ln.rstrip()) for ln in lines),
    }

    boundary = find_quote_boundary(lines)
    pre_quote = lines[:boundary]
    flags["has_signoff_in_pre_quote"] = any(
        SIGN_OFF_RE.match(ln.strip()) for ln in pre_quote
    )
    flags["has_signoff_anywhere"] = any(
        SIGN_OFF_RE.match(ln.strip()) for ln in lines
    )

    # Heuristic: a sig-shaped block exists if there's a sign-off in pre_quote
    # AND ≥3 non-empty lines after it.
    # Mirror the tightened TS fallback: walk back from LAST sign-off; require
    # ≥1 strong signal in the trailing block; otherwise treat as "no sig".
    sig_block_size = 0
    sig_has_strong = False
    sig_block_start = None
    if flags["has_signoff_in_pre_quote"]:
        for i in range(len(pre_quote) - 1, -1, -1):
            if SIGN_OFF_RE.match(pre_quote[i].strip()):
                sig_block_start = i + 1
                while sig_block_start < len(pre_quote) and pre_quote[sig_block_start].strip() == "":
                    sig_block_start += 1
                trailing = pre_quote[sig_block_start:]
                sig_block_size = sum(1 for ln in trailing if ln.strip())
                sig_has_strong = any(has_strong_signature_signal(ln) for ln in trailing)
                break
    flags["sig_block_lines"] = sig_block_size
    flags["sig_has_strong_signal"] = sig_has_strong
    flags["sig_would_fire"] = sig_has_strong and sig_block_size >= 1

    # Capture last 5 non-blank lines of pre_quote as a representative
    # "trailing block" sample for eyeballing.
    trailing = [ln for ln in pre_quote if ln.strip()][-8:]
    flags["trailing_lines"] = trailing

    return flags


def main() -> int:
    db = SessionLocal()
    try:
        msgs = db.execute(
            select(EmailMessage).where(
                EmailMessage.direction == MessageDirection.inbound,
                EmailMessage.body_text.isnot(None),
            )
        ).scalars().all()
        print(f"Inbound messages with body_text: {len(msgs)}\n")

        counts: Counter[str] = Counter()
        sig_block_distribution: Counter[int] = Counter()
        edge_cases: list[tuple[str, str, dict]] = []
        trailing_line_corpus: Counter[str] = Counter()

        for m in msgs:
            f = classify_message(m.body_text or "")
            for k, v in f.items():
                if isinstance(v, bool) and v:
                    counts[k] += 1
            sig_block_distribution[f["sig_block_lines"]] += 1

            # Edge case: has a sig-shaped block but NO disclosure marker —
            # i.e. relies on our new sign-off fallback. Worth listing so we
            # can see what patterns the fallback handles.
            if (
                f["sig_block_lines"] >= 3
                and not f["has_disclosure"]
                and not f["has_rfc3676"]
                and not f["has_sent_from"]
                and not f["has_divider"]
            ):
                edge_cases.append((str(m.id), m.sender or "", f))

            for ln in f["trailing_lines"]:
                trailing_line_corpus[ln.strip()] += 1

        print("=== Detector signal frequency ===")
        for k, v in counts.most_common():
            print(f"  {v:4d}/{len(msgs):<4d} ({100*v/len(msgs):.0f}%)  {k}")

        print("\n=== Trailing-block size distribution (lines after sign-off) ===")
        for sz, n in sorted(sig_block_distribution.items()):
            bar = "#" * n
            print(f"  {sz:3d} lines : {n:3d}  {bar}")

        print(f"\n=== Sign-off-only fallback cases (no formal markers): {len(edge_cases)} ===")
        for mid, sender, f in edge_cases[:10]:
            print(f"\n  msg={mid}  sender={sender[:50]}")
            print(f"    sig_block_lines={f['sig_block_lines']}")
            for ln in f["trailing_lines"]:
                # ASCII-safe for Windows console
                print(f"    | {ascii(ln)[1:-1][:120]}")

        print("\n=== Top 30 repeating trailing lines (likely signature components) ===")
        for ln, n in trailing_line_corpus.most_common(30):
            if n < 2:
                break
            print(f"  {n:3d}x  {ascii(ln)[1:-1][:100]}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
