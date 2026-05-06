"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ChevronRight,
  Lock,
  Search,
  X,
  History,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { Pagination } from "@/components/shared/pagination";
import { Input } from "@/components/ui/input";
import { DiffRow } from "@/components/audit/diff-row";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { swrFetcher } from "@/lib/api";
import { useUser } from "@/hooks/use-user";
import { cn, formatDate, relativeTime } from "@/lib/utils";
import type { AuditLogEntry, AuditLogResponse } from "@/lib/types";

// Date-range chips → ISO `since` for the API
const RANGE_OPTIONS = [
  { id: "24h", label: "24h" },
  { id: "7d",  label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "all", label: "All time" },
] as const;

type RangeId = (typeof RANGE_OPTIONS)[number]["id"];

function rangeToSince(range: RangeId): string | undefined {
  const now = Date.now();
  switch (range) {
    case "24h": return new Date(now - 24 * 3600 * 1000).toISOString();
    case "7d":  return new Date(now - 7 * 24 * 3600 * 1000).toISOString();
    case "30d": return new Date(now - 30 * 24 * 3600 * 1000).toISOString();
    case "all": return undefined;
  }
}

// Action prefix → accent color for the colored dot in the row
const ACTION_DOT_COLOR: Record<string, string> = {
  auth: "bg-sky-500",
  email: "bg-violet-500",
  draft: "bg-emerald-500",
  escalation: "bg-red-500",
  knowledge: "bg-amber-500",
  user: "bg-pink-500",
  tier_rule: "bg-blue-500",
  session: "bg-muted-foreground",
};

function dotColor(action: string): string {
  const prefix = action.split(".")[0];
  return ACTION_DOT_COLOR[prefix] ?? "bg-muted-foreground";
}

function actorBadge(entry: AuditLogEntry): JSX.Element {
  if (!entry.user_name) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ring-1 ring-border bg-muted text-muted-foreground">
        System
      </span>
    );
  }
  return <span className="text-sm text-foreground">{entry.user_name}</span>;
}

interface RowProps {
  entry: AuditLogEntry;
  expanded: boolean;
  onToggle: () => void;
}

