"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowLeft,
  CalendarRange,
  Clock,
  DollarSign,
  Lock,
  Power,
  Server,
  Wand2,
  ChevronDown,
  ChevronUp,
  Copy,
  Loader2,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ErrorState } from "@/components/shared/error-state";
import { api, swrFetcher } from "@/lib/api";
import { useUser } from "@/hooks/use-user";
import { cn, relativeTime } from "@/lib/utils";
import type {
  RunPodStatus,
  RunPodActionResponse,
  RunPodHistoryResponse,
  RunPodDailyUsageRow,
} from "@/lib/types";

const STATUS_ENDPOINT = "/api/v1/runpod/status";
const HISTORY_ENDPOINT = "/api/v1/runpod/history?days=30";

// ── State → visual mapping ────────────────────────────────────────────────────
// last_known_state values: RUNNING / STARTING / EXITED / FAILED / TERMINATED /
// MISSING / UNHEALTHY / START_FAILED / FAILED_START / CRASHED / null.
// Anything we don't explicitly recognise falls into "unknown" with muted styling.

type StateMeta = {
  label: string;
  dot: string;
  ring: string;
  text: string;
  banner: string;
};

const STATE_META: Record<string, StateMeta> = {
  RUNNING: {
    label: "Running",
    dot: "bg-emerald-500",
    ring: "ring-emerald-500/30",
    text: "text-emerald-700 dark:text-emerald-300",
    banner: "bg-emerald-500/10 border-emerald-500/30",
  },
  STARTING: {
    label: "Starting",
    dot: "bg-amber-500 animate-pulse",
    ring: "ring-amber-500/30",
    text: "text-amber-700 dark:text-amber-300",
    banner: "bg-amber-500/10 border-amber-500/30",
  },
  EXITED: {
    label: "Stopped",
    dot: "bg-muted-foreground/60",
    ring: "ring-border",
    text: "text-muted-foreground",
    banner: "bg-muted border-border",
  },
  MISSING: {
    label: "Missing (terminated externally)",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    banner: "bg-red-500/10 border-red-500/30",
  },
  UNHEALTHY: {
    label: "Running but unhealthy",
    dot: "bg-amber-500",
    ring: "ring-amber-500/30",
    text: "text-amber-700 dark:text-amber-300",
    banner: "bg-amber-500/10 border-amber-500/30",
  },
  FAILED: {
    label: "Failed",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    banner: "bg-red-500/10 border-red-500/30",
  },
  TERMINATED: {
    label: "Terminated",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    banner: "bg-red-500/10 border-red-500/30",
  },
  START_FAILED: {
    label: "Start failed",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    banner: "bg-red-500/10 border-red-500/30",
  },
  FAILED_START: {
    label: "Start failed",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    banner: "bg-red-500/10 border-red-500/30",
  },
  CRASHED: {
    label: "Crashed",
    dot: "bg-red-500",
    ring: "ring-red-500/30",
    text: "text-red-700 dark:text-red-300",
    banner: "bg-red-500/10 border-red-500/30",
  },
};

const UNKNOWN_META: StateMeta = {
  label: "Unknown",
  dot: "bg-muted-foreground/60",
  ring: "ring-border",
  text: "text-muted-foreground",
  banner: "bg-muted border-border",
};

