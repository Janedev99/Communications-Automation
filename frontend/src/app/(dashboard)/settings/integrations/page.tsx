"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  Clock,
  Database,
  Globe,
  Lock,
  Mail,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { SetupGuideDialog } from "@/components/integrations/setup-guide-dialog";
import { swrFetcher } from "@/lib/api";
import { useUser } from "@/hooks/use-user";
import { cn, relativeTime } from "@/lib/utils";
import { INTEGRATION_GUIDES, type IntegrationGuideId } from "@/lib/integration-guides";
import type {
  IntegrationItem,
  IntegrationsResponse,
  IntegrationStatus,
} from "@/lib/types";

const ENDPOINT = "/api/v1/admin/integrations";

// ── Visual mappings ───────────────────────────────────────────────────────────

const STATUS_META: Record<
  IntegrationStatus,
  { label: string; dot: string; ring: string; text: string; chip: string }
> = {
  healthy: {
    label: "Healthy",
    dot: "bg-emerald-500",
    ring: "ring-emerald-500/30",
    text: "text-emerald-700 dark:text-emerald-300",
    chip: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-emerald-500/30",
  },
  degraded: {
    label: "Degraded",
    dot: "bg-amber-500",
    ring: "ring-amber-500/30",
    text: "text-amber-700 dark:text-amber-300",
    chip: "bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-amber-500/30",
  },
  down: {
    label: "Down",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    chip: "bg-red-500/15 text-red-700 dark:text-red-300 ring-red-500/30",
  },
  not_configured: {
    label: "Not configured",
    dot: "bg-muted-foreground/60",
    ring: "ring-border",
    text: "text-muted-foreground",
    chip: "bg-muted text-muted-foreground ring-border",
  },
};

const ICON_MAP: Record<string, LucideIcon> = {
  postgres: Database,
  anthropic: Sparkles,
  email_provider: Mail,
  notifications: Activity,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatLatency(ms: number | null): { text: string; cls: string } | null {
  if (ms === null) return null;
  let cls = "text-foreground";
  if (ms < 100) cls = "text-emerald-700 dark:text-emerald-400";
  else if (ms > 500) cls = "text-amber-700 dark:text-amber-400";
  return { text: `${ms.toFixed(1)} ms`, cls };
}

function formatConfigKey(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    if (key.endsWith("_pct_used")) return `${value}%`;
    return value.toLocaleString();
  }
  return String(value);
}

function CONFIG_LABELS(key: string): string {
  const map: Record<string, string> = {
    host: "Host",
    username: "Username",
    mailbox: "Mailbox",
    tenant: "Tenant",
    provider: "Provider",
    model: "Model",
    api_key: "API key",
    tokens_today: "Tokens today",
    daily_budget: "Daily budget",
    budget_pct_used: "Budget used",
    slack_webhook: "Slack webhook",
    log_file: "Log file",
  };
  return map[key] ?? key;
}

// ── Card ──────────────────────────────────────────────────────────────────────

