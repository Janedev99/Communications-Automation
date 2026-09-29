"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { EscalationList } from "@/components/escalations/escalation-list";
import { Pagination } from "@/components/shared/pagination";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useEscalations } from "@/hooks/use-escalations";
import { useDashboard } from "@/hooks/use-dashboard";

export default function EscalationsPage() {
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [page, setPage] = useState(1);

  // "active" (pending + acknowledged) is filtered by the server, so the page
  // total and pagination are correct and a "Start clean" reset is honoured.
  const isActiveView = status === "active";
  const apiStatus = isActiveView || status === "all" ? undefined : status;

  const { stats } = useDashboard();
  const cutoffActive = Boolean(stats?.todo_cutoff_at);

  const { escalations, total, isLoading, isError, mutate } = useEscalations({
    status: apiStatus,
    severity: severity || undefined,
    active: isActiveView,
    includeHidden: showHidden,
    page,
    page_size: 25,
  });

  const handleFilterChange = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(1);
  };

  return (
    <div>
      <PageHeader
        title="Escalations"
        subtitle="Items flagged for the firm owner — IRS notices, complaints, and high-stakes threads."
      />

      <div className="bg-card rounded-xl border border-border p-3 mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={status} onValueChange={(v: string | null) => handleFilterChange(setStatus)(v ?? "active")}>
            <SelectTrigger className="w-[200px] h-9 text-sm">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">Pending + Acknowledged</SelectItem>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="acknowledged">Acknowledged</SelectItem>
              <SelectItem value="resolved">Resolved</SelectItem>
            </SelectContent>
          </Select>

          <Select value={severity || "all"} onValueChange={(v: string | null) => handleFilterChange(setSeverity)(!v || v === "all" ? "" : v)}>
            <SelectTrigger className="w-[160px] h-9 text-sm">
              <SelectValue placeholder="All severities" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All severities</SelectItem>
              <SelectItem value="low">Low</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="critical">Critical</SelectItem>
            </SelectContent>
          </Select>

          {isActiveView && cutoffActive && (
            <div className="flex items-center gap-2 pl-1">
              <Switch
                id="show-reset-escalations"
                checked={showHidden}
                onCheckedChange={(checked: boolean) => {
                  setShowHidden(checked);
                  setPage(1);
                }}
                aria-label="Show escalations cleared by Start clean"
              />
              <label
                htmlFor="show-reset-escalations"
                className="text-sm text-muted-foreground cursor-pointer"
              >
                Show items cleared by &ldquo;Start clean&rdquo;
              </label>
            </div>
          )}
        </div>
      </div>

      {isError ? (
        <ErrorState
          title="Failed to load escalations"
          description="Could not retrieve escalations. Please try again."
          onRetry={mutate}
        />
      ) : isLoading ? (
        <TableSkeleton rows={6} />
      ) : (
        <>
          <EscalationList escalations={escalations} onRefresh={mutate} />
          <Pagination
            page={page}
            pageSize={25}
            total={total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
