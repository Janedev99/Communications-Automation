"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  AlertTriangle,
  Cpu,
  FileEdit,
  Flame,
  Inbox,
  Send,
  XCircle,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "@/components/layout/page-header";
import { StatCardSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { swrFetcher } from "@/lib/api";
import { CATEGORY_LABELS, SEVERITY_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { AnalyticsResponse, EmailCategory, EscalationSeverity } from "@/lib/types";

// ── Constants ─────────────────────────────────────────────────────────────────

const RANGE_OPTIONS = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
] as const;

const TIER_LABELS: Record<string, string> = {
  t1_auto: "Tier 1 — Auto",
  t2_review: "Tier 2 — Review",
  t3_escalate: "Tier 3 — Escalate",
};

const DRAFT_STATUS_ORDER = ["pending", "edited", "approved", "sent", "rejected", "send_failed"];

// Chart palette — indigo-led to match the brand theme.
const PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#f43f5e", "#8b5cf6", "#14b8a6", "#94a3b8", "#64748b"];
const COLOR_INPUT = "#6366f1"; // indigo — input tokens
const COLOR_OUTPUT = "#0ea5e9"; // sky — output tokens

// ── Small shared pieces ───────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
  tone = "default",
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "warn" | "danger";
}) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 min-w-0">
      <div className="flex items-center gap-2 mb-2">
        <span
          className={cn(
            "flex items-center justify-center w-7 h-7 rounded-lg shrink-0",
            tone === "danger"
              ? "bg-rose-500/10 text-rose-600 dark:text-rose-400"
              : tone === "warn"
              ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
              : "bg-primary/10 text-primary",
          )}
        >
          <Icon className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
        </span>
        <span className="text-xs text-muted-foreground truncate">{label}</span>
      </div>
      <p className="text-xl font-semibold text-foreground tabular-nums leading-none">{value}</p>
      {hint && <p className="text-[11px] text-muted-foreground mt-1.5 leading-relaxed">{hint}</p>}
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 min-w-0">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {subtitle && <p className="text-xs text-muted-foreground mt-0.5 mb-3">{subtitle}</p>}
      {!subtitle && <div className="mb-3" />}
      {children}
    </div>
  );
}

const compact = (n: number) =>
  Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** Shared axis/tooltip styling so all charts read as one family. */
const axisProps = {
  tick: { fontSize: 10, fill: "var(--color-muted-foreground, #6b7280)" },
  tickLine: false,
  axisLine: false,
} as const;

