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
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <EmptyState
          icon={BookOpen}
          title="No entries found"
          description="Create your first knowledge entry to get started"
        />
      </div>
    );
  }

  return (
    <>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/80 hover:bg-accent/80">
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Title
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[140px]">
                Category
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[120px]">
                Type
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[180px]">
                Tags
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[70px] text-center">
                Used
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[120px]">
                Updated
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[80px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow
                key={entry.id}
                className={cn(
                  "border-b border-border/60 hover:bg-accent/60 transition-colors",
                  !entry.is_active && "opacity-50"
                )}
              >
                <TableCell className="px-4 py-3">
                  <span className="text-sm font-medium text-foreground">{entry.title}</span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[140px]">
                  <span className="text-sm text-muted-foreground">{entry.category ?? "—"}</span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[120px]">
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-xs font-medium",
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
                        className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-[10px]"
                      >
                        {tag}
                      </span>
                    ))}
                    {(entry.tags?.length ?? 0) > 3 && (
                      <span className="text-[10px] text-muted-foreground">
                        +{(entry.tags?.length ?? 0) - 3}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="px-4 py-3 w-[70px] text-center text-sm text-muted-foreground">
                  {entry.usage_count}
                </TableCell>
                <TableCell className="px-4 py-3 w-[120px]">
                  <span className="text-xs text-muted-foreground">
                    {relativeTime(entry.updated_at)}
                  </span>
                </TableCell>
                <TableCell className="px-4 py-3 w-[80px]">
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      className="inline-flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                      aria-label="Actions"
                    >
                      <MoreHorizontal className="w-4 h-4" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => setEditEntry(entry)}>
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="text-red-600"
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