function AuditRow({ entry, expanded, onToggle }: RowProps) {
  const hasDetails = entry.details && Object.keys(entry.details).length > 0;
  const rowDate = formatDate(entry.created_at);

  return (
    <>
      <tr
        className={cn(
          "border-b border-border/60 transition-colors",
          expanded ? "bg-muted/40" : "hover:bg-accent/40",
          hasDetails && "cursor-pointer"
        )}
        onClick={hasDetails ? onToggle : undefined}
      >
        <td className="px-3 py-3 w-8 align-middle">
          {hasDetails ? (
            <ChevronRight
              className={cn(
                "w-4 h-4 text-muted-foreground transition-transform",
                expanded && "rotate-90"
              )}
            />
          ) : (
            <span className="block w-4" />
          )}
        </td>
        <td className="px-3 py-3 w-40 align-middle">
          <div className="flex items-center gap-2">
            <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", dotColor(entry.action))} />
            <span className="text-sm text-foreground" title={rowDate}>
              {relativeTime(entry.created_at)}
            </span>
          </div>
        </td>
        <td className="px-3 py-3 w-44 align-middle">{actorBadge(entry)}</td>
        <td className="px-3 py-3 align-middle">
          <span className="font-mono text-xs text-foreground">{entry.action}</span>
        </td>
        <td className="px-3 py-3 align-middle">
          <span className="text-xs text-muted-foreground">
            {entry.entity_type}
            {entry.entity_id && (
              <span className="ml-1 font-mono opacity-80">
                #{entry.entity_id.slice(0, 8)}
                {entry.entity_id.length > 8 && "…"}
              </span>
            )}
          </span>
        </td>
        <td className="px-3 py-3 w-12 text-center align-middle">
          {hasDetails && (
            <span
              className="inline-block w-1.5 h-1.5 rounded-full bg-primary"
              title="Has details"
            />
          )}
        </td>
      </tr>
      {expanded && hasDetails && (
        <tr className="bg-muted/40">
          <td />
          <td colSpan={5} className="px-3 pb-4">
            <DiffRow details={entry.details} />
            {entry.ip_address && (
              <p className="text-[11px] text-muted-foreground mt-2 font-mono">
                IP: {entry.ip_address}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function AuditLogPage() {
  const { isAdmin, isLoading: userLoading } = useUser();
  const [actionFilter, setActionFilter] = useState<string>("");
  const [entityFilter, setEntityFilter] = useState<string>("");
  const [actorFilter, setActorFilter] = useState<string>("");
  const [range, setRange] = useState<RangeId>("7d");
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const PAGE_SIZE = 50;

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => {
      setSearchTerm(searchInput);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
    setExpanded(new Set());
  }, [actionFilter, entityFilter, actorFilter, range]);

  // Build query string
  const queryString = useMemo(() => {
    const sp = new URLSearchParams();
    sp.set("page", String(page));
    sp.set("page_size", String(PAGE_SIZE));
    if (actionFilter) sp.set("action", actionFilter);
    if (entityFilter) sp.set("entity_type", entityFilter);
    if (actorFilter) sp.set("user_id", actorFilter);
    const since = rangeToSince(range);
    if (since) sp.set("since", since);
    if (searchTerm) sp.set("q", searchTerm);
    return sp.toString();
  }, [page, actionFilter, entityFilter, actorFilter, range, searchTerm]);

  const { data, error, isLoading, mutate } = useSWR<AuditLogResponse>(
    isAdmin ? `/api/v1/audit-log?${queryString}` : null,
    swrFetcher,
    { refreshInterval: 30_000 }
  );

  const { data: actions } = useSWR<string[]>(
    isAdmin ? "/api/v1/audit-log/actions" : null,
    swrFetcher
  );

  const { data: entityTypes } = useSWR<string[]>(
    isAdmin ? "/api/v1/audit-log/entities" : null,
    swrFetcher
  );

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleClearFilters = () => {
    setActionFilter("");
    setEntityFilter("");
    setActorFilter("");
    setRange("7d");
    setSearchInput("");
    setSearchTerm("");
    setPage(1);
  };

  const hasActiveFilter =
    !!actionFilter || !!entityFilter || !!actorFilter || !!searchTerm || range !== "7d";

  if (userLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <History className="w-5 h-5 text-muted-foreground animate-pulse" />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="bg-card border border-border rounded-lg p-8 text-center">
        <Lock className="w-10 h-10 text-muted-foreground mx-auto" strokeWidth={1.5} />
        <h2 className="text-lg font-semibold text-foreground mt-3">Admin access required</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Only admins can view the audit log.
        </p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Audit Log"
        subtitle="A complete record of every state-changing action — who, what, when, and before/after."
      />

      {/* Filters */}
      <div className="bg-card border border-border rounded-xl p-3 mb-4 space-y-3">
        {/* Top row: dropdowns + range chips */}
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={actionFilter || "__all__"}
            onValueChange={(v) => setActionFilter(v == null || v === "__all__" ? "" : v)}
          >
            <SelectTrigger className="w-[200px] h-8 text-xs">
              <SelectValue placeholder="Any action" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">Any action</SelectItem>
              {(actions ?? []).map((a) => (
                <SelectItem key={a} value={a}>
                  <span className="font-mono text-xs">{a}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={entityFilter || "__all__"}
            onValueChange={(v) => setEntityFilter(v == null || v === "__all__" ? "" : v)}
          >
            <SelectTrigger className="w-[160px] h-8 text-xs">
              <SelectValue placeholder="Any entity" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">Any entity</SelectItem>
              {(entityTypes ?? []).map((e) => (
                <SelectItem key={e} value={e}>
                  {e}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={actorFilter || "__all__"}
            onValueChange={(v) => setActorFilter(v == null || v === "__all__" ? "" : v)}
          >
            <SelectTrigger className="w-[140px] h-8 text-xs">
              <SelectValue placeholder="Any actor" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">Any actor</SelectItem>
              <SelectItem value="system">System only</SelectItem>
            </SelectContent>
          </Select>

          {/* Range chips */}
          <div className="flex items-center gap-1 ml-auto">
            {RANGE_OPTIONS.map((r) => (
              <button
                key={r.id}
                onClick={() => setRange(r.id)}
                className={cn(
                  "h-8 px-3 rounded-md text-xs font-medium transition-colors",
                  range === r.id
                    ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent"
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {/* Bottom row: search + clear */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search action, entity ID, or details payload…"
              className="pl-9 h-8 text-sm"
            />
            {searchInput && (
              <button
                onClick={() => setSearchInput("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {hasActiveFilter && (
            <button
              onClick={handleClearFilters}
              className="text-xs px-3 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Results */}
      {error ? (
        <ErrorState
          title="Failed to load audit log"
          description="Could not retrieve audit entries."
          onRetry={mutate}
        />
      ) : isLoading || !data ? (
        <TableSkeleton rows={8} />
      ) : data.items.length === 0 ? (
        <div className="bg-card border border-border rounded-xl p-12 text-center">
          <History
            className="w-10 h-10 text-muted-foreground/60 mx-auto"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <h3 className="text-sm font-semibold text-foreground mt-3">No audit entries</h3>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
            {hasActiveFilter
              ? "Nothing matches the current filters."
              : "No state changes have been logged yet."}
          </p>
          {hasActiveFilter && (
            <button
              onClick={handleClearFilters}
              className="text-sm font-medium text-primary hover:underline mt-3"
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-muted/40 border-b border-border">
                  <th className="px-3 py-2.5 w-8" />
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    When
                  </th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Who
                  </th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Action
                  </th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Entity
                  </th>
                  <th className="px-3 py-2.5 text-center text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Diff
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <AuditRow
                    key={entry.id}
                    entry={entry}
                    expanded={expanded.has(entry.id)}
                    onToggle={() => toggleExpand(entry.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={data.total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
