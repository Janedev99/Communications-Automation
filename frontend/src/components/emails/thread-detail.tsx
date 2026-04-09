"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle, UserCircle2, XCircle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { ThreadStatusBadge } from "./thread-status-badge";
import { CategoryBadge } from "./category-badge";
import { MessageBubble } from "./message-bubble";
import { SEVERITY_BADGE_CLASSES, SEVERITY_LABELS } from "@/lib/constants";
import { assignThread, changeThreadStatus } from "@/hooks/use-emails";
import { useUser } from "@/hooks/use-user";
import { cn, formatDate } from "@/lib/utils";
import type { EmailThread, Escalation } from "@/lib/types";

interface ThreadDetailProps {
  thread: EmailThread;
  escalation?: Escalation;
  onThreadChange?: () => void;
}

export function ThreadDetail({ thread, escalation, onThreadChange }: ThreadDetailProps) {
  const router = useRouter();
  const { user } = useUser();
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const confidence = thread.category_confidence
    ? `AI: ${Math.round(thread.category_confidence * 100)}% confident`
    : null;

  const isClosed = thread.status === "closed";
  const isAssignedToMe = !!user && thread.assigned_to_id === user.id;

  const handleClaim = async () => {
    if (!user || actionLoading) return;
    setActionLoading("claim");
    try {
      await assignThread(thread.id, user.id);
      onThreadChange?.();
    } finally {
      setActionLoading(null);
    }
  };

  const handleUnassign = async () => {
    if (actionLoading) return;
    setActionLoading("unassign");
    try {
      await assignThread(thread.id, null);
      onThreadChange?.();
    } finally {
      setActionLoading(null);
    }
  };

  const handleClose = async () => {
    if (actionLoading) return;
    setActionLoading("close");
    try {
      await changeThreadStatus(thread.id, "closed");
      onThreadChange?.();
    } finally {
      setActionLoading(null);
    }
  };

  const handleReopen = async () => {
    if (actionLoading) return;
    setActionLoading("reopen");
    try {
      await changeThreadStatus(thread.id, "categorized");
      onThreadChange?.();
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Thread metadata header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white flex-shrink-0">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold text-gray-800 leading-snug">{thread.subject}</h2>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {!isAssignedToMe ? (
              <Button
                variant="outline"
                size="sm"
                onClick={handleClaim}
                disabled={!!actionLoading}
                className="h-7 text-xs gap-1"
              >
                <UserCircle2 className="w-3.5 h-3.5" />
                Claim
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleUnassign}
                disabled={!!actionLoading}
                className="h-7 text-xs gap-1 text-gray-500"
              >
                <UserCircle2 className="w-3.5 h-3.5" />
                Unassign
              </Button>
            )}

            {isClosed ? (
              <Button
                variant="outline"
                size="sm"
                onClick={handleReopen}
                disabled={!!actionLoading}
                className="h-7 text-xs gap-1 text-emerald-700 border-emerald-200 hover:bg-emerald-50"
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Reopen
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={handleClose}
                disabled={!!actionLoading}
                className="h-7 text-xs gap-1 text-gray-600 hover:text-red-600 hover:border-red-200"
              >
                <XCircle className="w-3.5 h-3.5" />
                Close
              </Button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 mt-2 flex-wrap">
          {thread.client_name && (
            <span className="text-sm text-gray-600">{thread.client_name}</span>
          )}
          <button
            type="button"
            onClick={() => router.push(`/emails?client_email=${encodeURIComponent(thread.client_email)}`)}
            className="text-sm text-brand-500 hover:text-brand-600 hover:underline transition-colors"
            title="View all emails from this client"
          >
            {thread.client_email}
          </button>
          <ThreadStatusBadge status={thread.status} />
          <CategoryBadge category={thread.category} />
          {confidence && (
            <span className="text-xs text-gray-400">{confidence}</span>
          )}
          {thread.assigned_to_name && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-500">
              <UserCircle2 className="w-3 h-3 text-brand-400" />
              {thread.assigned_to_name}
            </span>
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
        <div className="mx-6 mt-3 px-4 py-3 rounded-md bg-red-50 border border-red-200 flex-shrink-0">
          <div className="flex items-start gap-3">
            <AlertTriangle className="text-red-500 w-5 h-5 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-red-700">Escalated</span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    SEVERITY_BADGE_CLASSES[escalation.severity]
                  )}
                >
                  {SEVERITY_LABELS[escalation.severity]}
                </span>
              </div>
              <p className="text-sm text-red-600 mt-1 leading-relaxed">{escalation.reason}</p>
              <p className="text-xs text-red-400 mt-1">
                Created {formatDate(escalation.created_at)}
                {escalation.assigned_to_id && " · Assigned"}
              </p>
            </div>
            <Link
              href="/escalations"
              className="text-xs text-red-600 hover:text-red-700 underline flex-shrink-0"
            >
              View escalation
            </Link>
          </div>
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
