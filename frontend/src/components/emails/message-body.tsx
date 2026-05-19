"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { splitEmailSignature } from "@/lib/email/signature-detection";

// Long-signature threshold (lines). At or below this, render inline + muted.
// Above this, hide behind a "Show signature" toggle so signatures don't
// dominate the bubble visually — matches the dasg-ai-comms behavior.
const SIGNATURE_LONG_THRESHOLD_LINES = 5;

/**
 * Rich body renderer for email messages.
 *
 * Two upgrades over raw <whitespace-pre-wrap> text:
 *
 *   1. Paragraphs: splits on \n\n+, renders each as a <p> with controlled
 *      vertical spacing. Inbox-style — tight signature blocks (single \n
 *      between lines stack contiguously), real paragraph breaks get
 *      visible spacing.
 *
 *   2. Quote folding: detects the boundary where the current message ends
 *      and the quoted reply chain begins. Quoted content is collapsed by
 *      default behind a "Show quoted history" toggle (one click to expand).
 *      Handles three patterns seen in real Schiller CPA mail:
 *        - Apple Mail / iOS: `> ` prefix lines
 *        - Outlook reply header: `**From:** ... **Sent:** ... **Subject:**`
 *        - Gmail intro: "On <date>, <person> wrote:"
 *
 * Nested quotes (`>> `, `>>> `) are preserved as-is inside the collapsed
 * block — going deeper than one level is rare and not worth the UI cost.
 */

// Gmail / Apple Mail style intro that precedes quoted content. Examples:
//   "On May 19, 2026, at 7:34 AM, Jane Schilmoeller <jane@x> wrote:"
//   "On Friday, May 1st, 2026 at 3:36 PM, Doug Conquest <doug@x> wrote:"
const GMAIL_INTRO_RE = /^On .+, .+ wrote:\s*$/;

/**
 * Find the index in `lines` where quoted content starts. Returns lines.length
 * if no quote boundary is detected (meaning the whole message is "current").
 *
 * Detects three patterns observed in the real corpus:
 *   - Apple Mail / iOS: lines beginning with "> " (or "> > " for nested)
 *   - Outlook reply header: "**From:** ... **Sent:** ... **Subject:**"
 *   - Gmail / Proton standalone intro: "On <date>, <person> wrote:"
 *     (when followed by quote body that doesn't use ">" prefixes — e.g.
 *     Proton Mail's plain-text reply quoting)
 */
function findQuoteBoundary(lines: string[]): number {
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trimStart();
    if (trimmed.startsWith("> ") || trimmed === ">") {
      // Walk backwards past a Gmail intro line so the toggle reveals it
      // alongside the quoted lines (it belongs to the quote, not the body).
      let start = i;
      while (start > 0 && GMAIL_INTRO_RE.test(lines[start - 1].trimEnd())) {
        start -= 1;
      }
      while (start > 0 && lines[start - 1].trim() === "") {
        start -= 1;
      }
      return start;
    }
    if (
      trimmed.startsWith("**From:**") ||
      trimmed.startsWith("**From: **") || // tolerate stray space variant
      trimmed.startsWith("From: ") // plain-text version (no markdown bolding)
    ) {
      let start = i;
      while (start > 0 && lines[start - 1].trim() === "") {
        start -= 1;
      }
      return start;
    }
    // Standalone Gmail / Apple Mail intro — e.g. Proton Mail's reply format
    // doesn't use "> " prefixes. Treat the intro itself as the boundary so
    // it (and everything after) folds into the quote toggle. Only trigger
    // when the intro is followed by MORE content (not the last line) —
    // otherwise an intro-only message would lose its content to the toggle.
    if (GMAIL_INTRO_RE.test(lines[i].trimEnd()) && i < lines.length - 1) {
      let start = i;
      while (start > 0 && lines[start - 1].trim() === "") {
        start -= 1;
      }
      return start;
    }
  }
  return lines.length;
}

/**
 * Split a block of lines into "paragraphs" by collapsing runs of 2+ blank
 * lines. Each returned entry is a non-empty array of lines that belong to
 * one logical paragraph (single \n between them = same paragraph).
 */
function toParagraphs(lines: string[]): string[][] {
  const paragraphs: string[][] = [];
  let current: string[] = [];
  for (const line of lines) {
    if (line.trim() === "") {
      if (current.length) {
        paragraphs.push(current);
        current = [];
      }
    } else {
      current.push(line);
    }
  }
  if (current.length) paragraphs.push(current);
  return paragraphs;
}

