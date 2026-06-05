"use client";

import { useState, useEffect } from "react";
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
      <div className="px-4 lg:px-6 pt-3 pb-2 flex-shrink-0 flex items-center justify-between gap-3">
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

      {/* Two-panel layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] flex-1 min-h-0 overflow-hidden">
        {/* Left panel: thread + messages */}
        <div
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

        {/* Right panel: draft workflow */}
        <div
          className={cn(
            "border-t lg:border-t-0 lg:border-l border-border min-h-0 overflow-hidden flex flex-col",
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
