"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Bookmark,
  BookmarkCheck,
  BookPlus,
  CheckCircle,
  Forward,
  MoreVertical,
  Printer,
  RotateCcw,
  ShieldAlert,
  ShieldX,
  Trash2,
  UserCircle2,
} from "lucide-react";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { ThreadStatusBadge } from "./thread-status-badge";
import { CategoryBadge } from "./category-badge";
import { MessageBubble } from "./message-bubble";
import { SaveThreadDialog } from "./save-thread-dialog";
import { ForwardMessageDialog } from "./forward-message-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SEVERITY_BADGE_CLASSES, SEVERITY_LABELS } from "@/lib/constants";
import {
  addThreadToKnowledgeBase,
  assignThread,
  changeThreadStatus,
  markThreadSpam,
  trashThread,
} from "@/hooks/use-emails";
import { useUser } from "@/hooks/use-user";
import { cn, formatDate } from "@/lib/utils";
import type { EmailThread, Escalation } from "@/lib/types";

interface ThreadDetailProps {
  thread: EmailThread;
  escalation?: Escalation;
  onThreadChange?: () => void;
  /** Mobile-only: called when the user taps "Review draft →" to switch the tab panel. */
  onReviewDraft?: () => void;
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

export function ThreadDetail({ thread, escalation, onThreadChange, onReviewDraft }: ThreadDetailProps) {
  const router = useRouter();
  const { user } = useUser();
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  // When set, the dialog targets a single message rather than the whole thread.
  const [saveMessageId, setSaveMessageId] = useState<string | null>(null);
  // Trash / spam confirm dialogs — Gus's explicit ask (2026-05-21): "a
  // pop up that says — also in your Outlook. Are you sure?" The two states
  // are mutually exclusive in the UI (only one button can be in flight at
  // a time), so a single discriminated state would also work, but two
  // booleans read more clearly at the JSX call sites.
  const [showTrashConfirm, setShowTrashConfirm] = useState(false);
  const [showSpamConfirm, setShowSpamConfirm] = useState(false);
  const [showAddToKbConfirm, setShowAddToKbConfirm] = useState(false);
  const [showForwardDialog, setShowForwardDialog] = useState(false);

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
  // Forward operates on the latest INBOUND message — with none, the dialog
  // would open but could never submit. Disable both triggers up front.
  const hasInboundMessage = thread.messages.some((m) => m.direction === "inbound");

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

  const handleTrash = async () => {
    if (actionLoading) return;
    setActionLoading("trash");
    try {
      await trashThread(thread.id);
      onThreadChange?.();
      setShowTrashConfirm(false);
      // Navigate back to the inbox — the trashed thread has dropped out
      // of the default list view, so staying on its detail page leaves
      // the user on a "dead" route. Bouncing to /emails matches what
      // Outlook does after a delete.
      toast.success("Moved to Deleted Items in Outlook.");
      router.push("/emails");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not delete.");
    } finally {
      setActionLoading(null);
    }
  };

  const handleSpam = async () => {
    if (actionLoading) return;
    setActionLoading("spam");
    try {
      await markThreadSpam(thread.id);
      onThreadChange?.();
      setShowSpamConfirm(false);
      toast.success("Moved to Junk Email in Outlook.");
      router.push("/emails");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not mark as spam.");
    } finally {
      setActionLoading(null);
    }
  };

  const handleAddToKb = async () => {
    if (actionLoading) return;
    setActionLoading("kb");
    try {
      const entry = await addThreadToKnowledgeBase(thread.id);
      setShowAddToKbConfirm(false);
      // Toast with a deep-link so Jane can jump straight to the new
      // entry if she wants to edit the auto-derived title/content.
      // sonner's `action` slot renders a button on the right side of
      // the toast — perfect affordance for "saved → edit now?"
      toast.success("Added to knowledge base.", {
        action: {
          label: "Open",
          onClick: () => router.push(`/knowledge/${entry.id}`),
        },
      });
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not save to knowledge base.");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    // min-h-0 is essential here: this component is a CSS-grid item in
    // page.tsx, and grid items default to min-height: auto (content size).
    // Without min-h-0 the messages list can grow unbounded and the
    // <ScrollArea/> below has no bounded height to scroll within.
    <div className="flex flex-col h-full min-h-0 min-w-0 bg-card">
      {/* Thread metadata header */}
      <div className="px-6 py-5 border-b border-border bg-card flex-shrink-0">
        {/* Subject + a compact action cluster share one row. The cluster is
            small (Resolve + Claim + "⋯ More"), so it no longer squeezes the
            subject the way the old wide toolbar did in this narrow pane. */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
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

          {/* Actions — a compact primary + "⋯ More" cluster. The received
              email now sits in the narrow reference pane (~320–560px on
              desktop, so never wide enough for a full button row), so the wide
              toolbar was retired in favour of this cluster at every width:
              Resolve + Claim stay one tap away, everything else lives in More. */}
          <div className="flex items-center gap-2 flex-shrink-0 print:hidden">
            {/* Resolve / Reopen */}
            {isClosed ? (
              <Button
                variant="outline"
                size="sm"
                onClick={handleReopen}
                disabled={!!actionLoading}
                className="h-9 text-xs gap-1.5 text-emerald-700 dark:text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/10"
              >
                <RotateCcw className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Reopen
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={handleClose}
                disabled={!!actionLoading}
                className="h-9 text-xs gap-1.5"
              >
                <CheckCircle className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                Resolve
              </Button>
            )}

            {/* Claim / Unassign icon button */}
            {!isAssignedToMe ? (
              <button
                type="button"
                onClick={handleClaim}
                disabled={!!actionLoading}
                title="Claim this thread"
                aria-label="Claim this thread"
                className="inline-flex items-center justify-center w-9 h-9 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <UserCircle2 className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleUnassign}
                disabled={!!actionLoading}
                title="Unassign"
                aria-label="Unassign from this thread"
                className="inline-flex items-center justify-center w-9 h-9 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <UserCircle2 className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
              </button>
            )}

            {/* More menu */}
            <DropdownMenu>
              <DropdownMenuTrigger
                className="inline-flex items-center justify-center w-9 h-9 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                aria-label="More actions"
              >
                <MoreVertical className="w-4 h-4" strokeWidth={1.75} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {/* Save / Edit saved */}
                <DropdownMenuItem onClick={() => openSaveForThread()}>
                  {thread.is_saved ? (
                    <>
                      <BookmarkCheck className="w-4 h-4" strokeWidth={1.75} />
                      Edit saved
                    </>
                  ) : (
                    <>
                      <Bookmark className="w-4 h-4" strokeWidth={1.75} />
                      Save
                    </>
                  )}
                </DropdownMenuItem>

                {/* Add to KB */}
                <DropdownMenuItem onClick={() => setShowAddToKbConfirm(true)}>
                  <BookPlus className="w-4 h-4" strokeWidth={1.75} />
                  Add to KB
                </DropdownMenuItem>

                {/* Forward */}
                <DropdownMenuItem
                  onClick={() => setShowForwardDialog(true)}
                  disabled={!hasInboundMessage}
                  title={hasInboundMessage ? undefined : "Nothing to forward yet"}
                >
                  <Forward className="w-4 h-4" strokeWidth={1.75} />
                  Forward
                </DropdownMenuItem>

                {/* Print */}
                <DropdownMenuItem onClick={() => window.print()}>
                  <Printer className="w-4 h-4" strokeWidth={1.75} />
                  Print
                </DropdownMenuItem>

                {/* Spam + Delete — hidden when closed */}
                {!isClosed && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => setShowSpamConfirm(true)}
                      className="py-2"
                    >
                      <ShieldX className="w-4 h-4" strokeWidth={1.75} />
                      Spam
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => setShowTrashConfirm(true)}
                      className="py-2"
                    >
                      <Trash2 className="w-4 h-4" strokeWidth={1.75} />
                      Delete
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Mobile "Review draft →" affordance */}
        {onReviewDraft && (
          <button
            onClick={onReviewDraft}
            className="lg:hidden mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline print:hidden"
          >
            Review draft
            <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        )}

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

      </div>

      {/* Conversation. The AI summary and any banners ride at the TOP of the
          scroll (no longer pinned), so the message list gets the panel's full
          height and the scrollbar itself hints at how long the thread is. */}
      <ScrollArea className="flex-1">
        <div className="px-6 pt-4 pb-1 space-y-3 empty:hidden">
          {thread.ai_summary && (
            <div className="bg-muted/40 rounded-md px-3.5 py-2.5 border border-border">
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1">
                AI Summary
              </p>
              <p className="text-sm text-foreground/80 leading-relaxed">{thread.ai_summary}</p>
            </div>
          )}

          {thread.suggested_reply_tone && (
            <p className="text-xs text-muted-foreground">
              Suggested tone: {thread.suggested_reply_tone}
            </p>
          )}

      {/* Escalation banner */}
      {escalation && (
        <div className="px-4 py-3 rounded-md bg-destructive/10 border border-destructive/30">
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
              className="text-xs font-medium text-destructive hover:underline flex-shrink-0 print:hidden"
            >
              View escalation
            </Link>
          </div>
        </div>
      )}

      {/* Saved-note banner — only when there's a note worth surfacing */}
      {thread.is_saved && thread.saved_note && (
        <div className="px-4 py-2.5 rounded-md bg-amber-500/10 border border-amber-500/30">
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
        </div>

        {/* Messages */}
        <div className="flex flex-col space-y-4 px-6 py-4 bg-muted/50 min-w-0">
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

      <ConfirmDialog
        open={showTrashConfirm}
        onOpenChange={setShowTrashConfirm}
        title="Delete this conversation?"
        description={
          "This moves every incoming message in this thread to the Deleted Items folder in Outlook. " +
          "Sent replies are not affected. You can restore from Outlook's Deleted Items if needed."
        }
        confirmLabel="Delete"
        confirmVariant="destructive"
        loading={actionLoading === "trash"}
        onConfirm={handleTrash}
      />

      <ConfirmDialog
        open={showSpamConfirm}
        onOpenChange={setShowSpamConfirm}
        title="Mark as spam?"
        description={
          "This moves every incoming message in this thread to the Junk Email folder in Outlook " +
          "and trains Outlook's junk filter on the sender. Future emails from this sender may be " +
          "auto-routed to junk and won't reach this inbox."
        }
        confirmLabel="Mark as spam"
        confirmVariant="destructive"
        loading={actionLoading === "spam"}
        onConfirm={handleSpam}
      />

      <ForwardMessageDialog
        open={showForwardDialog}
        onOpenChange={setShowForwardDialog}
        thread={thread}
        onForwarded={() => onThreadChange?.()}
      />

      <ConfirmDialog
        open={showAddToKbConfirm}
        onOpenChange={setShowAddToKbConfirm}
        title="Add to knowledge base?"
        description={
          "Creates a knowledge base entry from this thread's most recent question and " +
          "response. Future AI drafts can pull from it as context. The default title comes " +
          "from the subject line and the category from this thread — you can edit either " +
          "afterwards from the Knowledge Base page."
        }
        confirmLabel="Add to KB"
        confirmVariant="default"
        loading={actionLoading === "kb"}
        onConfirm={handleAddToKb}
      />
    </div>
  );
}
