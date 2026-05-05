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
import {
  AlertTriangle,
  BookmarkCheck,
  HelpCircle,
  Mail,
  UserCircle2,
  Zap,
} from "lucide-react";
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
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        <EmptyState
          icon={Mail}
          title="No threads found"
          description="Try adjusting your filters or wait for the next poll cycle."
        />
      </div>
    );
  }

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40 hover:bg-muted/40 border-b border-border">
            {hasBulkMode && (
              <TableHead className="w-10 px-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={onSelectAll}
                  aria-label="Select all threads"
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary/30 cursor-pointer"
                />
              </TableHead>
            )}
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground py-2.5">
              Subject
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[160px] py-2.5">
              Client
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[130px] py-2.5">
              Category
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[130px] py-2.5">
              Status
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[130px] py-2.5">
              Assigned
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[60px] text-center py-2.5">
              Msgs
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[110px] py-2.5">
              Updated
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {threads.map((thread, idx) => {
            const isSelected = selectedIds.has(thread.id);
            const isLast = idx === threads.length - 1;
            // Item E: emails the AI couldn't classify confidently land here.
            // Jane explicitly asked about a "surprise box" — we mark these
            // rows so they stand out within the For Review lane.
            const isUncategorized = thread.category === "uncategorized";
            // Item C: T1 threads where the AI sent the reply autonomously.
            // Jane asked "where is that indication?" — make it unmistakable.
            const wasAutoSent = !!thread.auto_sent_at;
            return (
              <TableRow
                key={thread.id}
                data-thread-row="true"
                data-thread-id={thread.id}
                className={cn(
                  "group transition-colors",
                  !isLast && "border-b border-border/50",
                  isSelected
                    ? "bg-primary/[0.06] hover:bg-primary/[0.09]"
                    : isUncategorized
                    ? "bg-amber-500/[0.04] hover:bg-amber-500/[0.08] border-l-2 border-l-amber-500/50"
                    : "hover:bg-accent/40"
                )}
              >
                {hasBulkMode && (
                  <TableCell className="w-10 px-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleSelect!(thread.id)}
                      aria-label={`Select thread: ${thread.subject}`}
                      className="h-4 w-4 rounded border-border text-primary focus:ring-primary/30 cursor-pointer"
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
                    <span className="text-sm font-medium text-foreground truncate block max-w-[260px] group-hover:text-foreground">
                      {thread.subject}
                    </span>
                    {thread.is_saved && (
                      <span
                        title={
                          thread.saved_folder
                            ? `Saved in "${thread.saved_folder}"`
                            : "Saved"
                        }
                        className="flex-shrink-0 text-amber-600 dark:text-amber-400"
                      >
                        <BookmarkCheck
                          className="w-3.5 h-3.5 fill-current"
                          strokeWidth={1.75}
                          aria-label="Saved"
                        />
                      </span>
                    )}
                    {wasAutoSent && (
                      <span
                        title="AI auto-replied — no review needed"
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px] font-semibold uppercase tracking-wider flex-shrink-0"
                      >
                        <Zap className="w-3 h-3" strokeWidth={2.25} aria-hidden="true" />
                        AI sent
                      </span>
                    )}
                    {isUncategorized && (
                      <span
                        title="AI couldn't classify this email — needs human triage"
                        className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-400 text-[10px] font-semibold uppercase tracking-wider flex-shrink-0"
                      >
                        <HelpCircle
                          className="w-3.5 h-3.5"
                          strokeWidth={2}
                          aria-label="Uncategorized — needs triage"
                        />
                      </span>
                    )}
                    {thread.draft_generation_failed && (
                      <span
                        title="AI draft generation failed for this thread"
                        className="flex-shrink-0"
                      >
                        <AlertTriangle
                          className="w-3.5 h-3.5 text-destructive"
                          strokeWidth={2}
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
                  <span className="text-sm text-foreground/80 truncate block">
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
                    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                      <UserCircle2
                        className="w-3.5 h-3.5 text-muted-foreground/70 flex-shrink-0"
                        strokeWidth={1.75}
                        aria-hidden="true"
                      />
                      <span className="truncate max-w-[90px]">{thread.assigned_to_name}</span>
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground/60">—</span>
                  )}
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[60px] text-center text-sm text-muted-foreground tabular-nums cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  {thread.message_count}
                </TableCell>
                <TableCell
                  className="px-4 py-3 w-[110px] cursor-pointer"
                  onClick={() => router.push(`/emails/${thread.id}`)}
                >
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
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
