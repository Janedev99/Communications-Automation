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
    green: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
    amber: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30",
    red: "bg-destructive/10 text-destructive border-destructive/30",
    blue: "bg-primary/10 text-primary border-primary/30",
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

      {/* LLM (provider-agnostic — Anthropic / RunPod / OpenAI). Wording is
          intentionally generic: post the 05/02 RunPod migration, the brand
          on the chip would otherwise mislead. */}
      <StatusChip
        icon={<Sparkles className="w-3.5 h-3.5" />}
        label={status.llm_reachable ? "AI reachable" : "AI unreachable"}
        variant={status.llm_reachable ? "green" : "red"}
        ariaLabel={`AI service: ${status.llm_reachable ? "reachable" : "unreachable"}`}
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
