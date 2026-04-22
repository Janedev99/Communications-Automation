"use client";

import { Activity, Sparkles, Info } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, relativeTime } from "@/lib/utils";
import { useSystemStatus } from "@/hooks/use-system-status";

function minutesAgo(isoDate: string | null): number | null {
  if (!isoDate) return null;
  return Math.floor((Date.now() - new Date(isoDate).getTime()) / 60_000);
}

interface ChipProps {
  icon: React.ReactNode;
  label: string;
  variant: "green" | "amber" | "red" | "blue";
  pulse?: boolean;
  ariaLabel?: string;
}

function StatusChip({ icon, label, variant, pulse, ariaLabel }: ChipProps) {
  const variantClasses: Record<ChipProps["variant"], string> = {
    green: "bg-emerald-50 text-emerald-700 border-emerald-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    red: "bg-red-50 text-red-700 border-red-200",
    blue: "bg-blue-50 text-blue-700 border-blue-200",
  };

  const dotClasses: Record<ChipProps["variant"], string> = {
    green: "bg-emerald-500",
    amber: "bg-amber-500",
    red: "bg-red-500",
    blue: "bg-blue-500",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border",
        variantClasses[variant]
      )}
      aria-label={ariaLabel ?? label}
    >
      <span
        className={cn(
          "w-2 h-2 rounded-full flex-shrink-0",
          dotClasses[variant],
          pulse && "animate-pulse motion-reduce:animate-none"
        )}
      />
      {icon}
      {label}
    </span>
  );
}

export function SystemStatusStrip() {
  const { status, isLoading } = useSystemStatus();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 mb-4" aria-busy="true" aria-label="Loading system status">
        <Skeleton className="h-7 w-36 rounded-full" />
        <Skeleton className="h-7 w-36 rounded-full" />
      </div>
    );
  }

  if (!status) return null;

  // Poller chip
  const pollMinsAgo = minutesAgo(status.last_successful_poll_at);
  let pollerVariant: ChipProps["variant"] = "green";
  let pollerLabel: string;
  let pollerPulse = false;

  if (!status.poller_healthy || pollMinsAgo === null || pollMinsAgo > 10) {
    pollerVariant = "red";
    pollerPulse = true;
    pollerLabel =
      pollMinsAgo !== null
        ? `STALLED (last poll ${pollMinsAgo}m ago)`
        : "STALLED (no poll recorded)";
  } else if (pollMinsAgo > 2) {
    pollerVariant = "amber";
    pollerLabel = `Delayed (${pollMinsAgo}m ago)`;
  } else {
    pollerLabel =
      status.last_successful_poll_at
        ? `Live (polled ${relativeTime(status.last_successful_poll_at)})`
        : "Live";
  }

  return (
    <div className="flex flex-wrap items-center gap-2 mb-4" role="region" aria-label="System status">
      {/* Poller chip */}
      <StatusChip
        icon={<Activity className="w-3.5 h-3.5" />}
        label={pollerLabel}
        variant={pollerVariant}
        pulse={pollerPulse}
        ariaLabel={`Email poller: ${pollerLabel}`}
      />

      {/* AI / Claude chip */}
      <StatusChip
        icon={<Sparkles className="w-3.5 h-3.5" />}
        label={status.anthropic_reachable ? "Claude reachable" : "Claude unreachable"}
        variant={status.anthropic_reachable ? "green" : "red"}
        ariaLabel={`AI service: ${status.anthropic_reachable ? "reachable" : "unreachable"}`}
      />

      {/* Shadow mode chip — only shown when active */}
      {status.shadow_mode && (
        <StatusChip
          icon={<Info className="w-3.5 h-3.5" />}
          label="Shadow mode — auto-drafts off"
          variant="blue"
          ariaLabel="Shadow mode is active: auto-drafts are disabled"
        />
      )}
    </div>
  );
}
