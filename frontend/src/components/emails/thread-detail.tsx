"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ThreadStatusBadge } from "./thread-status-badge";
import { CategoryBadge } from "./category-badge";
import { MessageBubble } from "./message-bubble";
import { SEVERITY_BADGE_CLASSES, SEVERITY_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { EmailThread, Escalation } from "@/lib/types";

interface ThreadDetailProps {
  thread: EmailThread;
  escalation?: Escalation;
}

export function ThreadDetail({ thread, escalation }: ThreadDetailProps) {
  const confidence = thread.category_confidence
    ? `AI: ${Math.round(thread.category_confidence * 100)}% confident`
    : null;

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Thread metadata header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white flex-shrink-0">
        <h2 className="text-base font-semibold text-gray-800">{thread.subject}</h2>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <span className="text-sm text-gray-600">
            {thread.client_name ?? thread.client_email}
          </span>
          <ThreadStatusBadge status={thread.status} />
          <CategoryBadge category={thread.category} />
          {confidence && (
            <span className="text-xs text-gray-400">{confidence}</span>
          )}
        </div>

        {thread.ai_summary && (
          <div className="mt-3 bg-gray-50 rounded-md px-3 py-2 border border-gray-100">
            <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1">
              AI Summary
            </p>
            <p className="text-sm text-gray-600 leading-relaxed">{thread.ai_summary}</p>
          </div>
        )}

        {thread.suggested_reply_tone && (
          <p className="text-xs text-gray-400 mt-2">
            Suggested tone: {thread.suggested_reply_tone}
          </p>
        )}
      </div>

      {/* Escalation banner */}
      {escalation && (
        <div className="mx-6 mt-3 px-4 py-3 rounded-md bg-red-50 border border-red-200 flex items-start gap-3 flex-shrink-0">
          <AlertTriangle className="text-red-500 w-5 h-5 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-sm text-red-700">This thread has been escalated </span>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                SEVERITY_BADGE_CLASSES[escalation.severity]
              )}
            >
              {SEVERITY_LABELS[escalation.severity]}
            </span>
          </div>
          <Link
            href="/escalations"
            className="text-xs text-red-600 hover:text-red-700 underline flex-shrink-0"
          >
            View escalation
          </Link>
        </div>
      )}

      {/* Messages area */}
      <ScrollArea className="flex-1">
        <div className="flex flex-col space-y-4 px-6 py-4 bg-gray-50/50">
          {thread.messages.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">No messages yet.</p>
          ) : (
            thread.messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
