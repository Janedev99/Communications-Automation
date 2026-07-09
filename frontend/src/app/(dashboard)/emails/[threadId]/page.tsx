"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { ThreadDetail } from "@/components/emails/thread-detail";
import { DraftPanel } from "@/components/drafts/draft-panel";
import { ThreadDetailSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { useThread } from "@/hooks/use-thread";
import { useThreadDraft } from "@/hooks/use-drafts";
import { useThreadEscalation } from "@/hooks/use-thread-escalation";
import { cn } from "@/lib/utils";
import type { DraftStatus } from "@/lib/types";

const DRAFT_NEEDS_ATTENTION_STATUSES: DraftStatus[] = [
  "pending",
  "edited",
  "approved",
  "send_failed",
];

// Draft workspace width (lg+ two-panel layout). Default is deliberately wider
// than the old fixed 400px — the draft is where the editing happens, per Jane's
// feedback. User-dragged width persists (jane_ localStorage convention) and is
// clamped so the conversation panel never gets squeezed to nothing.
const DRAFT_WIDTH_KEY = "jane_thread_draft_width";
const DRAFT_WIDTH_DEFAULT = 520;
const DRAFT_WIDTH_MIN = 380;
const DRAFT_WIDTH_MAX = 680;
const DRAFT_WIDTH_STEP = 24; // keyboard resize increment

function clampDraftWidth(px: number): number {
  return Math.min(DRAFT_WIDTH_MAX, Math.max(DRAFT_WIDTH_MIN, Math.round(px)));
}

export default function ThreadDetailPage({
  params,
}: {
  params: { threadId: string };
}) {
  const { threadId } = params;
  const { thread, isLoading: threadLoading, isError: threadError, mutate: mutateThread } = useThread(threadId);
  const { draft, mutate: mutateDraft } = useThreadDraft(threadId);
  const { escalation } = useThreadEscalation(threadId);

  const [mobileTab, setMobileTab] = useState<"conversation" | "draft">("conversation");

  // App Router reuses this component instance across [threadId] navigations —
  // reset to the conversation tab so a new thread never opens on a stale
  // (possibly draft-less) Draft tab.
  useEffect(() => {
    setMobileTab("conversation");
  }, [threadId]);

  // ── Resizable draft workspace (lg+) ──────────────────────────────────────
  const gridRef = useRef<HTMLDivElement>(null);
  const [draftWidth, setDraftWidth] = useState(DRAFT_WIDTH_DEFAULT);
  const [resizing, setResizing] = useState(false);
  // Latest width for the pointer-up persist (the move handler's closure would
  // otherwise capture a stale value).
  const draftWidthRef = useRef(draftWidth);
  draftWidthRef.current = draftWidth;

  // Hydrate the persisted width AFTER mount. Server and first client render
  // both use DRAFT_WIDTH_DEFAULT so the markup matches (no hydration mismatch);
  // the stored value applies once we're on the client.
  useEffect(() => {
    const saved = window.localStorage.getItem(DRAFT_WIDTH_KEY);
    if (saved !== null) {
      const n = Number(saved);
      if (Number.isFinite(n)) setDraftWidth(clampDraftWidth(n));
    }
  }, []);

  const persistDraftWidth = useCallback((px: number) => {
    const w = clampDraftWidth(px);
    setDraftWidth(w);
    window.localStorage.setItem(DRAFT_WIDTH_KEY, String(w));
  }, []);

  const handleResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    setResizing(true);
  }, []);

  const handleResizeKey = useCallback(
    (e: React.KeyboardEvent) => {
      // ArrowLeft widens the draft (divider moves left); ArrowRight narrows it.
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        persistDraftWidth(draftWidthRef.current + DRAFT_WIDTH_STEP);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        persistDraftWidth(draftWidthRef.current - DRAFT_WIDTH_STEP);
      }
    },
    [persistDraftWidth]
  );

  // Global pointer listeners live only while dragging so a drag that leaves the
  // handle still tracks. Body user-select is suspended so text isn't selected
  // mid-drag.
  useEffect(() => {
    if (!resizing) return;
    const onMove = (e: PointerEvent) => {
      const grid = gridRef.current;
      if (!grid) return;
      // Draft pane is the right column: width = grid's right edge − pointer x.
      setDraftWidth(clampDraftWidth(grid.getBoundingClientRect().right - e.clientX));
    };
    const onUp = () => {
      setResizing(false);
      window.localStorage.setItem(DRAFT_WIDTH_KEY, String(draftWidthRef.current));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    const prevSelect = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.userSelect = prevSelect;
    };
  }, [resizing]);

  const handleDraftChange = () => {
    mutateDraft();
    mutateThread();
  };

  const handleThreadChange = () => {
    mutateThread();
  };

  if (threadLoading) {
    return (
      <div className="-m-4 lg:-m-6 h-[calc(100dvh-56px)]">
        <ThreadDetailSkeleton />
      </div>
    );
  }

  if (threadError) {
    return (
      <ErrorState
        title="Failed to load thread"
        description="Could not retrieve this email thread. Please try again."
        onRetry={mutateThread}
      />
    );
  }

  if (!thread) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <p className="text-sm text-muted-foreground">Thread not found.</p>
        <Link
          href="/emails"
          className="mt-3 text-sm text-brand-500 hover:text-brand-600 flex items-center gap-1"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Emails
        </Link>
      </div>
    );
  }

  // Draft needs attention when it exists in an actionable state OR generation failed
  const draftNeedsAttention =
    (draft != null && DRAFT_NEEDS_ATTENTION_STATUSES.includes(draft.status)) ||
    thread.draft_generation_failed;

  return (
    <div className="-m-4 lg:-m-6 flex flex-col h-[calc(100dvh-56px)]">
      {/* Back navigation + mobile segmented control */}
      <div className="px-4 lg:px-6 pt-3 pb-2 flex-shrink-0 flex items-center justify-between gap-3 print:hidden">
        <Link
          href="/emails"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-muted-foreground transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          Emails
        </Link>

        {/* Mobile segmented control — hidden on lg+ */}
        <div
          role="tablist"
          aria-label="Thread view"
          className="lg:hidden inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/60"
        >
          <button
            role="tab"
            aria-selected={mobileTab === "conversation"}
            onClick={() => setMobileTab("conversation")}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 h-8 rounded-md text-sm font-medium transition-colors duration-150",
              mobileTab === "conversation"
                ? "bg-card text-foreground ring-1 ring-border shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Conversation
          </button>
          <button
            role="tab"
            aria-selected={mobileTab === "draft"}
            onClick={() => setMobileTab("draft")}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 h-8 rounded-md text-sm font-medium transition-colors duration-150",
              mobileTab === "draft"
                ? "bg-card text-foreground ring-1 ring-border shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Draft
            {/* Attention dot — shown when draft needs action and user is on conversation tab */}
            {draftNeedsAttention && mobileTab === "conversation" && (
              <span className="w-1.5 h-1.5 rounded-full bg-primary" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      {/* Two-panel layout. lg+ is a three-column grid — conversation (1fr),
          a draggable divider, and the draft workspace (user-resizable width via
          the --draft-w custom property). Below lg it collapses to a single
          column and the mobile segmented control shows one panel at a time
          (the divider is hidden). */}
      <div
        ref={gridRef}
        className="grid grid-cols-1 lg:[grid-template-columns:1fr_auto_var(--draft-w)] flex-1 min-h-0 overflow-hidden"
        style={{ "--draft-w": `${draftWidth}px` } as React.CSSProperties}
      >
        {/* Left panel: thread + messages. Marked as the print region. */}
        <div
          data-print-region
          className={cn(
            "min-h-0 min-w-0",
            mobileTab === "draft" ? "hidden lg:block" : "block"
          )}
        >
          <ThreadDetail
            thread={thread}
            escalation={escalation ?? undefined}
            onThreadChange={handleThreadChange}
            onReviewDraft={() => setMobileTab("draft")}
          />
        </div>

        {/* Resize handle (lg+ only) — the visual divider between the panels.
            Drag with the pointer or nudge with Left/Right arrow keys. */}
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize draft workspace"
          aria-valuemin={DRAFT_WIDTH_MIN}
          aria-valuemax={DRAFT_WIDTH_MAX}
          aria-valuenow={draftWidth}
          tabIndex={0}
          onPointerDown={handleResizeStart}
          onKeyDown={handleResizeKey}
          className={cn(
            "hidden lg:block self-stretch w-1.5 shrink-0 cursor-col-resize touch-none select-none z-20 print:hidden",
            "bg-border hover:bg-primary/40 transition-colors",
            "focus-visible:outline-none focus-visible:bg-primary/50",
            resizing && "bg-primary/50"
          )}
        />

        {/* Right panel: draft workflow. Excluded from print (Jane prints the
            conversation, not the draft editor). */}
        <div
          className={cn(
            "border-t lg:border-t-0 border-border min-h-0 overflow-hidden flex flex-col print:hidden",
            mobileTab === "conversation" ? "hidden lg:flex" : "flex"
          )}
        >
          <DraftPanel
            thread={thread}
            draft={draft}
            onDraftChange={handleDraftChange}
          />
        </div>
      </div>
    </div>
  );
}