function metaFor(state: string | null | undefined): StateMeta {
  if (!state) return UNKNOWN_META;
  return STATE_META[state] ?? UNKNOWN_META;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDuration(totalSeconds: number | undefined | null): string {
  if (totalSeconds === undefined || totalSeconds === null) return "—";
  if (totalSeconds < 0) return "—";
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatCost(usd: number | null | undefined): string {
  if (usd === undefined || usd === null) return "—";
  return `$${usd.toFixed(2)}`;
}

function truncateMiddle(text: string, keepStart = 8, keepEnd = 4): string {
  if (text.length <= keepStart + keepEnd + 1) return text;
  return `${text.slice(0, keepStart)}…${text.slice(-keepEnd)}`;
}

function formatDayUtc(iso: string): string {
  // Parse as UTC-noon to avoid TZ shifting the displayed date.
  // toLocaleDateString without TZ option would interpret "2026-05-14" as
  // midnight UTC and could display "May 13" for users west of UTC.
  const d = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RunPodPage() {
  const { isAdmin, isLoading: userLoading } = useUser();
  const [stopConfirm, setStopConfirm] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [waking, setWaking] = useState(false);
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  const { data, error, isLoading, mutate } = useSWR<RunPodStatus>(
    isAdmin ? STATUS_ENDPOINT : null,
    swrFetcher,
    {
      // Tight polling while the pod is transitioning, slow otherwise.
      // The orchestrator's STARTING state can last up to ~3 min on a cold
      // boot — we want the UI to track that without thrashing the API
      // every 5s during steady-state RUNNING.
      refreshInterval: (current) =>
        current?.start_in_flight ||
        current?.last_known_state === "STARTING"
          ? 5_000
          : 30_000,
    },
  );

  // History only changes at the UTC midnight rollover, so a long refresh
  // interval is fine. 1h means an admin who leaves this tab open overnight
  // still sees yesterday's row appear without manual reload.
  const { data: history } = useSWR<RunPodHistoryResponse>(
    isAdmin ? HISTORY_ENDPOINT : null,
    swrFetcher,
    { refreshInterval: 60 * 60 * 1000 },
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
          Only admins can manage the RunPod orchestrator.
        </p>
      </div>
    );
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function handleStop() {
    setStopping(true);
    try {
      const result = await api.post<RunPodActionResponse>(
        "/api/v1/runpod/stop",
      );
      if (result.status === "stopped") {
        toast.success("Pod stopped. Uptime rolled into today's counter.");
      } else if (result.status === "already_stopped") {
        toast.info("Pod was already stopped on RunPod's side. Synced state.");
      } else if (result.status === "stop_failed") {
        toast.error(
          result.reason || "RunPod refused the stop request. The watchdog will retry.",
        );
      } else if (result.status === "missing") {
        toast.warning("Pod not found on RunPod — it may have been terminated externally.");
      }
      setStopConfirm(false);
      await mutate();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to stop pod";
      toast.error(msg);
    } finally {
      setStopping(false);
    }
  }

  async function handleWake() {
    setWaking(true);
    try {
      const result = await api.post<RunPodActionResponse>(
        "/api/v1/runpod/wake",
      );
      if (result.status === "ready") {
        toast.success("Pod is already running and healthy.");
      } else if (result.status === "starting") {
        toast.success("Pod is starting in the background. This takes ~1-3 min.");
      } else if (result.status === "already_starting") {
        toast.info("A start is already in progress.");
      } else if (result.status === "capacity_exceeded") {
        toast.error("Daily uptime cap reached. Resets at midnight UTC.");
      } else if (result.status === "missing") {
        toast.warning("Pod not found on RunPod.");
      }
      await mutate();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to wake pod";
      toast.error(msg);
    } finally {
      setWaking(false);
    }
  }

  function copyPodId() {
    if (!data?.pod_id) return;
    navigator.clipboard.writeText(data.pod_id);
    toast.success("Pod ID copied");
  }

  // ── Loading / empty / disabled states ─────────────────────────────────────

  if (error) {
    return (
      <div>
        <BackLink />
        <PageHeader title="RunPod" subtitle="Pod state, uptime, and controls." />
        <ErrorState
          title="Failed to load RunPod status"
          description="Could not reach the orchestrator status endpoint."
          onRetry={mutate}
        />
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div>
        <BackLink />
        <PageHeader title="RunPod" subtitle="Pod state, uptime, and controls." />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-44 rounded-xl" />
          <Skeleton className="h-44 rounded-xl" />
        </div>
      </div>
    );
  }

  if (!data.enabled) {
    return (
      <div>
        <BackLink />
        <PageHeader title="RunPod" subtitle="Pod state, uptime, and controls." />
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <Server className="w-10 h-10 text-muted-foreground mx-auto" strokeWidth={1.5} />
          <h2 className="text-lg font-semibold text-foreground mt-3">Not configured</h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            The RunPod orchestrator isn&apos;t active in this environment. Set{" "}
            <code className="font-mono text-xs px-1 py-0.5 bg-muted rounded">
              RUNPOD_POD_ID
            </code>{" "}
            in the backend environment and restart to enable.
          </p>
        </div>
      </div>
    );
  }

  // ── Enabled view ──────────────────────────────────────────────────────────

  const state = data.last_known_state ?? null;
  const meta = metaFor(state);
  const isRunning = state === "RUNNING";
  // Stop is enabled when the pod is plausibly billing: RUNNING or RUNNING-
  // but-unhealthy. The backend's stop_now reconciles with RunPod's view
  // before acting, so even if we get this wrong client-side the worst
  // outcome is an "already_stopped" toast, never a phantom uptime add.
  const canStop = state === "RUNNING" || state === "UNHEALTHY";
  const isStarting = state === "STARTING" || data.start_in_flight;
  const capReachedToday =
    (data.daily_cap_remaining_seconds ?? 0) <= 0 &&
    (data.daily_cap_seconds ?? 0) > 0;
  const uptimePct = data.daily_cap_seconds
    ? Math.min(100, ((data.uptime_today_seconds ?? 0) / data.daily_cap_seconds) * 100)
    : 0;

  return (
    <div>
      <BackLink />
      <PageHeader
        title="RunPod"
        subtitle="GPU pod state, uptime, and controls. Auto-refreshes."
      />

      {/* State banner */}
      <div
        className={cn(
          "rounded-xl border p-4 mb-6 flex items-center justify-between gap-4",
          meta.banner,
        )}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span
            className={cn(
              "inline-block w-2.5 h-2.5 rounded-full ring-2 shrink-0",
              meta.dot,
              meta.ring,
            )}
            aria-hidden
          />
          <div className="min-w-0">
            <p className={cn("text-sm font-semibold", meta.text)}>{meta.label}</p>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">
              {data.pod_id ? (
                <>
                  Pod{" "}
                  <button
                    onClick={copyPodId}
                    className="font-mono inline-flex items-center gap-1 hover:text-foreground transition-colors"
                    title="Copy pod ID"
                  >
                    {truncateMiddle(data.pod_id)}
                    <Copy className="w-3 h-3" />
                  </button>
                </>
              ) : (
                "No pod ID"
              )}
              {data.last_used_at && (
                <>
                  <span className="mx-1.5">·</span>
                  Last used {relativeTime(data.last_used_at)}
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

      <div className="grid gap-4 md:grid-cols-2">
        {/* Today card */}
        <section className="bg-card border border-border rounded-xl p-5">
          <header className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Clock className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
              Today
            </h2>
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
              UTC {data.uptime_day_utc ?? "—"}
            </span>
          </header>

          <div className="space-y-4">
            <div>
              <div className="flex items-baseline justify-between mb-1.5">
                <span className="text-xs text-muted-foreground">Uptime used</span>
                <span className="text-sm font-semibold tabular-nums text-foreground">
                  {formatDuration(data.uptime_today_seconds)}
                  <span className="text-muted-foreground font-normal">
                    {" "}
                    /{" "}
                    {formatDuration(data.daily_cap_seconds)}
                  </span>
                </span>
              </div>
              <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className={cn(
                    "h-full transition-all duration-300",
                    capReachedToday
                      ? "bg-red-500"
                      : uptimePct > 75
                        ? "bg-amber-500"
                        : "bg-emerald-500",
                  )}
                  style={{ width: `${uptimePct}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground mt-1.5">
                {capReachedToday
                  ? "Daily cap reached — pod will not auto-start until midnight UTC."
                  : `${formatDuration(data.daily_cap_remaining_seconds)} remaining before cap`}
              </p>
            </div>

            <div className="pt-3 border-t border-border flex items-baseline justify-between">
              <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                <DollarSign className="w-3.5 h-3.5" strokeWidth={1.75} />
                Est. cost today
              </span>
              <span className="text-sm font-semibold tabular-nums text-foreground">
                {formatCost(data.cost_today_usd_estimate)}
                {data.cost_per_hour_usd !== null &&
                  data.cost_per_hour_usd !== undefined && (
                    <span className="text-muted-foreground font-normal text-xs ml-1.5">
                      ({formatCost(data.cost_per_hour_usd)}/hr)
                    </span>
                  )}
              </span>
            </div>
          </div>
        </section>

        {/* Controls card */}
        <section className="bg-card border border-border rounded-xl p-5">
          <header className="mb-4">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Power className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
              Controls
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              Manual overrides. Idle-stop runs automatically every{" "}
              {formatDuration(data.idle_timeout_seconds)}.
            </p>
          </header>

          <div className="space-y-2.5">
            <Button
              variant="destructive"
              onClick={() => setStopConfirm(true)}
              disabled={!canStop || stopping || isStarting}
              className="w-full justify-start"
            >
              {stopping ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Power className="w-4 h-4 mr-2" />
              )}
              Stop pod now
            </Button>
            <Button
              variant="outline"
              onClick={handleWake}
              disabled={isRunning || waking || isStarting || capReachedToday}
              className="w-full justify-start"
            >
              {waking ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Wand2 className="w-4 h-4 mr-2" />
              )}
              Wake pod
            </Button>
          </div>

          {(isStarting || capReachedToday) && (
            <p className="text-xs text-muted-foreground mt-3 leading-relaxed">
              {capReachedToday
                ? "Wake disabled: daily cap reached."
                : "Wake disabled: a start is already in progress."}
            </p>
          )}
        </section>
      </div>

      {/* History */}
      <HistorySection
        history={history}
        dailyCapSeconds={data.daily_cap_seconds ?? 0}
      />

      {/* Diagnostics (collapsed) */}
      <section className="mt-6 bg-card border border-border rounded-xl overflow-hidden">
        <button
          onClick={() => setShowDiagnostics((v) => !v)}
          className="w-full flex items-center justify-between p-4 text-sm font-semibold text-foreground hover:bg-accent/50 transition-colors"
        >
          <span className="flex items-center gap-2">
            <Server className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
            Diagnostics
          </span>
          {showDiagnostics ? (
            <ChevronUp className="w-4 h-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          )}
        </button>
        {showDiagnostics && (
          <dl className="px-4 pb-4 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-xs border-t border-border pt-4">
            <DiagRow label="Inference URL" value={data.inference_url ?? "—"} mono />
            <DiagRow label="Pod ID" value={data.pod_id ?? "—"} mono />
            <DiagRow
              label="Last started"
              value={data.last_started_at ? relativeTime(data.last_started_at) : "—"}
            />
            <DiagRow
              label="Last stopped"
              value={data.last_stopped_at ? relativeTime(data.last_stopped_at) : "—"}
            />
            <DiagRow
              label="Start in flight"
              value={data.start_in_flight ? "yes" : "no"}
            />
            <DiagRow
              label="Sweep in flight"
              value={data.sweep_in_flight ? "yes" : "no"}
            />
            <DiagRow
              label="Daily cap"
              value={formatDuration(data.daily_cap_seconds)}
            />
            <DiagRow
              label="Idle timeout"
              value={formatDuration(data.idle_timeout_seconds)}
            />
          </dl>
        )}
      </section>

      <ConfirmDialog
        open={stopConfirm}
        onOpenChange={setStopConfirm}
        title="Stop the RunPod pod?"
        description={
          "This stops the GPU pod immediately. The current session's uptime " +
          "still counts toward today's cap. The pod will auto-restart on the " +
          "next draft generation request."
        }
        confirmLabel="Stop pod"
        confirmVariant="destructive"
        onConfirm={handleStop}
        loading={stopping}
      />
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function BackLink() {
  return (
    <Link
      href="/settings"
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-3"
    >
      <ArrowLeft className="w-3.5 h-3.5" />
      Back to settings
    </Link>
  );
}

function HistorySection({
  history,
  dailyCapSeconds,
}: {
  history: RunPodHistoryResponse | undefined;
  dailyCapSeconds: number;
}) {
  // Loading shimmer.
  if (history === undefined) {
    return (
      <section className="mt-6 bg-card border border-border rounded-xl p-5">
        <header className="mb-4 flex items-center gap-2">
          <CalendarRange className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
          <h2 className="text-sm font-semibold text-foreground">History</h2>
        </header>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-6" />
          ))}
        </div>
      </section>
    );
  }

  const items = history.items ?? [];
  const days = history.days ?? 30;

  // Total cost across the window — items with null cost contribute nothing.
  const totalCost = items.reduce(
    (sum, row) => sum + (row.cost_usd ?? 0),
    0,
  );
  const totalUptime = items.reduce(
    (sum, row) => sum + row.uptime_seconds,
    0,
  );

  // Empty state — no rollovers captured yet (fresh deploy, or pod never used).
  if (items.length === 0) {
    return (
      <section className="mt-6 bg-card border border-border rounded-xl p-5">
        <header className="mb-4 flex items-center gap-2">
          <CalendarRange className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
          <h2 className="text-sm font-semibold text-foreground">
            History — last {days} days
          </h2>
        </header>
        <p className="text-xs text-muted-foreground leading-relaxed">
          No usage captured yet. A row gets recorded for each UTC day the pod
          ran at least once — your first row will appear after the next
          midnight UTC rollover.
        </p>
      </section>
    );
  }

  // Scale denominator for bars: the daily cap is the most meaningful
  // denominator (a half-filled bar = half the budget that day) — but if
  // the cap isn't configured, fall back to the max uptime in the window
  // so bars still render proportionally.
  const maxObserved = items.reduce(
    (m, row) => Math.max(m, row.uptime_seconds),
    0,
  );
  const scaleDenom = dailyCapSeconds > 0 ? dailyCapSeconds : maxObserved || 1;

  return (
    <section className="mt-6 bg-card border border-border rounded-xl p-5">
      <header className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CalendarRange className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
          <h2 className="text-sm font-semibold text-foreground">
            History — last {days} days
          </h2>
        </div>
        <div className="text-right">
          <div className="text-xs text-muted-foreground">Window total</div>
          <div className="text-sm font-semibold tabular-nums text-foreground">
            ${totalCost.toFixed(2)}
            <span className="text-muted-foreground font-normal text-xs ml-1.5">
              · {formatDuration(totalUptime)}
            </span>
          </div>
        </div>
      </header>

      <ol className="space-y-1.5">
        {items.map((row) => (
          <HistoryRow key={row.day_utc} row={row} scaleDenom={scaleDenom} />
        ))}
      </ol>

      <p className="text-xs text-muted-foreground mt-4 leading-relaxed">
        Days where the pod wasn&apos;t used at all are omitted. Bars are
        scaled to the {dailyCapSeconds > 0 ? "daily cap" : "peak day in this window"}.
      </p>
    </section>
  );
}

function HistoryRow({
  row,
  scaleDenom,
}: {
  row: RunPodDailyUsageRow;
  scaleDenom: number;
}) {
  // Width percentage; min 2% so non-zero rows always show a sliver.
  const rawPct = (row.uptime_seconds / scaleDenom) * 100;
  const widthPct = Math.max(2, Math.min(100, rawPct));
  // Colour cue: red when a day burned >75% of the cap.
  const overCap = rawPct >= 100;
  const high = rawPct >= 75;
  const barColor = overCap
    ? "bg-red-500"
    : high
      ? "bg-amber-500"
      : "bg-emerald-500";

  return (
    <li className="flex items-center gap-3 text-xs">
      <span className="w-24 shrink-0 text-muted-foreground tabular-nums">
        {formatDayUtc(row.day_utc)}
      </span>
      <span className="relative flex-1 h-5 bg-muted rounded">
        <span
          className={cn("absolute inset-y-0 left-0 rounded", barColor)}
          style={{ width: `${widthPct}%` }}
          aria-hidden
        />
        <span className="absolute inset-0 flex items-center justify-end pr-2 font-medium text-foreground/90 tabular-nums">
          {formatDuration(row.uptime_seconds)}
        </span>
      </span>
      <span className="w-16 shrink-0 text-right font-semibold tabular-nums text-foreground">
        {formatCost(row.cost_usd)}
      </span>
    </li>
  );
}

function DiagRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground shrink-0">{label}</dt>
      <dd
        className={cn(
          "text-foreground truncate text-right",
          mono && "font-mono",
        )}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
