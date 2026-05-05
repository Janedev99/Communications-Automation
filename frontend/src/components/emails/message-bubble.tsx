"use client";

import { Bookmark, BookmarkCheck, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { unsaveMessage } from "@/hooks/use-emails";
import { cn, formatDate } from "@/lib/utils";
import type { AttachmentInfo, EmailMessage } from "@/lib/types";

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

function AttachmentBadge({
  attachment,
  variant,
}: {
  attachment: AttachmentInfo;
  variant: "inbound" | "outbound";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1",
        variant === "inbound"
          ? "bg-muted text-muted-foreground ring-border"
          : "bg-white/15 text-white ring-white/20",
      )}
      title={attachment.content_type ?? undefined}
    >
      <Paperclip className="w-2.5 h-2.5 flex-shrink-0" aria-hidden="true" />
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
    </span>
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
      <div className="flex flex-col max-w-[75%] self-start">
        <div className="group relative bg-card rounded-2xl rounded-tl-sm px-4 py-3 border border-border shadow-sm">
          <p className="text-[11px] font-medium text-muted-foreground mb-1.5 truncate pr-8">
            {message.sender}
          </p>
          <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap break-words">
            {message.body_text ?? "(no content)"}
          </p>
          {hasAttachments && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {message.attachments!.map((att, i) => (
                <AttachmentBadge key={i} attachment={att} variant="inbound" />
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
              · saved in "{message.saved_folder}"
            </span>
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col max-w-[75%] self-end items-end">
      <div className="group relative bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm">
        <p className="text-[11px] font-medium text-primary-foreground/70 mb-1.5 truncate pl-8">
          {message.sender}
        </p>
        <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
          {message.body_text ?? "(no content)"}
        </p>
        {hasAttachments && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {message.attachments!.map((att, i) => (
              <AttachmentBadge key={i} attachment={att} variant="outbound" />
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
            · saved in "{message.saved_folder}"
          </span>
        )}
      </p>
    </div>
  );
}
