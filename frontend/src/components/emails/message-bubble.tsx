"use client";

import { useState } from "react";
import { Bookmark, BookmarkCheck, ChevronDown, Download, Loader2, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { unsaveMessage } from "@/hooks/use-emails";
import { downloadBinary } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import type { AttachmentInfo, EmailMessage } from "@/lib/types";
import { MessageBody } from "./message-body";
import { MessageHtmlBody } from "./message-html-body";

/**
 * To/CC disclosure line, rendered under the sender name and above the body.
 * Legacy rows (to_recipients/cc_recipients null) fall back to the singular
 * `recipient` field as a To-only display. A single To with no Cc renders as
 * a plain truncated line; multiple To or any Cc becomes a disclosure button
 * that expands to the full stacked To/Cc lists.
 */
function MessageRecipientsLine({
  message,
  variant,
}: {
  message: EmailMessage;
  variant: "inbound" | "outbound";
}) {
  const [expanded, setExpanded] = useState(false);

  const to =
    message.to_recipients && message.to_recipients.length > 0
      ? message.to_recipients
      : message.recipient
      ? [message.recipient]
      : [];
  const cc = message.cc_recipients ?? [];

  if (to.length === 0 && cc.length === 0) return null;

  const mutedClass =
    variant === "inbound" ? "text-muted-foreground" : "text-primary-foreground/70";

  // Single To, no Cc — plain line, no disclosure needed.
  if (to.length <= 1 && cc.length === 0) {
    return (
      <p className={cn("text-[10px] truncate mb-1.5", mutedClass)} title={to[0]}>
        To: {to[0]}
      </p>
    );
  }

  const fullTitle = [
    to.length > 0 ? `To: ${to.join(", ")}` : null,
    cc.length > 0 ? `Cc: ${cc.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join(" — ");
  const summary =
    to.length > 0
      ? `To: ${to[0]}${to.length > 1 ? ` +${to.length - 1}` : ""}`
      : `Cc: ${cc.length} recipient${cc.length === 1 ? "" : "s"}`;

  return (
    <div className="mb-1.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label="Show recipients for this message"
        title={fullTitle}
        className={cn(
          "inline-flex items-center gap-1 text-[10px] hover:underline",
          mutedClass,
        )}
      >
        <span className="truncate max-w-[200px]">{summary}</span>
        <ChevronDown
          className={cn("w-3 h-3 flex-shrink-0 transition-transform", expanded && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      {expanded && (
        <div className={cn("mt-1 space-y-0.5 text-[10px]", mutedClass)}>
          {to.length > 0 && <p className="break-all">To: {to.join(", ")}</p>}
          {cc.length > 0 && <p className="break-all">Cc: {cc.join(", ")}</p>}
        </div>
      )}
    </div>
  );
}

interface MessageBubbleProps {
  message: EmailMessage;
  /** Optional: opens the save dialog targeting this specific message. */
  onRequestSave?: (messageId: string) => void;
  /** Refresh callback called after a successful unsave. */
  onChange?: () => void;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Attachment with download. Clicking the badge streams the binary from the
 * backend (which fetches it on-demand from MS Graph) and saves it via the
 * browser's download path. Provider doesn't store binaries, so each click
 * is one Graph round-trip — fine for tax-document workflows where downloads
 * are infrequent and per-document deliberate.
 */
function AttachmentBadge({
  attachment,
  attachmentIndex,
  threadId,
  messageId,
  variant,
}: {
  attachment: AttachmentInfo;
  attachmentIndex: number;
  threadId: string;
  messageId: string;
  variant: "inbound" | "outbound";
}) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      await downloadBinary(
        `/api/v1/emails/${threadId}/messages/${messageId}/attachments/${attachmentIndex}/download`,
        attachment.filename,
      );
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleDownload}
      disabled={downloading}
      title={`Download ${attachment.filename}${attachment.content_type ? ` (${attachment.content_type})` : ""}`}
      aria-label={`Download ${attachment.filename}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1 transition-colors",
        "disabled:opacity-60 disabled:cursor-wait",
        variant === "inbound"
          ? "bg-muted text-muted-foreground ring-border hover:bg-accent hover:text-foreground"
          : "bg-white/15 text-white ring-white/20 hover:bg-white/25",
      )}
    >
      {downloading ? (
        <Loader2 className="w-2.5 h-2.5 flex-shrink-0 animate-spin" aria-hidden="true" />
      ) : (
        <Paperclip className="w-2.5 h-2.5 flex-shrink-0" aria-hidden="true" />
      )}
      <span className="truncate max-w-[140px]">{attachment.filename}</span>
      {attachment.size !== null && (
        <span
          className={cn(
            "ml-0.5 tabular-nums",
            variant === "inbound" ? "text-muted-foreground/80" : "text-white/70",
          )}
        >
          {formatBytes(attachment.size)}
        </span>
      )}
      <Download
        className={cn(
          "w-2.5 h-2.5 flex-shrink-0",
          variant === "inbound" ? "text-muted-foreground/70" : "text-white/70",
        )}
        aria-hidden="true"
      />
    </button>
  );
}

