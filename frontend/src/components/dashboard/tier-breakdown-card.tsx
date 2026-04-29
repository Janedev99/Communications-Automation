"use client";

import { AlertTriangle, Inbox, Zap, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface TierBreakdownCardProps {
  countsByTier: Record<string, number> | undefined;
  isLoading?: boolean;
}

interface Lane {
  id: "t1_auto" | "t2_review" | "t3_escalate";
  label: string;
  short: string;
  icon: LucideIcon;
  bar: string;        // bar fill class
  iconText: string;   // icon color
  href: string;
}

const LANES: Lane[] = [
  {
    id: "t1_auto",
    label: "Auto-handled",
    short: "T1",
    icon: Zap,
    bar: "bg-emerald-500",
    iconText: "text-emerald-500",
    href: "/emails?tier=t1_auto",
  },
  {
    id: "t2_review",
    label: "For review",
    short: "T2",
    icon: Inbox,
    bar: "bg-muted-foreground/40",
    iconText: "text-muted-foreground",
    href: "/emails?tier=t2_review",
  },
  {
    id: "t3_escalate",
    label: "Escalated",
    short: "T3",
    icon: AlertTriangle,
    bar: "bg-red-500",
    iconText: "text-red-500",
    href: "/emails?tier=t3_escalate",
  },
];

export function TierBreakdownCard({ countsByTier, isLoading }: TierBreakdownCardProps) {
  const counts = LANES.map((lane) => ({
    ...lane,
    count: countsByTier?.[lane.id] ?? 0,
  }));
  const total = counts.reduce((sum, c) => sum + c.count, 0);

  // Compute percentages for the stacked bar.
  // When total is 0, show evenly-split muted segments so the bar isn't blank.
  const pct = (n: number): number =>
    total > 0 ? (n / total) * 100 : 0;

  return (
    <div className="bg-card rounded-xl border border-border p-5">
      <div className="flex items-baseline justify-between mb-1">
        <h2 className="text-sm font-semibold text-foreground">Triage Distribution</h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          {total.toLocaleString()} {total === 1 ? "thread" : "threads"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        How incoming email is being handled by the AI right now.
      </p>

      {/* Stacked horizontal bar */}
      <div
        className={cn(
          "relative h-3 rounded-full overflow-hidden bg-muted ring-1 ring-border flex",
          isLoading && "animate-pulse"
        )}
        role="img"
        aria-label={
          total > 0
            ? `${counts[0].count} auto-handled, ${counts[1].count} for review, ${counts[2].count} escalated`
            : "No threads yet"
        }
      >
        {total > 0 ? (
          counts.map((lane) =>
            lane.count > 0 ? (
              <div
                key={lane.id}
                className={cn("h-full transition-[width] duration-300", lane.bar)}
                style={{ width: `${pct(lane.count)}%` }}
                title={`${lane.label}: ${lane.count} (${pct(lane.count).toFixed(1)}%)`}
              />
            ) : null
          )
        ) : (
          // Empty state — three faint segments so the geometry is still visible
          <>
            <div className="h-full w-1/3 bg-muted-foreground/10" />
            <div className="h-full w-1/3 bg-muted-foreground/15" />
            <div className="h-full w-1/3 bg-muted-foreground/10" />
          </>
        )}
      </div>

      {/* Legend / per-lane stats */}
      <div className="grid grid-cols-3 gap-2 mt-5">
        {counts.map((lane) => {
          const Icon = lane.icon;
          const percent = pct(lane.count);
          return (
            <Link
              key={lane.id}
              href={lane.href}
              className="block rounded-md p-3 hover:bg-accent/60 transition-colors group"
            >
              <div className="flex items-center gap-1.5">
                <Icon
                  className={cn("w-3.5 h-3.5", lane.iconText)}
                  strokeWidth={2}
                  aria-hidden
                />
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {lane.short}
                </span>
              </div>
              <p className="text-xl font-bold text-foreground mt-1 tabular-nums">
                {lane.count.toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {lane.label}
                {total > 0 && (
                  <span className="ml-1 opacity-70">
                    · {percent.toFixed(0)}%
                  </span>
                )}
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
