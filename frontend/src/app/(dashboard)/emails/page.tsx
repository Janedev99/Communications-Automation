"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Bookmark, Download, PenSquare, Search, ShieldX, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page-header";
import { EmailFilters } from "@/components/emails/email-filters";
import { EmailList } from "@/components/emails/email-list";
import { TierLanesNav, type TierFilter } from "@/components/emails/tier-lanes-nav";
import { FolderTabsNav, type MailFolder } from "@/components/emails/folder-tabs-nav";
import { Pagination } from "@/components/shared/pagination";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { ExportDialog } from "@/components/emails/export-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { BulkSaveDialog } from "@/components/emails/bulk-save-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useEmails, bulkAction } from "@/hooks/use-emails";
import { useDashboard } from "@/hooks/use-dashboard";
import { useUser } from "@/hooks/use-user";
import { useCompose } from "@/components/emails/compose-context";
import type { BulkActionRequest, ThreadTier } from "@/lib/types";

function parseTierParam(raw: string | null): TierFilter {
  if (raw === "t1_auto" || raw === "t2_review" || raw === "t3_escalate") return raw;
  return "all";
}

// Per-session memory of the email list view, so returning from a thread lands
// the user where they left off (page, folder, filters) instead of resetting to
// page 1 / inbox. sessionStorage (not localStorage) — it's a within-session
// convenience, not a durable preference.
const VIEW_STATE_KEY = "emails_view_state";

interface SavedEmailsView {
  page: number;
  folder: MailFolder;
  status: string;
  category: string;
  tier: TierFilter;
  clientEmail: string;
  assignedTo: string;
}

function readSavedView(): Partial<SavedEmailsView> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(VIEW_STATE_KEY);
    return raw ? (JSON.parse(raw) as Partial<SavedEmailsView>) : {};
  } catch {
    return {};
  }
}