const tooltipStyle = {
  contentStyle: {
    fontSize: 12,
    borderRadius: 8,
    border: "1px solid rgba(127,127,127,0.25)",
    background: "var(--color-card, #fff)",
  },
} as const;

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [days, setDays] = useState<number>(30);
  const { data, error, isLoading, mutate } = useSWR<AnalyticsResponse>(
    `/api/v1/analytics?days=${days}`,
    swrFetcher,
  );

  const rangePicker = (
    <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/60" data-tour="analytics-range">
      {RANGE_OPTIONS.map((opt) => (
        <button
          key={opt.days}
          type="button"
          onClick={() => setDays(opt.days)}
          className={cn(
            "px-3 h-7 rounded-md text-xs font-medium transition-colors",
            days === opt.days
              ? "bg-card text-foreground ring-1 ring-border shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );

  if (error) {
    return (
      <div className="p-6">
        <PageHeader title="Analytics" subtitle="Usage and workflow metrics." actions={rangePicker} />
        <ErrorState
          title="Failed to load analytics"
          description="Could not retrieve metrics. Please try again."
          onRetry={mutate}
        />
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="p-6">
        <PageHeader title="Analytics" subtitle="Usage and workflow metrics." actions={rangePicker} />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <StatCardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  const { token_usage: tu, email_volume: ev, draft_workflow: dw, escalations: es } = data;

  // ── Derived values ──────────────────────────────────────────────────────────
  const todayTotal = tu.today_input_tokens + tu.today_output_tokens;
  const budgetPct = tu.daily_budget > 0 ? Math.min(100, (todayTotal / tu.daily_budget) * 100) : 0;
  const rangeTokens = tu.daily.reduce((acc, d) => acc + d.input_tokens + d.output_tokens, 0);

  const tokenSeries = tu.daily.map((d) => ({ ...d, label: shortDate(d.date) }));
  const threadSeries = ev.threads_per_day.map((d) => ({ ...d, label: shortDate(d.date) }));
  const escalationSeries = es.created_per_day.map((d) => ({ ...d, label: shortDate(d.date) }));

  const categoryData = Object.entries(ev.by_category)
    .map(([key, value]) => ({
      name: CATEGORY_LABELS[key as EmailCategory] ?? key,
      value,
    }))
    .sort((a, b) => b.value - a.value);

  const tierData = Object.entries(ev.by_tier)
    .map(([key, value]) => ({ name: TIER_LABELS[key] ?? key, value }))
    .sort((a, b) => b.value - a.value);

  const draftStatusData = DRAFT_STATUS_ORDER.filter((s) => dw.by_status[s]).map((s) => ({
    name: s.replace("_", " "),
    value: dw.by_status[s],
  }));

  const severityData = Object.entries(es.by_severity)
    .map(([key, value]) => ({
      name: SEVERITY_LABELS[key as EscalationSeverity] ?? key,
      value,
    }))
    .sort((a, b) => b.value - a.value);

  const editRate = dw.total > 0 ? Math.round((dw.edited_count / dw.total) * 100) : 0;

  return (
    <div className="p-6 space-y-8">
      <PageHeader
        title="Analytics"
        subtitle={`Usage and workflow metrics over the last ${data.days} days.`}
        actions={rangePicker}
      />

      {/* ── AI Token Usage ──────────────────────────────────────────────────── */}
      <section data-tour="analytics-tokens">
        <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">AI Token Usage</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <StatCard
            icon={Cpu}
            label="Used today"
            value={compact(todayTotal)}
            hint={
              tu.daily_budget > 0
                ? `${budgetPct.toFixed(0)}% of the ${compact(tu.daily_budget)}/day budget`
                : "No daily budget configured"
            }
            tone={budgetPct >= 90 ? "danger" : budgetPct >= 70 ? "warn" : "default"}
          />
          <StatCard
            icon={Cpu}
            label={`Total (${data.days}d)`}
            value={compact(rangeTokens)}
            hint="Input + output tokens, all AI calls"
          />
          <StatCard
            icon={Flame}
            label="Budget exhausted"
            value={`${tu.budget_exhausted_days}d`}
            hint="Days the daily cap was fully used"
            tone={tu.budget_exhausted_days > 0 ? "warn" : "default"}
          />
          <StatCard
            icon={Send}
            label="Output share"
            value={
              rangeTokens > 0
                ? `${Math.round(
                    (tu.daily.reduce((a, d) => a + d.output_tokens, 0) / rangeTokens) * 100,
                  )}%`
                : "—"
            }
            hint="Output tokens cost more than input"
          />
        </div>
        {/* Budget progress bar for today */}
        {tu.daily_budget > 0 && (
          <div className="bg-card border border-border rounded-xl p-4 mb-4">
            <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
              <span>Today&apos;s budget</span>
              <span className="tabular-nums">
                {compact(todayTotal)} / {compact(tu.daily_budget)} tokens
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  budgetPct >= 90 ? "bg-rose-500" : budgetPct >= 70 ? "bg-amber-500" : "bg-primary",
                )}
                style={{ width: `${budgetPct}%` }}
              />
            </div>
            <p className="text-[11px] text-muted-foreground mt-2">
              Resets at midnight UTC. When exhausted, categorization falls back to keyword rules and
              drafting pauses until reset.
            </p>
          </div>
        )}
        <ChartCard title="Daily token usage" subtitle="Stacked input + output tokens per day">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={tokenSeries} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(127,127,127,0.15)" vertical={false} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={24} />
              <YAxis {...axisProps} tickFormatter={(v: number) => compact(v)} />
              <Tooltip {...tooltipStyle} formatter={(v) => compact(Number(v))} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="input_tokens" name="Input" stackId="t" fill={COLOR_INPUT} radius={[0, 0, 0, 0]} />
              <Bar dataKey="output_tokens" name="Output" stackId="t" fill={COLOR_OUTPUT} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      {/* ── Email Volume ────────────────────────────────────────────────────── */}
      <section data-tour="analytics-volume">
        <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">Email Volume</h2>
        <div className="grid lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <ChartCard
              title="Incoming threads per day"
              subtitle={`${ev.total_threads} new conversation${ev.total_threads === 1 ? "" : "s"} in range`}
            >
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={threadSeries} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
                  <defs>
                    <linearGradient id="threadFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={COLOR_INPUT} stopOpacity={0.25} />
                      <stop offset="100%" stopColor={COLOR_INPUT} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(127,127,127,0.15)" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={24} />
                  <YAxis {...axisProps} allowDecimals={false} />
                  <Tooltip {...tooltipStyle} />
                  <Area
                    type="monotone"
                    dataKey="count"
                    name="Threads"
                    stroke={COLOR_INPUT}
                    strokeWidth={2}
                    fill="url(#threadFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
          <ChartCard title="By category" subtitle="Where the volume comes from">
            {categoryData.length === 0 ? (
              <EmptyChart label="No threads in range" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={categoryData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={48}
                    outerRadius={75}
                    paddingAngle={2}
                    strokeWidth={0}
                  >
                    {categoryData.map((_, i) => (
                      <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltipStyle} />
                  <Legend
                    wrapperStyle={{ fontSize: 10 }}
                    layout="horizontal"
                    verticalAlign="bottom"
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </ChartCard>
        </div>
        {tierData.length > 0 && (
          <div className="mt-4">
            <ChartCard title="Triage tiers" subtitle="How incoming email is routed">
              <ResponsiveContainer width="100%" height={120}>
                <BarChart data={tierData} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 24 }}>
                  <XAxis type="number" {...axisProps} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" {...axisProps} width={110} />
                  <Tooltip {...tooltipStyle} />
                  <Bar dataKey="value" name="Threads" fill={COLOR_INPUT} radius={[0, 3, 3, 0]} barSize={16} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
        )}
      </section>

      {/* ── Draft Workflow ──────────────────────────────────────────────────── */}
      <section data-tour="analytics-drafts">
        <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">Draft Workflow</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <StatCard icon={Inbox} label="Drafts generated" value={String(dw.total)} hint="AI drafts created in range" />
          <StatCard icon={Send} label="Sent" value={String(dw.sent_count)} hint="Reached a client" />
          <StatCard
            icon={FileEdit}
            label="Edit rate"
            value={`${editRate}%`}
            hint="Drafts staff modified before sending — lower is better as the AI learns"
          />
          <StatCard
            icon={XCircle}
            label="Rejected"
            value={String(dw.rejected_count)}
            hint="Includes regenerations"
            tone={dw.rejected_count > dw.sent_count ? "warn" : "default"}
          />
        </div>
        {draftStatusData.length > 0 && (
          <ChartCard title="Drafts by status" subtitle="Current state of every draft created in range">
            <ResponsiveContainer width="100%" height={140}>
              <BarChart
                data={draftStatusData}
                layout="vertical"
                margin={{ top: 0, right: 16, bottom: 0, left: 24 }}
              >
                <XAxis type="number" {...axisProps} allowDecimals={false} />
                <YAxis type="category" dataKey="name" {...axisProps} width={80} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="value" name="Drafts" radius={[0, 3, 3, 0]} barSize={14}>
                  {draftStatusData.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
      </section>

      {/* ── Escalations ─────────────────────────────────────────────────────── */}
      <section data-tour="analytics-escalations">
        <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">Escalations</h2>
        <div className="grid lg:grid-cols-3 gap-4">
          <div className="space-y-4">
            <StatCard
              icon={AlertTriangle}
              label="Open right now"
              value={String(es.open_count)}
              hint="Pending + acknowledged, all time"
              tone={es.open_count > 0 ? "warn" : "default"}
            />
            <ChartCard title="By severity" subtitle="Escalations created in range">
              {severityData.length === 0 ? (
                <EmptyChart label="No escalations in range" />
              ) : (
                <ul className="space-y-2">
                  {severityData.map((s, i) => (
                    <li key={s.name} className="flex items-center gap-2 text-xs">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ background: PALETTE[i % PALETTE.length] }}
                      />
                      <span className="flex-1 text-muted-foreground">{s.name}</span>
                      <span className="tabular-nums font-medium text-foreground">{s.value}</span>
                    </li>
                  ))}
                </ul>
              )}
            </ChartCard>
          </div>
          <div className="lg:col-span-2">
            <ChartCard title="Escalations per day" subtitle="Items routed to Jane's queue">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={escalationSeries} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(127,127,127,0.15)" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={24} />
                  <YAxis {...axisProps} allowDecimals={false} />
                  <Tooltip {...tooltipStyle} />
                  <Bar dataKey="count" name="Escalations" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
        </div>
      </section>
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-[220px] flex items-center justify-center">
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
