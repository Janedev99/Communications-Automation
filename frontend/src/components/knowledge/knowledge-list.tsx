"use client";

import { useState } from "react";
import { MoreHorizontal, BookOpen } from "lucide-react";
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { KnowledgeForm } from "./knowledge-form";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { ENTRY_TYPE_BADGE_CLASSES, ENTRY_TYPE_LABELS } from "@/lib/constants";
import { api } from "@/lib/api";
import { cn, relativeTime } from "@/lib/utils";
import type { KnowledgeEntry } from "@/lib/types";

interface KnowledgeListProps {
  entries: KnowledgeEntry[];
  onRefresh: () => void;
}

export function KnowledgeList({ entries, onRefresh }: KnowledgeListProps) {
  const [editEntry, setEditEntry] = useState<KnowledgeEntry | null>(null);
  const [deleteEntry, setDeleteEntry] = useState<KnowledgeEntry | null>(null);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!deleteEntry) return;
    setDeleting(true);
    try {
      await api.delete(`/api/v1/knowledge/${deleteEntry.id}`);
      toast.success("Entry deactivated.");
      setDeleteEntry(null);
      onRefresh();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete entry.");
    } finally {
      setDeleting(false);
    }
  };

  if (entries.length === 0) {
    return (
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        <EmptyState
          icon={BookOpen}
          title="No entries found"
          description="Create your first knowledge entry to get started."
        />
      </div>
    );
  }

  return (
    <>
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 hover:bg-muted/40 border-b border-border">
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground py-2.5">
                Title
              </TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[140px] py-2.5">
                Category
              </TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[120px] py-2.5">
                Type
              </TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[180px] py-2.5">
                Tags
              </TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[60px] text-center py-2.5">
                Used
              </TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[120px] py-2.5">
                Updated
              </TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground w-[60px] py-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry, idx) => (
              <TableRow
                key={entry.id}
                className={cn(
                  "transition-colors hover:bg-accent/40",
                  idx !== entries.length - 1 && "border-b border-border/50",
                  !entry.is_active && "opacity-60"
                )}
              >
                <TableCell className="px-4 py-3">
                  <span className="text-sm font-medium text-foreground">{entry.title}</span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[140px]">
                  <span className="text-sm text-foreground/80">{entry.category ?? "—"}</span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[120px]">
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-[11px] font-medium",
                      ENTRY_TYPE_BADGE_CLASSES[entry.entry_type]
                    )}
                  >
                    {ENTRY_TYPE_LABELS[entry.entry_type]}
                  </span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[180px]">
                  <div className="flex flex-wrap gap-1">
                    {(entry.tags ?? []).slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="bg-muted text-muted-foreground rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-border/60"
                      >
                        {tag}
                      </span>
                    ))}
                    {(entry.tags?.length ?? 0) > 3 && (
                      <span className="text-[10px] text-muted-foreground/70 self-center">
                        +{(entry.tags?.length ?? 0) - 3}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="px-4 py-3 w-[60px] text-center text-sm text-muted-foreground tabular-nums">
                  {entry.usage_count}
                </TableCell>
                <TableCell className="px-4 py-3 w-[120px]">
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {relativeTime(entry.updated_at)}
                  </span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[60px]">
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      className="inline-flex items-center justify-center h-7 w-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                      aria-label="Actions"
                    >
                      <MoreHorizontal className="w-4 h-4" aria-hidden="true" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => setEditEntry(entry)}>
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        onClick={() => setDeleteEntry(entry)}
                      >
                        Deactivate
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <KnowledgeForm
        open={!!editEntry}
        onOpenChange={(v) => !v && setEditEntry(null)}
        entry={editEntry ?? undefined}
        onSaved={onRefresh}
      />

      <ConfirmDialog
        open={!!deleteEntry}
        onOpenChange={(v) => !v && setDeleteEntry(null)}
        title="Deactivate Entry"
        description="Are you sure you want to deactivate this entry? It will no longer be used for draft generation."
        confirmLabel="Deactivate"
        confirmVariant="destructive"
        onConfirm={handleDelete}
        loading={deleting}
      />
    </>
  );
}
