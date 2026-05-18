"use client";

import { useState } from "react";
import { Sparkles, ChevronDown, AlertTriangle } from "lucide-react";
import { cn, relativeTime } from "@/lib/utils";
import { useFeedbackPreview, type FeedbackExample } from "@/hooks/use-feedback";
import type { EmailCategory } from "@/lib/types";

interface FeedbackIndicatorProps {
  category: EmailCategory;
}

/**
 * Small inline marker that reveals the historical feedback context the AI
 * used to generate this draft. Renders nothing during the bootstrap window
 * (positive + curated + negative all zero) — see the iteration's Stage 2
 * design: "render nothing during bootstrap" is the disciplined choice.
 */
export function FeedbackIndicator({ category }: FeedbackIndicatorProps) {
  const [expanded, setExpanded] = useState(false);
  const { preview, isLoading } = useFeedbackPreview(category);

  if (isLoading || !preview) return null;

  const { counts } = preview;
  const positiveTotal = counts.positive + counts.curated;
  const negativeTotal = counts.negative;

  // Bootstrap state: no signal exists yet — render nothing rather than a
  // "0 examples" placeholder. The AI is still working off the manual KB.
  if (positiveTotal === 0 && negativeTotal === 0) return null;

  const label =
    positiveTotal > 0
      ? `Informed by ${positiveTotal} example${positiveTotal === 1 ? "" : "s"}`
      : "Informed by past corrections";

  const Icon = positiveTotal > 0 ? Sparkles : AlertTriangle;

  return (
    <div className="rounded-lg ring-1 ring-foreground/10 bg-muted/30">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={`${label}. ${expanded ? "Hide" : "Show"} details.`}
        className={cn(
          "w-full flex items-center justify-between gap-2 px-3 py-2 text-xs",
          "text-muted-foreground hover:text-foreground transition-colors",
          "rounded-lg"
        )}
      >
        <span className="flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5" />
          <span>{label}</span>
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform duration-150",
            expanded && "rotate-180"
          )}
        />
      </button>

      {expanded && <FeedbackDetails preview={preview} />}
    </div>
  );
}


function FeedbackDetails({
  preview,
}: {
  preview: NonNullable<ReturnType<typeof useFeedbackPreview>["preview"]>;
}) {
  return (
    <div className="border-t border-foreground/5 px-3 py-3 space-y-4">
      {(preview.curated.length > 0 || preview.positive.length > 0) && (
        <Section title="Past examples">
          <p className="text-[11px] text-muted-foreground mb-2">
            Responses we&apos;ve sent for similar emails. The AI uses these as
            voice and tone references.
          </p>
          <div className="space-y-2">
            {/* Curated first (stronger signal — Jane explicitly saved these) */}
            {preview.curated.map((ex, i) => (
              <ExampleRow key={`c-${i}`} example={ex} />
            ))}
            {preview.positive.map((ex, i) => (
              <ExampleRow key={`p-${i}`} example={ex} />
            ))}
          </div>
        </Section>
      )}

      {preview.negative.length > 0 && (
        <Section title="Issues avoided">
          <p className="text-[11px] text-muted-foreground mb-2">
            Reasons past drafts in this category were rejected.
          </p>
          <ul className="space-y-2">
            {preview.negative.map((neg, i) => (
              <li
                key={`n-${i}`}
                className="text-xs flex items-start gap-2 text-foreground/80"
              >
                <span className="mt-1 inline-block h-1 w-1 rounded-full bg-amber-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p>{neg.reason}</p>
                  <p className="text-[10px] text-muted-foreground/80 mt-0.5">
                    {neg.tone && <span>{neg.tone} tone · </span>}
                    {relativeTime(neg.occurred_at)}
                    {neg.actor_name && <span> · by {neg.actor_name}</span>}
                  </p>
                  {neg.subject && (
                    <p className="text-[10px] text-muted-foreground/70 italic truncate">
                      Re: {neg.subject}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <p className="text-[10px] text-muted-foreground/70 leading-relaxed pt-1">
        These examples come from your approved drafts, saved messages, and
        rejection feedback for this category. The AI sees them automatically.
      </p>
    </div>
  );
}


function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
        {title}
      </h4>
      {children}
    </div>
  );
}


function ExampleRow({ example }: { example: FeedbackExample }) {
  const labelClass =
    example.source === "saved"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/30"
      : "bg-blue-500/10 text-blue-700 dark:text-blue-300 ring-blue-500/30";
  const labelText = example.source === "saved" ? "SAVED" : "APPROVED";
  const actorVerb = example.source === "saved" ? "Saved" : "Approved";

  return (
    <div className="rounded-md bg-background/60 ring-1 ring-foreground/5 p-2.5">
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <span
          className={cn(
            "inline-flex items-center px-1.5 py-0.5 rounded-4xl text-[9px] font-medium tracking-wider ring-1 ring-inset",
            labelClass
          )}
        >
          {labelText}
        </span>
        {example.tone && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded-4xl text-[9px] font-medium tracking-wider bg-foreground/5 text-foreground/70 ring-1 ring-inset ring-foreground/10">
            {example.tone.toUpperCase()}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground">
          {relativeTime(example.occurred_at)}
        </span>
      </div>
      {example.subject && (
        <p className="text-[10px] text-muted-foreground italic mb-1.5 truncate">
          Re: {example.subject}
        </p>
      )}
      <p className="text-xs text-foreground/85 whitespace-pre-wrap leading-relaxed">
        {example.body}
      </p>
      {example.actor_name && (
        <p className="text-[10px] text-muted-foreground/80 mt-1.5">
          {actorVerb} by {example.actor_name}
        </p>
      )}
    </div>
  );
}
