"use client";

import { AlertTriangle, Inbox, LayoutGrid, Zap, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ThreadTier } from "@/lib/types";

export type TierFilter = "all" | ThreadTier;

interface TierLanesNavProps {
  active: TierFilter;
  /** Per-tier counts. Pass undefined while loading — counts will render as "—". */
  counts?: Record<string, number>;
  total?: number;
  onChange: (next: TierFilter) => void;
}

interface Lane {
  id: TierFilter;
  label: string;
  icon: LucideIcon;
  iconClass: string;
  /** Pulls a tier-specific count from `counts` map. `null` for "all" (uses total). */
  countKey: string | null;
}

const LANES: Lane[] = [
  { id: "all",         label: "All",          icon: LayoutGrid,     iconClass: "text-muted-foreground", countKey: null },
  { id: "t1_auto",     label: "Auto-handled", icon: Zap,            iconClass: "text-emerald-500",      countKey: "t1_auto" },
  { id: "t2_review",   label: "For review",   icon: Inbox,          iconClass: "text-muted-foreground", countKey: "t2_review" },
  { id: "t3_escalate", label: "Escalated",    icon: AlertTriangle,  iconClass: "text-red-500",          countKey: "t3_escalate" },
];

function fmt(n: number | undefined): string {
  if (n === undefined) return "—";
  if (n > 999) return `${Math.floor(n / 100) / 10}k`;
  return String(n);
}

export function TierLanesNav({ active, counts, total, onChange }: TierLanesNavProps) {
  return (
    <nav
      role="tablist"
      aria-label="Filter by triage tier"
      className="flex items-center gap-1 mb-3 overflow-x-auto scrollbar-thin"
    >
      {LANES.map((lane) => {
        const isActive = active === lane.id;
        const Icon = lane.icon;
        const count =
          lane.countKey === null
            ? total
            : counts?.[lane.countKey];

        return (
          <button
            key={lane.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(lane.id)}
            className={cn(
              "inline-flex items-center gap-2 px-3 h-9 rounded-md text-sm font-medium transition-colors duration-150 whitespace-nowrap",
              isActive
                ? "bg-card text-foreground ring-1 ring-border shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-accent"
            )}
          >
            <Icon className={cn("w-4 h-4", isActive ? lane.iconClass : "text-muted-foreground")} strokeWidth={1.75} />
            <span>{lane.label}</span>
            <span
              className={cn(
                "inline-flex items-center justify-center min-w-[1.5rem] h-5 px-1.5 rounded text-xs font-semibold tabular-nums",
                isActive
                  ? "bg-muted text-foreground"
                  : "bg-muted/60 text-muted-foreground"
              )}
            >
              {fmt(count)}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
