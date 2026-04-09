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
import { useEscalations } from "@/hooks/use-escalations";

export default function EscalationsPage() {
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);

  // "active" is a UI-only value meaning "pending + acknowledged"
  const apiStatus = status === "active" ? undefined : status === "all" ? undefined : status;

  const { escalations, total, isLoading, isError, mutate } = useEscalations({
    status: apiStatus,
    severity: severity || undefined,
    page,
    page_size: 25,
  });

  // Client-side filter for "active" (pending + acknowledged) since API may not support multi-value
  const filteredEscalations =
    status === "active"
      ? escalations.filter((e) => e.status === "pending" || e.status === "acknowledged")
      : escalations;

  // When "active" is selected, pagination total must reflect the filtered count,
  // not the unfiltered API total (which includes resolved escalations).
  const paginationTotal = status === "active" ? filteredEscalations.length : total;

  const handleFilterChange = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(1);
  };

  return (
    <div>
      <PageHeader
        title="Escalations"
        subtitle="Review and resolve escalated threads"
      />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Select value={status} onValueChange={(v: string | null) => handleFilterChange(setStatus)(v ?? "active")}>
          <SelectTrigger className="w-[180px] h-9 text-sm">
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
          <EscalationList escalations={filteredEscalations} onRefresh={mutate} />
          <Pagination
            page={page}
            pageSize={25}
            total={paginationTotal}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
