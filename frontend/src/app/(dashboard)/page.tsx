"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Mail, AlertTriangle, BookOpen, Send, FileText, Cpu, Activity, Inbox } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { SectionHeader } from "@/components/layout/section-header";
import { DashboardSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { ThreadStatusBadge } from "@/components/emails/thread-status-badge";
import { SystemStatusStrip } from "@/components/dashboard/system-status-strip";
import { TierBreakdownCard } from "@/components/dashboard/tier-breakdown-card";
import { useDashboard } from "@/hooks/use-dashboard";
import { useEmails } from "@/hooks/use-emails";
import { useEscalations } from "@/hooks/use-escalations";
import { useActivity } from "@/hooks/use-activity";
import { useUser } from "@/hooks/use-user";
import {
  SEVERITY_BADGE_CLASSES,
  SEVERITY_LABELS,
} from "@/lib/constants";
import { cn, relativeTime, truncate } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
  const { user, isAdmin } = useUser();
  const { stats, isLoading: statsLoading, isError: statsError, mutate: mutateStats } = useDashboard();
  const { threads, isLoading: threadsLoading, isError: threadsError, mutate: mutateThreads } = useEmails({
    page: 1,
    page_size: 5,
  });
  const { escalations, isLoading: escalationsLoading, isError: escalationsError, mutate: mutateEscalations } = useEscalations({
    page: 1,
    page_size: 5,
    status: "pending",
  });
  const { items: activityItems, isLoading: activityLoading } = useActivity(20);

  const pendingEmails =
    (stats?.threads_by_status["new"] ?? 0) +
    (stats?.threads_by_status["categorized"] ?? 0);

  const statCards = [
    {
      label: "Pending Emails",
      value: pendingEmails,
      sub: `+${stats?.last_24h.new_threads ?? 0} today`,
      href: "/emails",
      tone: "blue",
      icon: Mail,
    },
    {
      label: "Drafts to Review",
      value: stats?.drafts.pending_review ?? 0,
      sub: "Awaiting approval",
      href: "/emails?status=pending_review",
      tone: "amber",
      icon: FileText,
    },
    {
      label: "Open Escalations",
      value: stats?.totals.pending_escalations ?? 0,
      sub:
        (stats?.escalations_by_severity["critical"] ?? 0) > 0
          ? `${stats?.escalations_by_severity["critical"]} critical`
          : "No critical",
      href: "/escalations",
      tone: "red",
      icon: AlertTriangle,
    },
    {
      label: "Sent Today",
      value: stats?.drafts.sent_today ?? 0,
      sub: "Emails sent",
      href: "/emails?status=sent",
      tone: "emerald",
      icon: Send,
    },
    {
      label: "Knowledge Base",
      value: stats?.knowledge_entries_active ?? 0,
      sub: "Active entries",
      href: "/knowledge",
      tone: "violet",
      icon: BookOpen,
    },
  ] as const;

  const TONE_STYLES: Record<
    "blue" | "amber" | "red" | "emerald" | "violet",
    string
  > = {
    blue: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    red: "bg-destructive/10 text-destructive",
    emerald: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    violet: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  };

  if (statsLoading && threadsLoading && escalationsLoading) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <DashboardSkeleton />
      </>
    );
  }

  const aiUsage = stats?.ai_usage;
  const costFormatted = aiUsage
    ? aiUsage.estimated_cost_usd < 0.01
      ? "<$0.01"
      : `$${aiUsage.estimated_cost_usd.toFixed(2)}`
    : null;

  return (
    <div>
      <PageHeader
        title={`Welcome back${user?.name ? `, ${user.name.split(" ")[0]}` : ""}`}
        subtitle="An overview of email activity, drafts, and items needing attention."
      />

      {/* System status strip */}
      <SystemStatusStrip />

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {statsLoading ? (
          <div className="col-span-full">
            <DashboardSkeleton />
          </div>
        ) : statsError ? (
          <div className="col-span-full">
            <ErrorState
              title="Failed to load stats"
              description="Could not retrieve dashboard statistics."
              onRetry={mutateStats}
            />
          </div>
        ) : statCards.map((card) => {
          const Icon = card.icon;
          return (
            <Link
              key={card.label}
              href={card.href}
              className={cn(
                "group bg-card rounded-xl border border-border p-4",
                "hover:border-foreground/15 hover:shadow-sm transition-all duration-150",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <span
                  className={cn(
                    "flex items-center justify-center w-9 h-9 rounded-lg shrink-0",
                    TONE_STYLES[card.tone],
                  )}
                  aria-hidden="true"
                >
                  <Icon className="w-4 h-4" strokeWidth={1.75} />
                </span>
                <span
                  className="text-xs text-muted-foreground/70 group-hover:text-muted-foreground transition-colors"
                  aria-hidden="true"
                >
                  →
                </span>
              </div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-3">
                {card.label}
              </p>
              <p className="text-3xl font-semibold tracking-tight text-foreground mt-1 tabular-nums">
                {card.value}
              </p>
              <p className="text-xs text-muted-foreground mt-1.5">{card.sub}</p>
            </Link>
          );
        })}
      </div>

      {/* Tier breakdown — Phase 3 */}
      <div className="mt-4">
        <TierBreakdownCard
          countsByTier={stats?.threads_by_tier}
          isLoading={statsLoading}
        />
      </div>

      {/* AI Usage card — admin only */}
      {isAdmin && aiUsage && (
        <div className="mt-4">
          <div className="bg-card rounded-xl border border-border px-5 py-4 flex items-center gap-4">
            <span
              className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0"
              aria-hidden="true"
            >
              <Cpu className="w-5 h-5" strokeWidth={1.75} />
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                AI Usage · This Month
              </p>
              <p className="text-sm font-semibold text-foreground mt-0.5">
                <span className="tabular-nums">{aiUsage.calls_this_month}</span> AI draft
                {aiUsage.calls_this_month !== 1 ? "s" : ""} generated
                {costFormatted && (
                  <span className="text-muted-foreground font-normal"> · estimated {costFormatted}</span>
                )}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 tabular-nums">
                {aiUsage.prompt_tokens.toLocaleString()} prompt · {aiUsage.completion_tokens.toLocaleString()} completion
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Two-column section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        {/* Recent Threads */}
        <div>
          <SectionHeader
            title="Recent Threads"
            icon={Inbox}
            count={threads.length}
            viewAllHref="/emails"
          />
          <div className="bg-card rounded-xl border border-border overflow-hidden">
            {threadsLoading ? (
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-muted-foreground">Loading...</p>
              </div>
            ) : threadsError ? (
              <ErrorState
                title="Failed to load threads"
                description="Could not retrieve recent email threads."
                onRetry={mutateThreads}
              />
            ) : threads.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-muted-foreground">No recent threads</p>
              </div>
            ) : (
              <div className="divide-y divide-border/60">
                {threads.map((thread) => (
                  <div
                    key={thread.id}
                    className="px-4 py-3 hover:bg-accent/50 cursor-pointer transition-colors"
                    tabIndex={0}
                    role="button"
                    onClick={() => router.push(`/emails/${thread.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        router.push(`/emails/${thread.id}`);
                      }
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-foreground truncate">
                          {thread.subject}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">
                          {thread.client_name ?? thread.client_email}
                          <span className="mx-1.5 text-muted-foreground/50">·</span>
                          {relativeTime(thread.updated_at)}
                        </p>
                      </div>
                      <ThreadStatusBadge status={thread.status} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Pending Escalations */}
        <div>
          <SectionHeader
            title="Pending Escalations"
            icon={AlertTriangle}
            count={escalations.length}
            viewAllHref="/escalations"
          />
          <div className="bg-card rounded-xl border border-border overflow-hidden">
            {escalationsLoading ? (
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-muted-foreground">Loading...</p>
              </div>
            ) : escalationsError ? (
              <ErrorState
                title="Failed to load escalations"
                description="Could not retrieve pending escalations."
                onRetry={mutateEscalations}
              />
            ) : escalations.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-muted-foreground">No pending escalations — nice work.</p>
              </div>
            ) : (
              <div className="divide-y divide-border/60">
                {escalations.map((esc) => (
                  <div
                    key={esc.id}
                    className="px-4 py-3 hover:bg-accent/50 cursor-pointer transition-colors"
                    tabIndex={0}
                    role="button"
                    onClick={() => router.push("/escalations")}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        router.push("/escalations");
                      }
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-foreground truncate">
                          {esc.thread_subject ?? `Thread ${esc.thread_id.slice(0, 8)}…`}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {truncate(esc.reason, 80)}
                        </p>
                      </div>
                      <span
                        className={cn(
                          "rounded-full px-2.5 py-0.5 text-[11px] font-medium flex-shrink-0",
                          SEVERITY_BADGE_CLASSES[esc.severity]
                        )}
                      >
                        {SEVERITY_LABELS[esc.severity]}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Activity Feed */}
      <div className="mt-6">
        <SectionHeader title="Recent Activity" icon={Activity} />
        <div className="bg-card rounded-xl border border-border overflow-hidden">
          {activityLoading ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-muted-foreground">Loading...</p>
            </div>
          ) : activityItems.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-muted-foreground">No recent activity</p>
            </div>
          ) : (
            <div className="divide-y divide-border/60">
              {activityItems.map((item) => (
                <div key={item.id} className="px-4 py-2.5 flex items-center gap-3">
                  <span
                    className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 flex-shrink-0"
                    aria-hidden="true"
                  />
                  <p className="text-sm text-foreground/90 flex-1 min-w-0 truncate">
                    {item.description}
                  </p>
                  <span className="text-xs text-muted-foreground flex-shrink-0 whitespace-nowrap">
                    {relativeTime(item.created_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