function IntegrationCard({
  item,
  onOpenGuide,
}: {
  item: IntegrationItem;
  onOpenGuide: (id: IntegrationGuideId) => void;
}) {
  const meta = STATUS_META[item.status];
  const Icon = ICON_MAP[item.id] ?? Globe;
  const latency = formatLatency(item.latency_ms);
  const hasGuide = item.id in INTEGRATION_GUIDES;

  return (
    <div className="bg-card border border-border rounded-lg p-5 flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="flex items-center justify-center w-9 h-9 rounded-md bg-muted text-muted-foreground shrink-0">
            <Icon className="w-4 h-4" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground truncate">{item.name}</h3>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span
                className={cn(
                  "inline-block w-2 h-2 rounded-full ring-2",
                  meta.dot,
                  meta.ring
                )}
                aria-hidden
              />
              <span className={cn("text-xs font-medium", meta.text)}>{meta.label}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Meta row */}
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
        {latency && (
          <div>
            <p className="text-muted-foreground">Latency</p>
            <p className={cn("font-semibold tabular-nums mt-0.5", latency.cls)}>
              {latency.text}
            </p>
          </div>
        )}
        <div className={cn(latency ? "" : "col-span-2")}>
          <p className="text-muted-foreground flex items-center gap-1">
            <Clock className="w-3 h-3" />
            Last success
          </p>
          <p
            className="text-foreground font-medium mt-0.5 truncate"
            title={item.last_success_at ?? "Never"}
          >
            {item.last_success_at ? relativeTime(item.last_success_at) : "—"}
          </p>
        </div>
      </div>

      {/* Config keys */}
      {Object.keys(item.config).length > 0 && (
        <div className="mt-4 pt-4 border-t border-border">
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
            Configuration
          </p>
          <dl className="space-y-1.5">
            {Object.entries(item.config).map(([key, value]) => (
              <div key={key} className="flex items-baseline justify-between gap-3 text-xs">
                <dt className="text-muted-foreground shrink-0">{CONFIG_LABELS(key)}</dt>
                <dd
                  className={cn(
                    "text-foreground font-mono tabular-nums truncate text-right",
                    typeof value === "string" &&
                      (value === "missing" || value === "(not set)") &&
                      "text-muted-foreground"
                  )}
                >
                  {formatConfigKey(key, value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Last error */}
      {item.last_error && (
        <div
          className={cn(
            "mt-4 pt-4 border-t border-border text-xs",
            item.status === "down"
              ? "text-red-700 dark:text-red-400"
              : item.status === "degraded"
              ? "text-amber-700 dark:text-amber-400"
              : "text-muted-foreground"
          )}
        >
          {item.last_error}
        </div>
      )}

      {hasGuide && (
        <div className="mt-4 pt-4 border-t border-border">
          <button
            onClick={() => onOpenGuide(item.id as IntegrationGuideId)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
          >
            <BookOpen className="w-3.5 h-3.5" strokeWidth={1.75} />
            Need help setting this up?
          </button>
        </div>
      )}
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="bg-card border border-border rounded-lg p-5">
      <div className="flex items-center gap-2.5">
        <Skeleton className="w-9 h-9 rounded-md" />
        <div className="flex-1 space-y-1.5">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
      </div>
      <Skeleton className="h-20 mt-4" />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function IntegrationsPage() {
  const { isAdmin, isLoading: userLoading } = useUser();
  const { data, error, isLoading, mutate } = useSWR<IntegrationsResponse>(
    isAdmin ? ENDPOINT : null,
    swrFetcher,
    { refreshInterval: 30_000 }
  );
  const [openGuide, setOpenGuide] = useState<IntegrationGuideId | null>(null);

  const emailProviderConfig = data?.items.find((i) => i.id === "email_provider")
    ?.config?.provider as string | undefined;

  if (userLoading) {
    return null;
  }

  if (!isAdmin) {
    return (
      <div className="bg-card border border-border rounded-lg p-8 text-center">
        <Lock className="w-10 h-10 text-muted-foreground mx-auto" strokeWidth={1.5} />
        <h2 className="text-lg font-semibold text-foreground mt-3">Admin access required</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Only admins can view integration health.
        </p>
      </div>
    );
  }

  const overall = data?.overall_status;
  const overallMeta = overall ? STATUS_META[overall] : null;

  return (
    <div>
      <Link
        href="/settings"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-3"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to settings
      </Link>

      <PageHeader
        title="Integrations"
        subtitle="External dependencies the system relies on. Auto-refreshes every 30 seconds."
      />

      {/* Overall banner */}
      {overallMeta && data && (
        <div
          className={cn(
            "rounded-lg border p-4 mb-6 flex items-center justify-between gap-4",
            data.overall_status === "healthy"
              ? "bg-emerald-500/10 border-emerald-500/30"
              : data.overall_status === "degraded"
              ? "bg-amber-500/10 border-amber-500/30"
              : data.overall_status === "down"
              ? "bg-red-500/10 border-red-500/30"
              : "bg-muted border-border"
          )}
        >
          <div className="flex items-center gap-3 min-w-0">
            <span
              className={cn("inline-block w-2.5 h-2.5 rounded-full ring-2", overallMeta.dot, overallMeta.ring)}
              aria-hidden
            />
            <div className="min-w-0">
              <p className={cn("text-sm font-semibold", overallMeta.text)}>
                Overall: {overallMeta.label}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Checked {relativeTime(data.checked_at)}
                {data.shadow_mode && (
                  <>
                    <span className="mx-1.5">·</span>
                    <span className="text-amber-700 dark:text-amber-400 font-medium">
                      Shadow mode is ON (drafts not auto-sent)
                    </span>
                  </>
                )}
              </p>
            </div>
          </div>
          <button
            onClick={() => mutate()}
            className="text-xs px-3 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors shrink-0"
          >
            Refresh now
          </button>
        </div>
      )}

      {error ? (
        <ErrorState
          title="Failed to load integration status"
          description="Could not retrieve health probe data."
          onRetry={mutate}
        />
      ) : isLoading || !data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.items.map((item) => (
            <IntegrationCard key={item.id} item={item} onOpenGuide={setOpenGuide} />
          ))}
        </div>
      )}

      <SetupGuideDialog
        guideId={openGuide}
        defaultPathId={emailProviderConfig}
        onClose={() => setOpenGuide(null)}
      />
    </div>
  );
}
