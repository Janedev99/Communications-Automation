"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/page-header";
import { KnowledgeList } from "@/components/knowledge/knowledge-list";
import { KnowledgeForm } from "@/components/knowledge/knowledge-form";
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
import { useKnowledge } from "@/hooks/use-knowledge";

export default function KnowledgePage() {
  const [entryType, setEntryType] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);

  const { entries, total, isLoading, isError, mutate } = useKnowledge({
    entry_type: entryType || undefined,
    is_active: showInactive ? undefined : true,
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
        title="Knowledge Base"
        actions={
          <Button
            className="bg-brand-500 hover:bg-brand-600 text-white"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            New Entry
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Select
          value={entryType || "all"}
          onValueChange={(v: string | null) => handleFilterChange(setEntryType)(!v || v === "all" ? "" : v)}
        >
          <SelectTrigger className="w-[180px] h-9 text-sm">
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="response_template">Response Template</SelectItem>
            <SelectItem value="policy">Policy</SelectItem>
            <SelectItem value="snippet">Snippet</SelectItem>
          </SelectContent>
        </Select>

        <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
          <Switch
            checked={showInactive}
            onCheckedChange={(v) => {
              setShowInactive(v);
              setPage(1);
            }}
          />
          Show inactive
        </label>
      </div>

      {isError ? (
        <ErrorState
          title="Failed to load knowledge base"
          description="Could not retrieve knowledge entries. Please try again."
          onRetry={mutate}
        />
      ) : isLoading ? (
        <TableSkeleton rows={8} />
      ) : (
        <>
          <KnowledgeList entries={entries} onRefresh={mutate} />
          <Pagination
            page={page}
            pageSize={25}
            total={total}
            onPageChange={setPage}
          />
        </>
      )}

      <KnowledgeForm
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSaved={mutate}
      />
    </div>
  );
}