/**
 * Save/unsave button for a single message. Rendered overlaid on the bubble
 * so it's always reachable but never visually busy when a thread has many
 * messages — solid when saved, faded-but-discoverable when not.
 *
 * Saving opens the parent's SaveDialog (so we don't render N dialogs).
 * Unsaving is direct + idempotent.
 */
function BubbleSaveAction({
  message,
  onRequestSave,
  onChange,
  variant,
}: {
  message: EmailMessage;
  onRequestSave?: (messageId: string) => void;
  onChange?: () => void;
  variant: "inbound" | "outbound";
}) {
  if (!onRequestSave) return null;

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!message.is_saved) {
      onRequestSave(message.id);
      return;
    }
    // Already saved → unsave directly
    try {
      await unsaveMessage(message.thread_id, message.id);
      onChange?.();
      toast.success("Removed from saved.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not unsave.");
    }
  };

  const Icon = message.is_saved ? BookmarkCheck : Bookmark;
  const title = message.is_saved
    ? message.saved_folder
      ? `Saved in "${message.saved_folder}" — click to remove`
      : "Saved — click to remove"
    : "Save this email";

  return (
    <button
      type="button"
      onClick={handleClick}
      title={title}
      aria-label={title}
      className={cn(
        "absolute top-2 transition-opacity rounded-md p-1",
        // Position depends on bubble side so it doesn't overlap the
        // sender name. Inbound bubbles are left-aligned; outbound right.
        variant === "inbound" ? "right-2" : "left-2",
        message.is_saved
          ? variant === "inbound"
            ? "text-amber-600 dark:text-amber-400 bg-amber-500/10 hover:bg-amber-500/20"
            : "text-amber-300 bg-white/15 hover:bg-white/25"
          : variant === "inbound"
          ? "text-muted-foreground/50 hover:text-foreground hover:bg-accent opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
          : "text-white/60 hover:text-white hover:bg-white/15 opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
      )}
    >
      <Icon
        className={cn("w-3.5 h-3.5", message.is_saved && "fill-current")}
        strokeWidth={1.75}
      />
    </button>
  );
}

export function MessageBubble({
  message,
  onRequestSave,
  onChange,
}: MessageBubbleProps) {
  const isInbound = message.direction === "inbound";
  const hasAttachments = !!message.attachments?.length;

  if (isInbound) {
    return (
      <div className="flex flex-col max-w-[88%] sm:max-w-[75%] min-w-0 self-start">
        <div className="group relative bg-card rounded-2xl rounded-tl-sm px-4 py-3 border border-border shadow-sm min-w-0 overflow-hidden">
          <p className="text-[11px] font-medium text-muted-foreground mb-1.5 truncate pr-8">
            {message.sender}
          </p>
          <MessageRecipientsLine message={message} variant="inbound" />
          {message.body_html ? (
            <MessageHtmlBody
              html={message.body_html}
              threadId={message.thread_id}
              messageId={message.id}
            />
          ) : (
            <MessageBody text={message.body_text} variant="inbound" />
          )}
          {hasAttachments && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {message.attachments!.map((att, i) => (
                <AttachmentBadge
                  key={i}
                  attachment={att}
                  attachmentIndex={i}
                  threadId={message.thread_id}
                  messageId={message.id}
                  variant="inbound"
                />
              ))}
            </div>
          )}
          <BubbleSaveAction
            message={message}
            onRequestSave={onRequestSave}
            onChange={onChange}
            variant="inbound"
          />
        </div>
        <p className="text-[10px] text-muted-foreground mt-1 ml-2 flex items-center gap-1.5">
          <span>{formatDate(message.received_at)}</span>
          {message.is_saved && message.saved_folder && (
            <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
              · saved in &quot;{message.saved_folder}&quot;
            </span>
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col max-w-[88%] sm:max-w-[75%] min-w-0 self-end items-end">
      <div className="group relative bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm min-w-0 overflow-hidden">
        <p className="text-[11px] font-medium text-primary-foreground/70 mb-1.5 truncate pl-8">
          {message.sender}
        </p>
        <MessageRecipientsLine message={message} variant="outbound" />
        <MessageBody text={message.body_text} variant="outbound" />
        {hasAttachments && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {message.attachments!.map((att, i) => (
              <AttachmentBadge
                key={i}
                attachment={att}
                attachmentIndex={i}
                threadId={message.thread_id}
                messageId={message.id}
                variant="outbound"
              />
            ))}
          </div>
        )}
        <BubbleSaveAction
          message={message}
          onRequestSave={onRequestSave}
          onChange={onChange}
          variant="outbound"
        />
      </div>
      <p className="text-[10px] text-muted-foreground mt-1 mr-2 flex items-center gap-1.5">
        <span>{formatDate(message.received_at)}</span>
        {message.is_saved && message.saved_folder && (
          <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
            · saved in &quot;{message.saved_folder}&quot;
          </span>
        )}
      </p>
    </div>
  );
}
