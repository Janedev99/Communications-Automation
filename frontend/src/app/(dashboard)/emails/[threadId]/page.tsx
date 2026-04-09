"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { ThreadDetail } from "@/components/emails/thread-detail";
import { DraftPanel } from "@/components/drafts/draft-panel";
import { ThreadDetailSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { useThread } from "@/hooks/use-thread";
import { useThreadDraft } from "@/hooks/use-drafts";
import { useThreadEscalation } from "@/hooks/use-thread-escalation";

export default function ThreadDetailPage({
  params,
}: {
  params: { threadId: string };
}) {
  const { threadId } = params;
  const { thread, isLoading: threadLoading, isError: threadError, mutate: mutateThread } = useThread(threadId);
  const { draft, mutate: mutateDraft } = useThreadDraft(threadId);
  const { escalation } = useThreadEscalation(threadId);

  const handleDraftChange = () => {
    mutateDraft();
    mutateThread();
  };

  const handleThreadChange = () => {
    mutateThread();
  };

  if (threadLoading) {
    return (
      <div className="-m-6 h-[calc(100vh-56px)]">
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
        <p className="text-sm text-gray-500">Thread not found.</p>
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

  return (
    <div className="-m-6 flex flex-col h-[calc(100vh-56px)]">
      {/* Back navigation */}
      <div className="px-6 pt-4 pb-2 flex-shrink-0">
        <Link
          href="/emails"
          className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          Emails
        </Link>
      </div>

      {/* Two-panel layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] flex-1 min-h-0 overflow-hidden">
        {/* Left panel: thread + messages */}
        <ThreadDetail thread={thread} escalation={escalation ?? undefined} onThreadChange={handleThreadChange} />

        {/* Right panel: draft workflow */}
        <div className="border-t lg:border-t-0 lg:border-l border-gray-200 min-h-0 overflow-hidden flex flex-col">
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
