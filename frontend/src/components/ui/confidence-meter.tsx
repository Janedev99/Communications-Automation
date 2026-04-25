"use client";

import { cn } from "@/lib/utils";

interface ConfidenceMeterProps {
  /** 0–1; values outside the range are clamped. `null` renders a muted bar with "—%". */
  value: number | null | undefined;
  /** Compact layout (no label text), useful inline. */
  compact?: boolean;
  className?: string;
}

const BANDS = [
  { min: 0.85, label: "High confidence", track: "bg-emerald-500/20", fill: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300" },
  { min: 0.6,  label: "Moderate",        track: "bg-sky-500/20",     fill: "bg-sky-500",     text: "text-sky-700 dark:text-sky-300" },
  { min: 0,    label: "Low confidence",  track: "bg-amber-500/20",   fill: "bg-amber-500",   text: "text-amber-700 dark:text-amber-300" },
] as const;

function bandFor(value: number) {
  return BANDS.find((b) => value >= b.min) ?? BANDS[BANDS.length - 1];
}

export function ConfidenceMeter({ value, compact = false, className }: ConfidenceMeterProps) {
  const hasValue = value !== null && value !== undefined && Number.isFinite(value);
  const clamped = hasValue ? Math.max(0, Math.min(1, value as number)) : 0;
  const pct = Math.round(clamped * 100);
  const band = hasValue ? bandFor(clamped) : null;

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={hasValue ? pct : undefined}
      aria-label={hasValue ? `Confidence ${pct}%` : "Confidence unavailable"}
    >
      <div
        className={cn(
          "relative h-1.5 flex-1 rounded-full overflow-hidden",
          band ? band.track : "bg-muted"
        )}
      >
        {hasValue && (
          <div
            className={cn("absolute inset-y-0 left-0 rounded-full", band!.fill)}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <span className="text-xs font-medium tabular-nums text-foreground min-w-[2.5rem] text-right">
        {hasValue ? `${pct}%` : "—%"}
      </span>
      {!compact && (
        <span className={cn("text-xs font-medium hidden sm:inline", band ? band.text : "text-muted-foreground")}>
          {hasValue ? band!.label : "Unavailable"}
        </span>
      )}
    </div>
  );
}
