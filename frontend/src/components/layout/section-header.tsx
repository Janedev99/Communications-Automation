import Link from "next/link";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface SectionHeaderProps {
  title: string;
  icon?: LucideIcon;
  count?: number;
  viewAllHref?: string;
  viewAllLabel?: string;
  actions?: React.ReactNode;
  className?: string;
}

export function SectionHeader({
  title,
  icon: Icon,
  count,
  viewAllHref,
  viewAllLabel = "View all",
  actions,
  className,
}: SectionHeaderProps) {
  return (
    <div className={cn("flex items-center justify-between gap-3 mb-3", className)}>
      <div className="flex items-center gap-2 min-w-0">
        {Icon && (
          <Icon
            className="w-4 h-4 text-muted-foreground shrink-0"
            strokeWidth={1.75}
            aria-hidden="true"
          />
        )}
        <h2 className="text-sm font-semibold text-foreground tracking-tight">{title}</h2>
        {typeof count === "number" && count > 0 && (
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-muted text-[10px] font-semibold text-muted-foreground tabular-nums">
            {count}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {actions}
        {viewAllHref && (
          <Link
            href={viewAllHref}
            className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline"
          >
            {viewAllLabel}
            <ChevronRight className="w-3 h-3" aria-hidden="true" />
          </Link>
        )}
      </div>
    </div>
  );
}
