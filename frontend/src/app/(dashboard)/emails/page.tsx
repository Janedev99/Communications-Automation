"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Download, Search, X } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { EmailFilters } from "@/components/emails/email-filters";
import { EmailList } from "@/components/emails/email-list";
import { Pagination } from "@/components/shared/pagination";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { ExportDialog } from "@/components/emails/export-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useEmails, bulkAction } from "@/hooks/use-emails";
import { useUser } from "@/hooks/use-user";
import type { BulkActionRequest } from "@/lib/types";

export default function EmailsPage() {
  const searchParams = useSearchParams();
  const { isAdmin } = useUser();

  // Filter state — initialised from URL search params
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [category, setCategory] = useState(searchParams.get("category") ?? "");
  const [clientEmail, setClientEmail] = useState(searchParams.get("client_email") ?? "");
  const [assignedTo, setAssignedTo] = useState("");
  const [page, setPage] = useState(1);
  const [showExport, setShowExport] = useState(false);

  // Search state: local (immediate) and debounced (sent to API)
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  // Re-apply URL params if they change (e.g. navigating from thread detail)
  useEffect(() => {
    setClientEmail(searchParams.get("client_email") ?? "");
    setStatus(searchParams.get("status") ?? "");
    setCategory(searchParams.get("category") ?? "");
    setPage(1);
  }, [searchParams]);

  const isSearchActive = !!searchTerm;

  const { threads, total, isLoading, isError, mutate } = useEmails({
    status: isSearchActive ? undefined : (status || undefined),
    category: isSearchActive ? undefined : (category || undefined),
    client_email: isSearchActive ? undefined : (clientEmail || undefined),
    assigned_to: isSearchActive ? undefined : (assignedTo || undefined),
    search: searchTerm || undefined,
    page,
    page_size: 25,
  });

  // Clear selection whenever the thread list changes
  useEffect(() => {
    setSelectedIds(new Set());
  }, [threads]);

  const handleClear = () => {
    setStatus("");
    setCategory("");
    setClientEmail("");
    setAssignedTo("");
    setSearchInput("");
    setSearchTerm("");
    setPage(1);
  };

  const handleFilterChange = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(1);
  };

  const handleSearchInput = (value: string) => {
    setSearchInput(value);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      setSearchTerm(value);
      setPage(1);
    }, 500);
  };

  const handleClearSearch = () => {
    setSearchInput("");
    setSearchTerm("");
    setPage(1);
  };

  // Bulk selection
  const handleToggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (selectedIds.size === threads.length && threads.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(threads.map((t) => t.id)));
    }
  }, [selectedIds.size, threads]);

  const handleBulkClose = async () => {
    if (selectedIds.size === 0 || bulkLoading) return;
    setBulkLoading(true);
    try {
      const req: BulkActionRequest = {
        thread_ids: Array.from(selectedIds),
        action: "close",
      };
      await bulkAction(req);
      setSelectedIds(new Set());
      mutate();
    } finally {
      setBulkLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Emails"
        subtitle={
          clientEmail
            ? `Showing threads from: ${clientEmail}`
            : "Manage email threads and responses"
        }
        actions={
          isAdmin ? (
            <Button
              variant="outline"
              className="text-gray-600"
              onClick={() => setShowExport(true)}
            >
              <Download className="w-4 h-4 mr-1.5" />
              Export
            </Button>
          ) : undefined
        }
      />

      {/* Global search bar */}
      <div className="relative mb-3">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        <Input
          value={searchInput}
          onChange={(e) => handleSearchInput(e.target.value)}
          placeholder="Search by subject, client, summary, or message content..."
          className="pl-9 h-9 text-sm"
        />
        {searchInput && (
          <button
            onClick={handleClearSearch}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Clear search"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Column filters — hidden during active search to avoid conflicting signals */}
      {!isSearchActive && (
        <EmailFilters
          status={status}
          category={category}
          clientEmail={clientEmail}
          assignedTo={assignedTo}
          onStatusChange={handleFilterChange(setStatus)}
          onCategoryChange={handleFilterChange(setCategory)}
          onClientEmailChange={handleFilterChange(setClientEmail)}
          onAssignedToChange={handleFilterChange(setAssignedTo)}
          onClear={handleClear}
        />
      )}

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 mb-3 px-3 py-2 bg-brand-50 border border-brand-200 rounded-lg">
          <span className="text-sm text-brand-700 font-medium">
            {selectedIds.size} thread{selectedIds.size !== 1 ? "s" : ""} selected
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={handleBulkClose}
            disabled={bulkLoading}
            className="h-7 text-xs"
          >
            {bulkLoading ? "Closing..." : "Close Selected"}
          </Button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto text-xs text-brand-500 hover:text-brand-700 transition-colors"
          >
            Clear selection
          </button>
        </div>
      )}

      {isError ? (
        <ErrorState
          title="Failed to load emails"
          description="Could not retrieve email threads. Please try again."
          onRetry={mutate}
        />
      ) : isLoading ? (
        <TableSkeleton rows={8} />
      ) : (
        <>
          <EmailList
            threads={threads}
            selectedIds={selectedIds}
            onToggleSelect={handleToggleSelect}
            onSelectAll={handleSelectAll}
          />
          <Pagination
            page={page}
            pageSize={25}
            total={total}
            onPageChange={setPage}
          />
        </>
      )}

      {isAdmin && (
        <ExportDialog open={showExport} onOpenChange={setShowExport} />
      )}
    </div>
  );
}
