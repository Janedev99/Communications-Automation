"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Mail, AlertTriangle, BookOpen, Send, FileText } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { DashboardSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { ThreadStatusBadge } from "@/components/emails/thread-status-badge";
import { useDashboard } from "@/hooks/use-dashboard";
import { useEmails } from "@/hooks/use-emails";
import { useEscalations } from "@/hooks/use-escalations";
import {
  SEVERITY_BADGE_CLASSES,
  SEVERITY_LABELS,
} from "@/lib/constants";
import { cn, relativeTime, truncate } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
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

  const pendingEmails =
    (stats?.threads_by_status["new"] ?? 0) +
    (stats?.threads_by_status["categorized"] ?? 0);

  const statCards = [
    {
      label: "Pending Emails",
      value: pendingEmails,
      sub: `+${stats?.last_24h.new_threads ?? 0} today`,
      href: "/emails",
      accent: "border-l-blue-400",
      icon: Mail,
    },
    {
      label: "Drafts to Review",
      value: stats?.drafts.pending_review ?? 0,
      sub: "Awaiting approval",
      href: "/emails?status=pending_review",
      accent: "border-l-amber-400",
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
      accent: "border-l-red-400",
      icon: AlertTriangle,
    },
    {
      label: "Sent Today",
      value: stats?.drafts.sent_today ?? 0,
      sub: "Emails sent",
      href: "/emails?status=sent",
      accent: "border-l-emerald-400",
      icon: Send,
    },
    {
      label: "Knowledge Base",
      value: stats?.knowledge_entries_active ?? 0,
      sub: "Active entries",
      href: "/knowledge",
      accent: "border-l-violet-400",
      icon: BookOpen,
    },
  ];

  if (statsLoading && threadsLoading && escalationsLoading) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <DashboardSkeleton />
      </>
    );
  }

  return (
    <div>
      <PageHeader title="Dashboard" />

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-4">
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
                "bg-white rounded-lg border border-gray-200 p-5 border-l-4 cursor-pointer",
                "hover:shadow-sm hover:border-gray-300 transition-all duration-150",
                card.accent
              )}
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {card.label}
                  </p>
                  <p className="text-2xl font-bold text-gray-800 mt-1">{card.value}</p>
                  <p className="text-xs text-gray-400 mt-2">{card.sub}</p>
                </div>
                <Icon className="w-5 h-5 text-gray-300 mt-0.5" strokeWidth={1.5} />
              </div>
            </Link>
          );
        })}
      </div>

      {/* Two-column section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        {/* Recent Threads */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Recent Threads</h2>
            <Link
              href="/emails"
              className="text-xs text-brand-500 hover:text-brand-600 transition-colors"
            >
              View all
            </Link>
          </div>
          <div className="bg-white rounded-lg border border-gray-200">
            {threadsLoading ? (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-gray-400">Loading...</p>
              </div>
            ) : threadsError ? (
              <ErrorState
                title="Failed to load threads"
                description="Could not retrieve recent email threads."
                onRetry={mutateThreads}
              />
            ) : threads.length === 0 ? (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-gray-400">No recent threads</p>
              </div>
            ) : (
              threads.map((thread) => (
                <div
                  key={thread.id}
                  className="px-4 py-3 border-b border-gray-100 last:border-b-0 hover:bg-gray-50/60 cursor-pointer transition-colors"
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
                      <p className="text-sm font-medium text-gray-800 truncate max-w-[280px]">
                        {thread.subject}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {thread.client_name ?? thread.client_email} ·{" "}
                        {relativeTime(thread.updated_at)}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <ThreadStatusBadge status={thread.status} />
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Pending Escalations */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Pending Escalations</h2>
            <Link
              href="/escalations"
              className="text-xs text-brand-500 hover:text-brand-600 transition-colors"
            >
              View all
            </Link>
          </div>
          <div className="bg-white rounded-lg border border-gray-200">
            {escalationsLoading ? (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-gray-400">Loading...</p>
              </div>
            ) : escalationsError ? (
              <ErrorState
                title="Failed to load escalations"
                description="Could not retrieve pending escalations."
                onRetry={mutateEscalations}
              />
            ) : escalations.length === 0 ? (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-gray-400">No pending escalations</p>
              </div>
            ) : (
              escalations.map((esc) => (
                <div
                  key={esc.id}
                  className="px-4 py-3 border-b border-gray-100 last:border-b-0 hover:bg-gray-50/60 cursor-pointer transition-colors"
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
                      <p className="text-sm font-medium text-gray-800 truncate">
                        {esc.thread_subject ?? `Thread ${esc.thread_id.slice(0, 8)}…`}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5 truncate">
                        {truncate(esc.reason, 60)}
                      </p>
                    </div>
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-xs font-medium flex-shrink-0",
                        SEVERITY_BADGE_CLASSES[esc.severity]
                      )}
                    >
                      {SEVERITY_LABELS[esc.severity]}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
