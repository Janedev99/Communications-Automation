import ReactMarkdown from "react-markdown";
import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { HighlightChip } from "./highlight-chip";
import type { Highlight } from "@/lib/types";

interface Props {
  title: string;
  summary: string | null;
  highlights: Highlight[];
  /** Legacy markdown body — only rendered when highlights is empty (pre-structured releases). */
  body?: string | null;
  /** ISO 8601 timestamp string, displayed as a short date next to the "What's new" pill. */
  publishedAt?: string | null;
  /** Tighter padding/sizing for the modal context; default is full size for archive page. */
  compact?: boolean;
}

/**
 * Single source of truth for rendering a release note. Used by:
 *   - WhatsNewModal (auto-popup on dashboard)
 *   - /whats-new archive page (chunk 3)
 *   - Admin editor live preview pane
 *
 * Render mode is decided in this order:
 *   1. structured: highlights[] non-empty → chip-driven UI
 *   2. legacy: body markdown present → ReactMarkdown render
 *   3. empty: muted placeholder
 */
export function ReleaseNoteCard({
  title,
  summary,
  highlights,
  body,
  publishedAt,
  compact = false,
}: Props) {
  const dateLabel = publishedAt
    ? new Date(publishedAt).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : null;

  const hasStructured = highlights.length > 0;
  const hasLegacy = !hasStructured && !!body && body.trim().length > 0;

  return (
    <article
      className={cn(
        "rounded-2xl border border-border bg-card",
        compact ? "p-5" : "p-6",
      )}
    >
      <header className="flex items-center gap-2 mb-3">
        <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-brand-500 to-brand-700 px-2.5 py-0.5 text-xs font-semibold text-white">
          <Sparkles className="h-3 w-3" aria-hidden="true" />
          What&apos;s new
        </span>
        {dateLabel && (
          <>
            <span className="text-xs text-muted-foreground">·</span>
            <span className="text-xs text-muted-foreground">{dateLabel}</span>
          </>
        )}
      </header>

      <h2
        className={cn(
          "font-bold text-foreground tracking-tight mb-2",
          compact ? "text-lg" : "text-xl",
        )}
      >
        {title || (
          <span className="text-muted-foreground italic font-normal">
            Untitled release
          </span>
        )}
      </h2>

      {summary && summary.trim() && (
        <p
          className={cn(
            "text-muted-foreground leading-relaxed mb-4",
            compact ? "text-sm" : "text-sm",
          )}
        >
          {summary}
        </p>
      )}

      {hasStructured && (
        <ul className="space-y-2 border-t border-border/60 pt-4">
          {highlights.map((h, i) => (
            <li
              key={`${h.category}-${i}`}
              className="flex items-start gap-2.5 text-sm text-foreground"
            >
              <HighlightChip category={h.category} />
              <span className="leading-snug">{h.text}</span>
            </li>
          ))}
        </ul>
      )}

      {hasLegacy && (
        <div className="text-sm text-foreground/90 leading-relaxed border-t border-border/60 pt-4 max-h-[50vh] overflow-y-auto [&_p]:mb-2 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:mb-2 [&_li]:mb-0.5 [&_strong]:font-semibold [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h3]:font-semibold [&_h3]:text-foreground [&_h3]:mt-3 [&_h3]:mb-1">
          <ReactMarkdown>{body!}</ReactMarkdown>
        </div>
      )}

      {!hasStructured && !hasLegacy && (
        <p className="text-sm text-muted-foreground italic border-t border-border/60 pt-4">
          No content yet.
        </p>
      )}
    </article>
  );
}
