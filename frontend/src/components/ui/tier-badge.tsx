"use client";

import { AlertTriangle, Inbox, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ThreadTier } from "@/lib/types";

interface TierBadgeProps {
  tier: ThreadTier;
  /** "glyph" = icon-only (dense rows) | "pill" = icon + label (headers, detail) */
  variant?: "glyph" | "pill";
  className?: string;
}

const META: Record<
  ThreadTier,
  {
    icon: typeof Zap;
    label: string;
    short: string;
    pillClasses: string;
    glyphColor: string;
    rowAccent: string; // left border color for inbox rows
    tooltip: string;
  }
> = {
  t1_auto: {
    icon: Zap,
    label: "Auto-handled",
    short: "T1",
    pillClasses:
      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-emerald-500/30",
    glyphColor: "text-emerald-500",
    rowAccent: "border-l-emerald-500",
    tooltip: "Tier 1 — handled automatically by AI",
  },
  t2_review: {
    icon: Inbox,
    label: "For review",
    short: "T2",
    pillClasses:
      "bg-muted text-muted-foreground ring-border",
    glyphColor: "text-muted-foreground",
    rowAccent: "border-l-transparent",
    tooltip: "Tier 2 — staff review required before sending",
  },
  t3_escalate: {
    icon: AlertTriangle,
    label: "Escalated",
    short: "T3",
    pillClasses:
      "bg-red-500/15 text-red-700 dark:text-red-300 ring-red-500/30",
    glyphColor: "text-red-500",
    rowAccent: "border-l-red-500",
    tooltip: "Tier 3 — escalated to firm owner",
  },
};

export function TierBadge({ tier, variant = "pill", className }: TierBadgeProps) {
  const meta = META[tier] ?? META.t2_review;
  const Icon = meta.icon;

  if (variant === "glyph") {
    return (
      <span title={meta.tooltip} className={cn("inline-flex items-center", className)}>
        <Icon
          className={cn("w-4 h-4", meta.glyphColor)}
          strokeWidth={2}
          aria-label={meta.label}
        />
      </span>
    );
  }

  return (
    <span
      title={meta.tooltip}
      className={cn(
        "inline-flex items-center gap-1 h-6 px-2 rounded text-xs font-medium ring-1 ring-inset",
        meta.pillClasses,
        className
      )}
    >
      <Icon className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
      {meta.label}
    </span>
  );
}

/** Helper: returns the row left-accent color for a given tier. Used by email list rows. */
export function tierRowAccent(tier: ThreadTier): string {
  return (META[tier] ?? META.t2_review).rowAccent;
}