/** Render a single paragraph — preserve intra-paragraph line breaks (<br>). */
function Paragraph({ lines, muted = false }: { lines: string[]; muted?: boolean }) {
  return (
    <p
      className={cn(
        "text-sm leading-relaxed break-words",
        muted ? "text-foreground/70" : "text-foreground",
      )}
    >
      {lines.map((line, i) => (
        <span key={i}>
          {line}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </p>
  );
}

interface MessageBodyProps {
  text: string | null;
  /** Drives the inbound (light card) vs outbound (primary bubble) color scheme. */
  variant: "inbound" | "outbound";
}

export function MessageBody({ text, variant }: MessageBodyProps) {
  const [showQuoted, setShowQuoted] = useState(false);
  const [showSignature, setShowSignature] = useState(false);

  if (!text) {
    return (
      <p
        className={cn(
          "text-sm italic",
          variant === "inbound" ? "text-muted-foreground" : "text-primary-foreground/60",
        )}
      >
        (no content)
      </p>
    );
  }

  const lines = text.split("\n");
  const boundary = findQuoteBoundary(lines);
  const currentText = lines.slice(0, boundary).join("\n");
  const quotedLines = lines.slice(boundary);

  // Signature detection runs on the CURRENT-message portion only. Quoted
  // history may contain old signatures from prior messages, but those are
  // already visually demoted inside the quote toggle.
  const { body: bodyText, signature } = splitEmailSignature(currentText);

  const currentParagraphs = toParagraphs(bodyText.split("\n"));
  const signatureLines = signature ? signature.split("\n") : [];
  const signatureLong = signatureLines.length > SIGNATURE_LONG_THRESHOLD_LINES;
  const quotedParagraphs = toParagraphs(quotedLines);

  const hasSignature = signature !== null && signature.length > 0;
  const hasQuote = quotedParagraphs.length > 0;

  // Inbound = dark text on light card. Outbound = light text on primary.
  const outbound = variant === "outbound";

  return (
    <div className={cn("flex flex-col gap-2", outbound && "text-primary-foreground")}>
      {currentParagraphs.map((para, i) => (
        <Paragraph key={`cur-${i}`} lines={para} />
      ))}

      {hasSignature && (
        <div
          className={cn(
            "mt-1 pt-2 border-t",
            outbound ? "border-white/15" : "border-border",
          )}
        >
          {signatureLong ? (
            <>
              <button
                type="button"
                onClick={() => setShowSignature((s) => !s)}
                className={cn(
                  "inline-flex items-center gap-1 text-[11px] font-medium transition-colors underline-offset-2 hover:underline",
                  outbound
                    ? "text-primary-foreground/60 hover:text-primary-foreground/90"
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-expanded={showSignature}
              >
                {showSignature ? (
                  <ChevronDown className="w-3 h-3" />
                ) : (
                  <ChevronRight className="w-3 h-3" />
                )}
                {showSignature ? "Hide signature" : "Show signature"}
              </button>
              {showSignature && (
                <SignatureBlock signature={signature!} outbound={outbound} />
              )}
            </>
          ) : (
            <SignatureBlock signature={signature!} outbound={outbound} />
          )}
        </div>
      )}

      {hasQuote && (
        <div className="mt-1">
          <button
            type="button"
            onClick={() => setShowQuoted((s) => !s)}
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium transition-colors",
              outbound
                ? "bg-white/10 text-primary-foreground/80 hover:bg-white/20 ring-1 ring-white/15"
                : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground ring-1 ring-border",
            )}
            aria-expanded={showQuoted}
            aria-controls="quoted-content"
          >
            {showQuoted ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
            {showQuoted
              ? "Hide quoted history"
              : `Show quoted history (${quotedParagraphs.length} paragraph${quotedParagraphs.length === 1 ? "" : "s"})`}
          </button>

          {showQuoted && (
            <div
              id="quoted-content"
              className={cn(
                "mt-2 pl-3 border-l-2 flex flex-col gap-2",
                outbound ? "border-white/25" : "border-border",
              )}
            >
              {quotedParagraphs.map((para, i) => (
                <Paragraph key={`q-${i}`} lines={para} muted />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Visual treatment for the signature block: smaller, italic, slightly muted. */
function SignatureBlock({
  signature,
  outbound,
}: {
  signature: string;
  outbound: boolean;
}) {
  return (
    <div
      className={cn(
        "mt-2 text-[12px] italic leading-relaxed whitespace-pre-line break-words",
        outbound ? "text-primary-foreground/70" : "text-muted-foreground",
      )}
    >
      {signature}
    </div>
  );
}
