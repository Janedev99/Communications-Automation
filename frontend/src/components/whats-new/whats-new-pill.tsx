"use client";

import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LatestUnreadResponse } from "@/lib/types";

interface Props {
  release: LatestUnreadResponse | null;
  onOpen: () => void;
}

export function WhatsNewPill({ release, onOpen }: Props) {
  if (!release) return null;

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "hidden sm:inline-flex items-center gap-1.5 rounded-full",
        "bg-gradient-to-r from-brand-500/10 to-brand-700/10",
        "hover:from-brand-500/20 hover:to-brand-700/20",
        "border border-brand-500/30",
        "px-2.5 py-1 text-xs font-medium text-brand-600 dark:text-brand-400",
        "transition-colors",
      )}
      aria-label="What's new"
    >
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-500 opacity-60" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-brand-500" />
      </span>
      <Sparkles className="h-3 w-3" aria-hidden="true" />
      What&apos;s new
    </button>
  );
}
