"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Bookmark,
  BookmarkCheck,
  CheckCircle,
  ShieldAlert,
  UserCircle2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { ThreadStatusBadge } from "./thread-status-badge";
import { CategoryBadge } from "./category-badge";
import { MessageBubble } from "./message-bubble";
import { SaveThreadDialog } from "./save-thread-dialog";
import { SEVERITY_BADGE_CLASSES, SEVERITY_LABELS } from "@/lib/constants";
import {
  assignThread,
  changeThreadStatus,
  unsaveThread,
} from "@/hooks/use-emails";
import { useUser } from "@/hooks/use-user";
import { cn, formatDate } from "@/lib/utils";
import type { EmailThread, Escalation } from "@/lib/types";

interface ThreadDetailProps {
  thread: EmailThread;
  escalation?: Escalation;
  onThreadChange?: () => void;
}

/**
 * The PII detector emits the canonical phrase "sensitive client data" in
 * the escalation reason. The string is the contract — keep this helper
 * in lockstep with `pii_detector.summarize_pii()` on the backend.
 */
function isSensitiveData(reason: string | null | undefined): boolean {
  if (!reason) return false;
  return reason.toLowerCase().includes("sensitive client data");
}

export function ThreadDetail({ thread, escalation, onThreadChange }: ThreadDetailProps) {
  const router = useRouter();
  const { user } = useUser();
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  // When set, the dialog targets a single message rather than the whole thread.
  const [saveMessageId, setSaveMessageId] = useState<string | null>(null);

  const openSaveForThread = () => {
    setSaveMessageId(null);
    setShowSaveDialog(true);
  };

  const openSaveForMessage = (messageId: string) => {
    setSaveMessageId(messageId);
    setShowSaveDialog(true);
  };

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

  const handleUnsave = async () => {
    if (actionLoading) return;
    setActionLoading("unsave");
    try {
      await unsaveThread(thread.id);
      onThreadChange?.();
      toast.success("Removed from saved.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not unsave.");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    // min-h-0 is essential here: this component is a CSS-grid item in
    // page.tsx, and grid items default to min-height: auto (content size).
    // Without min-h-0 the messages list can grow unbounded and the
    // <ScrollArea/> below has no bounded height to scroll within.
    <div className="flex flex-col h-full min-h-0 bg-card">
      {/* Thread metadata header */}
      <div className="px-6 py-5 border-b border-border bg-card flex-shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-foreground leading-snug tracking-tight">
              {thread.subject}
            </h2>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap text-sm">
              {thread.client_name && (
                <span className="font-medium text-foreground/90">{thread.client_name}</span>
              )}
              <button
                type="button"
                onClick={() =>
                  router.push(
                    `/emails?client_email=${encodeURIComponent(thread.client_email)}`,
                  )
                }
                className="text-muted-foreground hover:text-foreground hover:underline transition-colors"
                title="View all emails from this client"
              >
                {thread.client_email}
              </button>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {thread.is_saved ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => openSaveForThread()}
                disabled={!!actionLoading}
                className="h-8 text-xs gap-1.5 text-amber-700 dark:text-amber-300 border-amber-500/40 hover:bg-amber-500/10"
                title={
                  thread.saved_folder
                    ? `Saved in "${thread.saved_folder}" — click to edit`
                    : "Saved — click to edit"
                }
              >
                <BookmarkCheck className="w-3.5 h-3.5 fill-current" strokeWidth={1.75} aria-hidden="true" />
                {thread.saved_folder ?? "Saved"}
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => openSaveForThread()}
                disabled={!!actionLoading}
                className="h-8 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
                title="Save this thread to a folder"
              >
                <Bookmark className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Save
              </Button>
            )}
            {thread.is_saved && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleUnsave}
                disabled={!!actionLoading}
                className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                title="Remove from saved"
                aria-label="Remove from saved"
              >
                <XCircle className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
              </Button>
            )}
            {!isAssignedToMe ? (
              <Button
                variant="outline"
                size="sm"
                onClick={handleClaim}
                disabled={!!actionLoading}
                className="h-8 text-xs gap-1.5"
              >
                <UserCircle2 className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Claim
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleUnassign}
                disabled={!!actionLoading}
                className="h-8 text-xs gap-1.5 text-muted-foreground"
              >
                <UserCircle2 className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Unassign
              </Button>
            )}

            {isClosed ? (
              <Button
                variant="outline"
                size="sm"
                onClick={handleReopen}
                disabled={!!actionLoading}
                className="h-8 text-xs gap-1.5 text-emerald-700 dark:text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/10"
              >
                <CheckCircle className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Reopen
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClose}
                disabled={!!actionLoading}
                className="h-8 text-xs gap-1.5 text-muted-foreground hover:text-destructive"
              >
                <XCircle className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Close
              </Button>
            )}
          </div>
        </div>

        {/* Metadata chip row */}
        <div className="flex items-center gap-2 mt-3 flex-wrap">
          <ThreadStatusBadge status={thread.status} />
          <CategoryBadge category={thread.category} />
          {confidence && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-muted text-[11px] font-medium text-muted-foreground tabular-nums">
              {confidence}
            </span>
          )}
          {thread.assigned_to_name && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-muted text-[11px] font-medium text-muted-foreground">
              <UserCircle2
                className="w-3 h-3 text-muted-foreground/70"
                strokeWidth={1.75}
                aria-hidden="true"
              />
              {thread.assigned_to_name}
            </span>
          )}
        </div>

        {thread.ai_summary && (
          <div className="mt-4 bg-muted/40 rounded-md px-3.5 py-2.5 border border-border">
            <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1">
              AI Summary
            </p>
            <p className="text-sm text-foreground/80 leading-relaxed">{thread.ai_summary}</p>
          </div>
        )}

        {thread.suggested_reply_tone && (
          <p className="text-xs text-muted-foreground mt-2">
            Suggested tone: {thread.suggested_reply_tone}
          </p>
        )}
      </div>

      {/* Escalation banner */}
      {escalation && (
        <div className="mx-6 mt-3 px-4 py-3 rounded-md bg-destructive/10 border border-destructive/30 flex-shrink-0">
          <div className="flex items-start gap-3">
            {isSensitiveData(escalation.reason) ? (
              <ShieldAlert
                className="text-destructive w-5 h-5 mt-0.5 flex-shrink-0"
                strokeWidth={1.75}
                aria-hidden="true"
              />
            ) : (
              <AlertTriangle
                className="text-destructive w-5 h-5 mt-0.5 flex-shrink-0"
                strokeWidth={1.75}
                aria-hidden="true"
              />
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-destructive">
                  {isSensitiveData(escalation.reason) ? "Sensitive data" : "Escalated"}
                </span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    SEVERITY_BADGE_CLASSES[escalation.severity]
                  )}
                >
                  {SEVERITY_LABELS[escalation.severity]}
                </span>
                {isSensitiveData(escalation.reason) && (
                  <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-destructive/15 text-destructive">
                    PII
                  </span>
                )}
              </div>
              <p className="text-sm text-foreground/90 mt-1 leading-relaxed">{escalation.reason}</p>
              <p className="text-xs text-muted-foreground mt-1">
                Created {formatDate(escalation.created_at)}
                {escalation.assigned_to_id && " · Assigned"}
              </p>
            </div>
            <Link
              href="/escalations"
              className="text-xs font-medium text-destructive hover:underline flex-shrink-0"
            >
              View escalation
            </Link>
          </div>
        </div>
      )}

      {/* Saved-note banner — only when there's a note worth surfacing */}
      {thread.is_saved && thread.saved_note && (
        <div className="mx-6 mt-3 px-4 py-2.5 rounded-md bg-amber-500/10 border border-amber-500/30 flex-shrink-0">
          <div className="flex items-start gap-2.5">
            <BookmarkCheck
              className="w-4 h-4 mt-0.5 flex-shrink-0 text-amber-700 dark:text-amber-300 fill-current"
              strokeWidth={1.75}
              aria-hidden="true"
            />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 uppercase tracking-wider">
                Saved note
              </p>
              <p className="text-sm text-foreground/90 mt-0.5 leading-relaxed whitespace-pre-wrap">
                {thread.saved_note}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Messages area */}
      <ScrollArea className="flex-1">
        <div className="flex flex-col space-y-4 px-6 py-4 bg-muted/50">
          {thread.messages.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No messages yet.</p>
          ) : (
            thread.messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                onRequestSave={openSaveForMessage}
                onChange={onThreadChange}
              />
            ))
          )}
        </div>
      </ScrollArea>

      <SaveThreadDialog
        open={showSaveDialog}
        onOpenChange={setShowSaveDialog}
        thread={thread}
        target={
          saveMessageId
            ? { kind: "message", messageId: saveMessageId }
            : { kind: "thread" }
        }
        onSaved={() => onThreadChange?.()}
      />
    </div>
  );
}
