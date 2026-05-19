/**
 * Splits an email body into (visible body) + (signature block).
 *
 * Adapted from the dasg-ai-comms reference implementation
 * (D:\Work\PRIME\projects\dasg-ai-comms\src\lib\email\signature-detection.ts).
 * Tweaked for jane-autocomms — particularly the disclosure-marker list, which
 * now includes patterns observed in real Schiller CPA traffic (e.g. CPA-firm
 * boilerplate, partner-name disclaimers).
 *
 * Detection signals, in priority order:
 *   1. RFC 3676 dash-dash-space delimiter: "\n-- \n"
 *   2. "Sent from my <device>" footer line
 *   3. A long unbroken line of underscores or hyphens (8+ chars)
 *   4. Legal / disclosure marker phrases (IRS Circular 230, Confidentiality
 *      Notice, etc.) — with a walk-back through contact-block lines so the
 *      full signature including the name/title/firm gets captured.
 *
 * Guards against false positives:
 *   - Sign-offs ("Best,", "Thanks,") stay with the body, not the signature
 *   - All-signature messages (forwarded body with nothing else) stay unsplit
 *   - Long prose lines (>120 chars) inside the walk-back terminate it
 */

export interface SignatureSplit {
  body: string;
  signature: string | null;
}

const RFC3676 = /(?:^|\n)-- ?\n([\s\S]+)$/;
const SENT_FROM = /\n(Sent from my [^\n]{1,80})\s*$/i;
const DIVIDER = /\n(?:_{8,}|-{8,})\n([\s\S]+)$/;

// Legal / footer marker phrases. Anchored to start-of-line via the `m` flag so
// we don't match these mid-sentence inside a regular body paragraph.
const DISCLOSURE_MARKERS: RegExp[] = [
  /^IRS Circular 230\b/im,
  /^Confidentiality Notice\b/im,
  /^CONFIDENTIALITY NOTICE\b/m,
  /^PRIVILEGED AND CONFIDENTIAL\b/im,
  /^This (?:e-?mail|message)\s.{0,80}(?:intended|confidential|privileged)/im,
  /^Get Outlook for (?:iOS|Android|Windows|Mac)\b/im,
  /^DISCLAIMER:/im,
  /^NOTICE:/im,
];

// Returns true if `line` looks like signature-block content (title, email,
// phone, URL, address, company line, short name, or blank) and not like prose.
// Used during the walk-back from a disclosure marker.
function looksLikeSignatureBlockLine(line: string): boolean {
  const t = line.trim();
  if (t === "") return true;
  // Long prose: stop the walk.
  if (t.length > 120) return false;

  // Strong signals — match anywhere in the line. Signatures often use labelled
  // formats like "Email: x@y.com" or "Direct: (555) 123-4567".
  if (/[\w.+\-]+@[\w-]+\.[\w.\-]+/.test(t)) return true; // email address
  if (/(?:\(\d{3}\)\s*\d{3}[\s.\-]?\d{4}|\d{3}[\s.\-]\d{3}[\s.\-]\d{4})/.test(t))
    return true; // US phone — (713) 527-9281 / 713-527-9281 / 713.527.9281
  if (/\+\d{1,3}[\s\-]?\d{3,}/.test(t)) return true; // international phone
  if (/(?:https?:\/\/|www\.)\S+/i.test(t)) return true; // URL
  if (/\b[\w.\-]+\.(?:com|net|org|io|co|app|dev|us|edu|gov)\b/i.test(t))
    return true; // bare domain
  if (/^\d+\s+\w/.test(t)) return true; // street address ("3131 Eastside…")
  // City/state/zip — accept BOTH 2-letter abbreviations ("TX") and full
  // state names ("Texas") because real signatures use both. Schiller's
  // own signature uses "Houston, Texas 77098" — full name.
  if (/^[A-Z][a-zA-Z .\-]+,\s*(?:[A-Z]{2}|[A-Z][a-z]+)\s+\d{5}(?:-\d{4})?/.test(t))
    return true; // "Houston, TX 77098" or "Houston, Texas 77098"
  // Any line ending in a US ZIP — catches "Suite 430, Houston TX 77098"
  // where the city/state appears mid-line.
  if (/\b\d{5}(?:-\d{4})?\s*$/.test(t)) return true;
  if (/^(?:tel|phone|mobile|cell|fax|direct|office|ext)[:.\s]/i.test(t))
    return true; // phone-label line — "Office:", "Fax:", "Direct Line:", "Ext"
  if (
    /\b(?:Director|Manager|Partner|Associate|Officer|VP|Vice President|Chief|CEO|CFO|COO|CTO|President|Founder|Owner|Head of|Senior|Principal|Lead|CPA|EA|JD|Esq\.?|Attorney|Counsel|Bookkeeper|Accountant|Advisor|Consultant|Analyst)\b/i.test(
      t,
    )
  )
    return true; // job title — includes CPA which is critical for this firm
  if (
    /\b(?:LLC|L\.L\.C\.?|Inc\.?|Corp\.?|Co\.?|Ltd\.?|LLP|PLLC|PC|Group|Partners|Associates|Capital|Advisors|Consulting|Solutions|Services|Holdings|Schoenfield|Schilmoeller)\b/.test(
      t,
    )
  )
    return true; // company suffix — includes the firm's actual names

  // Weak signal: short line with no sentence punctuation. Excludes sign-offs
  // like "Best," and "Thanks," (they have commas).
  if (t.length < 60 && !/[.?!,;:]/.test(t)) return true;

  return false;
}

