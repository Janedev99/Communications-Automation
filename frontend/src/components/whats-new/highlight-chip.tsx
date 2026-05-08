import { Sparkles, TrendingUp, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HighlightCategory } from "@/lib/types";

const STYLES: Record<
  HighlightCategory,
  { wrap: string; label: string; Icon: LucideIcon }
> = {
  new: {
    wrap:
      "bg-slate-100 text-slate-700 ring-slate-300/60 " +
      "dark:bg-slate-800/40 dark:text-slate-200 dark:ring-slate-700/60",
    label: "NEW",
    Icon: Sparkles,
  },
  improved: {
    wrap:
      "bg-amber-50 text-amber-700 ring-amber-200/60 " +
      "dark:bg-amber-950/30 dark:text-amber-300 dark:ring-amber-800/40",
    label: "IMPROVED",
    Icon: TrendingUp,
  },
  fixed: {
    wrap:
      "bg-emerald-50 text-emerald-700 ring-emerald-200/60 " +
      "dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800/40",
    label: "FIXED",
    Icon: Wrench,
  },
};

export function HighlightChip({ category }: { category: HighlightCategory }) {
  const { wrap, label, Icon } = STYLES[category];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
        "text-[10px] font-semibold uppercase tracking-wider",
        "ring-1 shrink-0",
        wrap,
      )}
    >
      <Icon className="h-2.5 w-2.5" aria-hidden="true" />
      {label}
    </span>
  );
}
