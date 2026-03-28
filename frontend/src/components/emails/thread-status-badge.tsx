import { cn } from "@/lib/utils";
import { STATUS_BADGE_CLASSES, STATUS_LABELS } from "@/lib/constants";
import type { EmailStatus } from "@/lib/types";

interface ThreadStatusBadgeProps {
  status: EmailStatus;
  className?: string;
}

export function ThreadStatusBadge({ status, className }: ThreadStatusBadgeProps) {
  return (
    <span
      className={cn(
        "rounded-full px-2.5 py-0.5 text-xs font-medium",
        STATUS_BADGE_CLASSES[status] ?? "bg-gray-100 text-gray-600 ring-1 ring-inset ring-gray-200",
        className
      )}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
