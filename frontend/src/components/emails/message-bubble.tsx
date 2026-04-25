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
  dark,
}: {
  attachment: AttachmentInfo;
  dark?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium",
        dark
          ? "bg-brand-600 text-brand-100"
          : "bg-muted text-muted-foreground border border-border"
      )}
      title={attachment.content_type ?? undefined}
    >
      <Paperclip className="w-2.5 h-2.5 flex-shrink-0" />
      <span className="truncate max-w-[140px]">{attachment.filename}</span>
      {attachment.size !== null && (
        <span className={cn("ml-0.5", dark ? "text-brand-300" : "text-muted-foreground")}>
          {formatBytes(attachment.size)}
        </span>
      )}
    </span>
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isInbound = message.direction === "inbound";
  const hasAttachments = !!message.attachments?.length;

  return (
    <div className={cn("flex flex-col max-w-[75%]", isInbound ? "self-start" : "self-end")}>
      {isInbound ? (
        <div className="bg-card rounded-xl rounded-tl-sm px-4 py-3 border border-border shadow-sm">
          <p className="text-xs font-medium text-muted-foreground mb-1">{message.sender}</p>
          <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
            {message.body_text ?? "(no content)"}
          </p>
          {hasAttachments && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {message.attachments!.map((att, i) => (
                <AttachmentBadge key={i} attachment={att} />
              ))}
            </div>
          )}
          <p className="text-[10px] text-muted-foreground mt-2 text-right">
            {formatDate(message.received_at)}
          </p>
        </div>
      ) : (
        <div className="bg-brand-500 rounded-xl rounded-tr-sm px-4 py-3 shadow-sm">
          <p className="text-xs font-medium text-brand-200 mb-1">{message.sender}</p>
          <p className="text-sm text-white leading-relaxed whitespace-pre-wrap">
            {message.body_text ?? "(no content)"}
          </p>
          {hasAttachments && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {message.attachments!.map((att, i) => (
                <AttachmentBadge key={i} attachment={att} dark />
              ))}
            </div>
          )}
          <p className="text-[10px] text-brand-300 mt-2 text-right">
            {formatDate(message.received_at)}
          </p>
        </div>
      )}
    </div>
  );
}
