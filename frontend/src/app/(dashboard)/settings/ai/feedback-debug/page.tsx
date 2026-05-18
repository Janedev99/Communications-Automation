"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Lock,
  Sparkles,
  RefreshCw,
  AlertTriangle,
  BookOpen,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useUser } from "@/hooks/use-user";
import { useFeedbackPreview, type FeedbackExample } from "@/hooks/use-feedback";
import { CATEGORY_LABELS } from "@/lib/constants";
import { cn, formatDate, relativeTime } from "@/lib/utils";
import type { EmailCategory } from "@/lib/types";

const CATEGORIES: EmailCategory[] = [
  "status_update",
  "document_request",
  "appointment",
  "clarification",
  "general_inquiry",
  "complaint",
  "urgent",
  "uncategorized",
];

/**
 * Admin debug surface for the implicit-feedback retrieval system.
 *
 * Pick a category, see what the AI would use as in-context examples and
 * anti-patterns for the next draft in that category. Doubles as a
 * developer-facing inspection tool when triaging "why is the AI suddenly
 * formal / casual / off-tone."
 */
export default function FeedbackDebugPage() {
  const { isAdmin, isLoading: userLoading } = useUser();
  const [category, setCategory] = useState<EmailCategory>("status_update");
  const { preview, isLoading, isError, mutate } = useFeedbackPreview(
    isAdmin ? category : null,
  );

  if (userLoading) return null;

  if (!isAdmin) {
    return (
      <div className="bg-card border border-border rounded-xl p-8 text-center">
        <Lock className="w-10 h-10 text-muted-foreground mx-auto" strokeWidth={1.5} />
        <h2 className="text-lg font-semibold text-foreground mt-3">
          Admin access required
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Only admins can inspect the AI&apos;s feedback context.
        </p>
      </div>
    );
  }

  return (
    <div>
      <Link
        href="/settings"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to settings
      </Link>

      <PageHeader
        eyebrow="AI"
        title="Feedback context preview"
        subtitle="See exactly what historical examples and anti-patterns the AI uses when drafting for each category."
      />

      {/* Category selector */}
      <div className="bg-card rounded-xl ring-1 ring-foreground/10 p-6 mb-6">
        <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
          Category
        </label>
        <div className="flex items-center gap-3">
          <Select value={category} onValueChange={(v) => setCategory(v as EmailCategory)}>
            <SelectTrigger className="w-full max-w-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {CATEGORY_LABELS[c]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => mutate()}
            disabled={isLoading}
            aria-label="Refresh"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            <span className="ml-1.5">Refresh</span>
          </Button>
        </div>
      </div>

      {isError && (
        <div className="rounded-xl ring-1 ring-destructive/20 bg-destructive/5 p-6 mb-6">
          <p className="text-sm text-destructive">
            Failed to load feedback context. Try refresh, or check the API server.
          </p>
        </div>
      )}

      {isLoading && (
        <div className="space-y-6">
          <SkeletonSection />
          <SkeletonSection />
        </div>
      )}

      {!isLoading && preview && (
        <div className="space-y-6">
          <Section
            icon={<Sparkles className="w-3.5 h-3.5" />}
            title="Positive examples"
            count={preview.positive.length + preview.curated.length}
            description="Saved messages and approved drafts. Used as voice and tone references."
          >
            {preview.curated.length === 0 && preview.positive.length === 0 ? (
              <EmptyHint message="No positive signal yet for this category. The AI is using your knowledge base entries only. Examples will appear here as you approve and save drafts." />
            ) : (
              <div className="space-y-3">
                {preview.curated.map((ex, i) => (
                  <ExampleCard key={`c-${i}`} example={ex} />
                ))}
                {preview.positive.map((ex, i) => (
                  <ExampleCard key={`p-${i}`} example={ex} />
                ))}
              </div>
            )}
          </Section>

          <Section
            icon={<AlertTriangle className="w-3.5 h-3.5" />}
            title="Anti-patterns"
            count={preview.negative.length}
            description="Reasons past drafts in this category were rejected. The AI is steered away from these."
          >
            {preview.negative.length === 0 ? (
              <EmptyHint message="No rejection reasons recorded for this category." />
            ) : (
              <ul className="space-y-2">
                {preview.negative.map((neg, i) => (
                  <li
                    key={`n-${i}`}
                    className="rounded-lg ring-1 ring-foreground/10 bg-amber-500/5 px-3.5 py-2.5 flex items-start gap-2"
                  >
                    <span className="mt-1.5 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm text-foreground/90">{neg.reason}</p>
                        {neg.tone && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded-4xl text-[9px] font-medium tracking-wider bg-foreground/5 text-foreground/70 ring-1 ring-inset ring-foreground/10">
                            {neg.tone.toUpperCase()} TONE
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        {formatDate(neg.occurred_at)} · {relativeTime(neg.occurred_at)}
                        {neg.actor_name && <span> · rejected by {neg.actor_name}</span>}
                      </p>
                      {neg.subject && (
                        <p className="text-[11px] text-muted-foreground/80 italic truncate mt-0.5">
                          Re: {neg.subject}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <div className="rounded-xl ring-1 ring-foreground/10 bg-muted/30 p-4 flex items-start gap-3">
            <BookOpen className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
            <p className="text-xs text-muted-foreground leading-relaxed">
              These signals are pulled at draft-generation time from approved drafts,
              outbound saved messages, and rejection reasons in this category.
              PII-flagged threads are excluded automatically. Empty results during
              the first weeks of use are expected — the system learns as the team
              works.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}


function Section({
  icon,
  title,
  count,
  description,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-card rounded-xl ring-1 ring-foreground/10 p-6">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">{icon}</span>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums">
          {count} {count === 1 ? "item" : "items"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground mb-4">{description}</p>
      {children}
    </div>
  );
}


// Same threshold as the inline indicator — keeps the collapse behaviour
// consistent across the two surfaces.
const COLLAPSED_BODY_CHARS_DEBUG = 400;

function ExampleCard({ example }: { example: FeedbackExample }) {
  const [bodyExpanded, setBodyExpanded] = useState(false);
  const isSaved = example.source === "saved";
  const chipClass = isSaved
    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/30"
    : "bg-blue-500/10 text-blue-700 dark:text-blue-300 ring-blue-500/30";
  const chipText = isSaved ? "SAVED" : "APPROVED";
  const actorVerb = isSaved ? "Saved" : "Approved";

  const isLong = example.body.length > COLLAPSED_BODY_CHARS_DEBUG;
  const displayBody =
    isLong && !bodyExpanded
      ? example.body.slice(0, COLLAPSED_BODY_CHARS_DEBUG).trimEnd() + "…"
      : example.body;

  return (
    <div className="rounded-lg ring-1 ring-foreground/10 bg-background p-4">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span
          className={cn(
            "inline-flex items-center px-2 py-0.5 rounded-4xl text-[10px] font-medium tracking-wider ring-1 ring-inset",
            chipClass,
          )}
        >
          {chipText}
        </span>
        {example.tone && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-4xl text-[10px] font-medium tracking-wider bg-foreground/5 text-foreground/70 ring-1 ring-inset ring-foreground/10">
            {example.tone.toUpperCase()} TONE
          </span>
        )}
        <span className="text-[11px] text-muted-foreground">
          {formatDate(example.occurred_at)} · {relativeTime(example.occurred_at)}
        </span>
      </div>
      {example.subject && (
        <p className="text-xs text-muted-foreground italic mb-2 truncate">
          Re: {example.subject}
        </p>
      )}
      <p className="text-sm text-foreground/85 whitespace-pre-wrap leading-relaxed">
        {displayBody}
      </p>
      {isLong && (
        <button
          type="button"
          onClick={() => setBodyExpanded((v) => !v)}
          className="mt-2 text-xs font-medium text-primary hover:underline"
          aria-expanded={bodyExpanded}
        >
          {bodyExpanded ? "See less" : "See more"}
        </button>
      )}
      {example.actor_name && (
        <p className="text-[11px] text-muted-foreground mt-2">
          {actorVerb} by {example.actor_name}
        </p>
      )}
    </div>
  );
}


function EmptyHint({ message }: { message: string }) {
  return (
    <div className="rounded-lg bg-muted/40 px-4 py-6 text-center">
      <p className="text-xs text-muted-foreground leading-relaxed max-w-md mx-auto">
        {message}
      </p>
    </div>
  );
}


function SkeletonSection() {
  return (
    <div className="bg-card rounded-xl ring-1 ring-foreground/10 p-6">
      <Skeleton className="h-4 w-32 mb-2" />
      <Skeleton className="h-3 w-64 mb-4" />
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    </div>
  );
}
