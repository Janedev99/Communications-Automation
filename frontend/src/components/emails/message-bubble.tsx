import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import type { EmailMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: EmailMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isInbound = message.direction === "inbound";

  return (
    <div className={cn("flex flex-col max-w-[75%]", isInbound ? "self-start" : "self-end")}>
      {isInbound ? (
        <div className="bg-white rounded-xl rounded-tl-sm px-4 py-3 border border-gray-200 shadow-sm">
          <p className="text-xs font-medium text-gray-500 mb-1">{message.sender}</p>
          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
            {message.body_text ?? "(no content)"}
          </p>
          <p className="text-[10px] text-gray-300 mt-2 text-right">
            {formatDate(message.received_at)}
          </p>
        </div>
      ) : (
        <div className="bg-brand-500 rounded-xl rounded-tr-sm px-4 py-3 shadow-sm">
          <p className="text-xs font-medium text-brand-200 mb-1">{message.sender}</p>
          <p className="text-sm text-white leading-relaxed whitespace-pre-wrap">
            {message.body_text ?? "(no content)"}
          </p>
          <p className="text-[10px] text-brand-300 mt-2 text-right">
            {formatDate(message.received_at)}
          </p>
        </div>
      )}
    </div>
  );
}
