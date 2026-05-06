"use client";

import { BookOpen, Filter, Sparkles, UserCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CategorizationSource } from "@/lib/types";

interface SourcePillProps {
  source: CategorizationSource;
  className?: string;
}

const META: Record<
  CategorizationSource,
  { icon: typeof Sparkles; label: string; classes: string; tooltip: string }
> = {
  // NOTE on the "claude" key: this is the backend `categorization_source` enum
  // value (kept stable so we don't break a database migration just to relabel).
  // The user-visible label/tooltip have been generalised to "AI" because the
  // production deployment now runs a self-hosted Gemma model on RunPod, not
  // Claude. See backend/app/services/llm_client.py for the provider story.
  claude: {
    icon: Sparkles,
    label: "AI",
    classes: "bg-violet-500/15 text-violet-700 dark:text-violet-300 ring-violet-500/30",
    tooltip: "Categorized by the AI model",
  },
  rules_fallback: {
    icon: Filter,
    label: "Rules",
    classes: "bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-amber-500/30",
    tooltip: "Keyword-based fallback used (AI was unavailable)",
  },
  manual: {
    icon: UserCircle2,
    label: "Manual",
    classes: "bg-sky-500/15 text-sky-700 dark:text-sky-300 ring-sky-500/30",
    tooltip: "Manually re-categorized by a staff member",
  },
};

export function SourcePill({ source, className }: SourcePillProps) {
  const meta = META[source] ?? META.claude;
  const Icon = meta.icon;
  return (
    <span
      title={meta.tooltip}
      className={cn(
        "inline-flex items-center gap-1 h-6 px-2 rounded text-xs font-medium ring-1 ring-inset",
        meta.classes,
        className
      )}
    >
      <Icon className="w-3 h-3" strokeWidth={2} />
      {meta.label}
    </span>
  );
}

/** Mostly-decorative variant: shows just an icon + tooltip. Useful in dense rows. */
export function SourceGlyph({ source, className }: SourcePillProps) {
  const meta = META[source] ?? META.claude;
  const Icon = meta.icon;
  return (
    <span title={meta.tooltip} className={cn("inline-flex items-center", className)}>
      <Icon
        className={cn(
          "w-3.5 h-3.5",
          source === "claude" && "text-violet-500",
          source === "rules_fallback" && "text-amber-500",
          source === "manual" && "text-sky-500",
        )}
        strokeWidth={2}
        aria-label={meta.label}
      />
    </span>
  );
}

// Re-export for places that prefer separate exports
export { BookOpen };
