import { cn } from "@/lib/utils";
import { CATEGORY_BADGE_CLASSES, CATEGORY_LABELS } from "@/lib/constants";
import type { EmailCategory } from "@/lib/types";

interface CategoryBadgeProps {
  category: EmailCategory;
  className?: string;
}

export function CategoryBadge({ category, className }: CategoryBadgeProps) {
  return (
    <span
      className={cn(
        "rounded-full px-2.5 py-0.5 text-xs font-medium",
        CATEGORY_BADGE_CLASSES[category] ?? "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
        className
      )}
    >
      {CATEGORY_LABELS[category] ?? category}
    </span>
  );
}
