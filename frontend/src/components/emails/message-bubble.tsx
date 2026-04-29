import { Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import type { AttachmentInfo, EmailMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: EmailMessage;
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

export function MessageBubble({ message }: MessageBubbleProps) {
  const isInbound = message.direction === "inbound";
  const hasAttachments = !!message.attachments?.length;

  if (isInbound) {
    return (
      <div className="flex flex-col max-w-[75%] self-start">
        <div className="bg-card rounded-2xl rounded-tl-sm px-4 py-3 border border-border shadow-sm">
          <p className="text-[11px] font-medium text-muted-foreground mb-1.5 truncate">
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
        </div>
        <p className="text-[10px] text-muted-foreground mt-1 ml-2">
          {formatDate(message.received_at)}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col max-w-[75%] self-end items-end">
      <div className="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm">
        <p className="text-[11px] font-medium text-primary-foreground/70 mb-1.5 truncate">
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
      </div>
      <p className="text-[10px] text-muted-foreground mt-1 mr-2">
        {formatDate(message.received_at)}
      </p>
    </div>
  );
}