// Sign-off words that mark the END of the human-written body. Used after the
// walk-back to peel the sign-off + name back off the signature start.
const SIGN_OFF_RE =
  /^(?:Best|Thanks|Thank you|Sincerely|Regards|Cheers|Kindly|Cordially|Respectfully|Warmly|Warm regards|Best regards|Kind regards|All the best|Take care|Many thanks)[,!.\s]*$/i;

export function splitEmailSignature(rawBody: string): SignatureSplit {
  if (!rawBody) return { body: "", signature: null };
  const body = rawBody.replace(/\r\n/g, "\n");

  const rfc = body.match(RFC3676);
  if (rfc) {
    const idx = body.lastIndexOf(rfc[0]);
    return {
      body: body.slice(0, idx).trimEnd(),
      signature: rfc[1].trim(),
    };
  }

  const sentFrom = body.match(SENT_FROM);
  if (sentFrom) {
    const idx = body.lastIndexOf(sentFrom[0]);
    return {
      body: body.slice(0, idx).trimEnd(),
      signature: sentFrom[1].trim(),
    };
  }

  const divider = body.match(DIVIDER);
  if (divider) {
    const idx = body.lastIndexOf(divider[0]);
    const sig = divider[1].trim();
    if (sig.split("\n").length <= 30) {
      return {
        body: body.slice(0, idx).trimEnd(),
        signature: sig,
      };
    }
  }

  // Disclosure-marker fallback — find a known footer/legal phrase, then walk
  // back through contact-block lines to capture the full signature.
  const lines = body.split("\n");
  let markerLine = -1;
  for (const pat of DISCLOSURE_MARKERS) {
    for (let i = 0; i < lines.length; i++) {
      if (pat.test(lines[i])) {
        markerLine = i;
        break;
      }
    }
    if (markerLine !== -1) break;
  }
  if (markerLine > -1) {
    let start = markerLine;
    while (start > 0 && looksLikeSignatureBlockLine(lines[start - 1])) {
      start--;
    }
    // Skip leading blanks inside the signature range.
    while (start < markerLine && lines[start].trim() === "") {
      start++;
    }
    // Refinement: if the signature starts with a single-word capitalized line
    // AND the body's last non-blank line is a sign-off marker, that single-word
    // line is the sign-off name and belongs with the body.
    if (start < lines.length) {
      const sigFirst = lines[start].trim();
      let lastBodyLine = start - 1;
      while (lastBodyLine >= 0 && lines[lastBodyLine].trim() === "") {
        lastBodyLine--;
      }
      if (
        lastBodyLine >= 0 &&
        SIGN_OFF_RE.test(lines[lastBodyLine].trim()) &&
        /^[A-Z][a-z]+$/.test(sigFirst)
      ) {
        start++;
        while (start < markerLine && lines[start].trim() === "") {
          start++;
        }
      }
    }
    // Guard: don't classify an all-signature message as having a signature
    // (that would leave an empty body).
    if (start > 0) {
      const bodyPart = lines.slice(0, start).join("\n").trimEnd();
      const sigPart = lines.slice(start).join("\n").trim();
      if (bodyPart.length > 0 && sigPart.length > 0) {
        return { body: bodyPart, signature: sigPart };
      }
    }
  }

  // Additional fallback for Schiller CPA-style signatures that have NO legal
  // disclosure marker but follow a recognisable shape — sign-off ("Thank
  // you,", "Best,") followed by a contact block. Walks back from the LAST
  // sign-off line and captures everything after it AS LONG AS the trailing
  // block parses as contact-block-shaped (no long prose).
  for (let i = lines.length - 1; i >= 0; i--) {
    if (SIGN_OFF_RE.test(lines[i].trim())) {
      // Everything after the sign-off line (skipping blanks) is a signature
      // candidate. Must be at least one contact-block line for us to bother.
      let cand = i + 1;
      while (cand < lines.length && lines[cand].trim() === "") cand++;
      if (cand >= lines.length) break;
      let allLook = true;
      for (let j = cand; j < lines.length; j++) {
        if (!looksLikeSignatureBlockLine(lines[j])) {
          allLook = false;
          break;
        }
      }
      if (allLook) {
        // Keep the sign-off WITH the body — the user wrote it.
        // Include the sign-off in the body, capture everything after as sig.
        const bodyPart = lines.slice(0, i + 1).join("\n").trimEnd();
        const sigPart = lines.slice(cand).join("\n").trim();
        if (bodyPart.length > 0 && sigPart.length > 0) {
          return { body: bodyPart, signature: sigPart };
        }
      }
      break; // first sign-off from the bottom wins; don't keep climbing
    }
  }

  return { body, signature: null };
}
