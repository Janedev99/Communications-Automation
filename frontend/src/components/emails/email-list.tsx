"use client";

import { useRouter } from "next/navigation";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AlertTriangle, Mail, UserCircle2 } from "lucide-react";
import { ThreadStatusBadge } from "./thread-status-badge";
import { CategoryBadge } from "./category-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { TierBadge } from "@/components/ui/tier-badge";
import { relativeTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { EmailThreadListItem } from "@/lib/types";

interface EmailListProps {
  threads: EmailThreadListItem[];
  selectedIds?: Set<string>;
  onToggleSelect?: (id: string) => void;
  onSelectAll?: () => void;
}

export function EmailList({
  threads,
  selectedIds = new Set(),
  onToggleSelect,
  onSelectAll,
}: EmailListProps) {
  const router = useRouter();
  const hasBulkMode = !!onToggleSelect;
  const allSelected = hasBulkMode && threads.length > 0 && selectedIds.size === threads.length;

  if (threads.length === 0) {
    return (
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <EmptyState
          icon={Mail}
          title="No threads found"
          description="Try adjusting your filters"
        />
      </div>
    );
  }

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/80 hover:bg-accent/80">
            {hasBulkMode && (
              <TableHead className="w-10 px-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={onSelectAll}
                  aria-label="Select all threads"
                  className="h-4 w-4 rounded border-border text-brand-500 focus:ring-brand-400 cursor-pointer"
                />
              </TableHead>
            )}
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Subject
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[160px]">
              Client
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[130px]">
              Category
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[130px]">
              Status
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[130px]">
              Assigned
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[70px] text-center">
              Msgs
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[110px]">
              Updated
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {threads.map((thread) => {
            const isSelected = selectedIds.has(thread.id);
            return (
              <TableRow
                key={thread.id}
                data-thread-row="true"
                data-thread-id={thread.id}
                className={cn(
                  "transition-colors border-b border-border/60",
                  isSelected
                    ? "bg-brand-50/60 hover:bg-brand-50"
                    : "hover:bg-accent/60"
                )}
              >
                {hasBulkMode && (
                  <TableCell className="w-10 px-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleSelect!(thread.id)}
                      aria-label={`Select thread: ${thread.subject}`}
                      className="h-4 w-4 rounded border-border text-brand-500 focus:ring-brand-400 cursor-pointer"
                    />
                  </TableCell>
                )}
                <TableCell
                  className="px-4 py-3 cursor-pointer"
                  tabIndex={0}
                  onClick={() => router.push(`/emails/${thread.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      router.push(`/emails/${thread.id}`);
                    }
                  }}
                >
                  <span className="inline-flex items-center gap-2">
                    <TierBadge tier={thread.tier ?? "t2_review"} variant="glyph" />
                    <span className="text-sm font-medium text-foreground truncate block max-w-[260px]">
                      {thread.subject}
                    </span>
                    {thread.draft_generation_failed && (
                      <span
                        title="AI draft generation failed for this thread"
                        className="flex-shrink-0"
                      >
                        <AlertTriangle
                          className="w-3.5 h-3.5 text-red-500"
                          aria-label="Draft generation failed"
                        />
                      </span>
                    )}
                  </span>
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[160px] cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  <span className="text-sm text-muted-foreground truncate block">
                    {thread.client_name ?? thread.client_email}
                  </span>
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[130px] cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  <CategoryBadge category={thread.category} />
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[130px] cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  <ThreadStatusBadge status={thread.status} />
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[130px] cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  {thread.assigned_to_name ? (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <UserCircle2 className="w-3.5 h-3.5 text-brand-400 flex-shrink-0" />
                      <span className="truncate max-w-[90px]">{thread.assigned_to_name}</span>
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[70px] text-center text-sm text-muted-foreground cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  {thread.message_count}
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[110px] cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  <span className="text-xs text-muted-foreground">
                    {relativeTime(thread.updated_at)}
                  </span>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