export default function EmailsPage() {
  const searchParams = useSearchParams();
  const { isAdmin } = useUser();
  const { openCompose } = useCompose();

  // Initial view: an explicit deep-link (e.g. ?client_email=) wins and starts at
  // page 1; otherwise restore the last view from sessionStorage so returning
  // from a thread lands where the user left off.
  const [initialView] = useState(() => {
    const urlClientEmail = searchParams.get("client_email") ?? "";
    const urlStatus = searchParams.get("status") ?? "";
    const urlCategory = searchParams.get("category") ?? "";
    const urlTier = searchParams.get("tier");
    if (urlClientEmail || urlStatus || urlCategory || urlTier) {
      return {
        page: 1,
        folder: "inbox" as MailFolder,
        status: urlStatus,
        category: urlCategory,
        tier: parseTierParam(urlTier),
        clientEmail: urlClientEmail,
        assignedTo: "",
      };
    }
    const saved = readSavedView();
    return {
      page: saved.page ?? 1,
      folder: saved.folder ?? ("inbox" as MailFolder),
      status: saved.status ?? "",
      category: saved.category ?? "",
      tier: saved.tier ?? ("all" as TierFilter),
      clientEmail: saved.clientEmail ?? "",
      assignedTo: saved.assignedTo ?? "",
    };
  });

  // Filter + list-position state (seeded from initialView above)
  const [status, setStatus] = useState(initialView.status);
  const [category, setCategory] = useState(initialView.category);
  const [tier, setTier] = useState<TierFilter>(initialView.tier);
  const [clientEmail, setClientEmail] = useState(initialView.clientEmail);
  const [assignedTo, setAssignedTo] = useState(initialView.assignedTo);
  const [page, setPage] = useState(initialView.page);
  const [folder, setFolder] = useState<MailFolder>(initialView.folder);
  const [showExport, setShowExport] = useState(false);

  // Search state: local (immediate) and debounced (sent to API)
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // Which bulk action is in flight (null = idle). Tracking the specific action,
  // not a bare boolean, lets each control show its own busy state instead of
  // the spinner always landing on the "Resolve" button.
  const [bulkPending, setBulkPending] = useState<BulkActionRequest["action"] | null>(null);
  const [showBulkSpam, setShowBulkSpam] = useState(false);
  const [showBulkDelete, setShowBulkDelete] = useState(false);
  const [showBulkSave, setShowBulkSave] = useState(false);

  // Re-apply URL params only on a *genuine* query-string change (e.g. clicking a
  // client link while already on this page). Comparing the actual string —
  // rather than a first-render flag — avoids clobbering the restored view on
  // mount and is resilient to StrictMode's double-invoked effects.
  const lastParamsRef = useRef<string | null>(null);
  useEffect(() => {
    const current = searchParams.toString();
    if (lastParamsRef.current === null) {
      // Mount: initialView already reflects the URL / saved view — just record.
      lastParamsRef.current = current;
      return;
    }
    if (lastParamsRef.current === current) return;
    lastParamsRef.current = current;
    setClientEmail(searchParams.get("client_email") ?? "");
    setStatus(searchParams.get("status") ?? "");
    setCategory(searchParams.get("category") ?? "");
    setTier(parseTierParam(searchParams.get("tier")));
    setFolder("inbox");
    setPage(1);
  }, [searchParams]);

  // Persist the view so returning from a thread restores page / folder / filters.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(
        VIEW_STATE_KEY,
        JSON.stringify({ page, folder, status, category, tier, clientEmail, assignedTo }),
      );
    } catch {
      // sessionStorage can throw (private mode / quota) — non-fatal.
    }
  }, [page, folder, status, category, tier, clientEmail, assignedTo]);

  const isSearchActive = !!searchTerm;
  const isInbox = folder === "inbox";
  const isSent = folder === "sent";

  const { threads, total, isLoading, isError, mutate } = useEmails({
    // Spam / Deleted folders map straight to the status query. Sent maps to the
    // sent_only flag (threads with an outbound message), independent of status.
    // The inbox uses the status dropdown (which no longer offers deleted/spam)
    // and relies on the backend's default exclusion of those terminal states.
    status: isInbox
      ? (isSearchActive ? undefined : status || undefined)
      : isSent
      ? undefined
      : folder,
    sentOnly: isSent || undefined,
    category: !isInbox || isSearchActive ? undefined : category || undefined,
    tier: !isInbox || isSearchActive || tier === "all" ? undefined : (tier as ThreadTier),
    client_email: !isInbox || isSearchActive ? undefined : clientEmail || undefined,
    assigned_to: !isInbox || isSearchActive ? undefined : assignedTo || undefined,
    search: isInbox ? searchTerm || undefined : undefined,
    page,
    page_size: 25,
  });

  // Pull tier counts from dashboard stats. SWR caches this independently from the
  // emails list, so changing tier doesn't refetch counts.
  const { stats } = useDashboard();
  const tierCounts = stats?.threads_by_tier;
  const tierTotal = stats?.totals.threads;

  // Clear selection whenever the thread list changes
  useEffect(() => {
    setSelectedIds(new Set());
  }, [threads]);

  const handleClear = () => {
    setStatus("");
    setCategory("");
    setTier("all");
    setClientEmail("");
    setAssignedTo("");
    setSearchInput("");
    setSearchTerm("");
    setPage(1);
  };

  const handleTierChange = (next: TierFilter) => {
    setTier(next);
    setPage(1);
  };

  const handleFolderChange = (next: MailFolder) => {
    setFolder(next);
    setSelectedIds(new Set());
    // Search is an inbox-only tool; leaving the Inbox clears it so a Spam /
    // Deleted view isn't silently still filtered by a stale search term.
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

  const runBulkAction = async (
    action: BulkActionRequest["action"],
    params?: BulkActionRequest["params"],
  ) => {
    if (selectedIds.size === 0 || bulkPending !== null) return;
    setBulkPending(action);
    try {
      const res = await bulkAction({
        thread_ids: Array.from(selectedIds),
        action,
        params,
      });
      setSelectedIds(new Set());
      mutate();
      const verb: Record<string, string> = {
        close: "Resolved",
        delete: "Deleted",
        spam: "Marked as spam",
        save: "Saved",
      };
      const n = res.succeeded;
      toast.success(`${verb[action] ?? "Updated"} ${n} thread${n === 1 ? "" : "s"}.`);
      if (res.failed > 0) {
        toast.error(
          `${res.failed} thread${res.failed === 1 ? "" : "s"} could not be processed.`,
        );
      }
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Bulk action failed.");
    } finally {
      setBulkPending(null);
      setShowBulkSpam(false);
      setShowBulkDelete(false);
      setShowBulkSave(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Emails"
        subtitle={
          clientEmail
            ? `Showing threads from ${clientEmail}.`
            : "Triage incoming threads, review AI drafts, and approve sends."
        }
        actions={
          <div className="flex items-center gap-2">
            {isAdmin && (
              <Button variant="outline" onClick={() => setShowExport(true)}>
                <Download className="w-4 h-4 mr-1.5" aria-hidden="true" />
                Export
              </Button>
            )}
            <Button onClick={() => openCompose()}>
              <PenSquare className="w-4 h-4 mr-1.5" aria-hidden="true" />
              New Email
            </Button>
          </div>
        }
      />

      {/* Mail folders — Inbox (working view) vs Spam / Deleted read views */}
      <FolderTabsNav active={folder} onChange={handleFolderChange} />

      {/* Context note for the non-inbox folders */}
      {!isInbox && (
        <p className="text-xs text-muted-foreground mb-3 -mt-1">
          {folder === "sent"
            ? "Threads you've sent mail in — composed emails and approved replies."
            : folder === "spam"
            ? "Junk mail — hidden from your inbox. Restore from Outlook's Junk Email folder if needed."
            : "Deleted threads — hidden from your inbox. Restore from Outlook's Deleted Items folder if needed."}
        </p>
      )}

      {/* Tier lanes — inbox only, and hidden during search */}
      {isInbox && !isSearchActive && (
        <TierLanesNav
          active={tier}
          counts={tierCounts}
          total={tierTotal}
          onChange={handleTierChange}
        />
      )}

      {/* Global search bar — inbox only (search spans all threads regardless
          of folder, so it would be misleading inside Spam / Deleted views) */}
      {isInbox && (
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          <Input
            value={searchInput}
            onChange={(e) => handleSearchInput(e.target.value)}
            placeholder="Search by subject, client, summary, or message content..."
            className="pl-9 h-9 text-sm"
          />
          {searchInput && (
            <button
              onClick={handleClearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground transition-colors"
              aria-label="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Column filters — inbox only, hidden during active search */}
      {isInbox && !isSearchActive && (
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

      {/* Bulk action bar — inbox only */}
      {isInbox && selectedIds.size > 0 && (
        <div className="flex items-center gap-3 mb-3 px-3.5 py-2 bg-primary/[0.07] border border-primary/30 rounded-lg">
          <span className="text-sm font-medium text-foreground">
            <span className="tabular-nums">{selectedIds.size}</span> thread
            {selectedIds.size !== 1 ? "s" : ""} selected
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              onClick={() => runBulkAction("close")}
              disabled={bulkPending !== null}
              className="h-7 text-xs"
            >
              {bulkPending === "close" ? "Working…" : "Resolve"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowBulkSave(true)}
              disabled={bulkPending !== null}
              className="h-7 text-xs gap-1.5"
            >
              <Bookmark className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
              Save
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowBulkSpam(true)}
              disabled={bulkPending !== null}
              className="h-7 text-xs gap-1.5 text-amber-700 dark:text-amber-300 hover:bg-amber-500/10"
            >
              <ShieldX className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
              Spam
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowBulkDelete(true)}
              disabled={bulkPending !== null}
              className="h-7 text-xs gap-1.5 text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
              Delete
            </Button>
          </div>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto text-xs font-medium text-primary hover:underline transition-colors"
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

      <ConfirmDialog
        open={showBulkSpam}
        onOpenChange={setShowBulkSpam}
        title={`Mark ${selectedIds.size} thread${selectedIds.size === 1 ? "" : "s"} as spam?`}
        description={
          "This moves every incoming message in the selected threads to the Junk Email " +
          "folder in Outlook and trains the junk filter on those senders. Sent replies are " +
          "not affected."
        }
        confirmLabel="Mark as spam"
        confirmVariant="destructive"
        loading={bulkPending === "spam"}
        onConfirm={() => runBulkAction("spam")}
      />

      <ConfirmDialog
        open={showBulkDelete}
        onOpenChange={setShowBulkDelete}
        title={`Delete ${selectedIds.size} thread${selectedIds.size === 1 ? "" : "s"}?`}
        description={
          "This moves every incoming message in the selected threads to Outlook's Deleted " +
          "Items. Sent replies are not affected. You can restore from Outlook if needed."
        }
        confirmLabel="Delete"
        confirmVariant="destructive"
        loading={bulkPending === "delete"}
        onConfirm={() => runBulkAction("delete")}
      />

      <BulkSaveDialog
        open={showBulkSave}
        onOpenChange={setShowBulkSave}
        count={selectedIds.size}
        loading={bulkPending === "save"}
        onConfirm={(folder) => runBulkAction("save", { folder })}
      />
    </div>
  );
}
