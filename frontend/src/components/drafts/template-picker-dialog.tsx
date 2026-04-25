"use client";

import { useState } from "react";
import { FileText, Loader2, Search } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useKnowledge } from "@/hooks/use-knowledge";
import type { KnowledgeEntry } from "@/lib/types";

interface TemplatePickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (template: KnowledgeEntry) => void;
  loading?: boolean;
}

export function TemplatePickerDialog({
  open,
  onOpenChange,
  onSelect,
  loading,
}: TemplatePickerDialogProps) {
  const [search, setSearch] = useState("");

  const { entries, isLoading } = useKnowledge({
    entry_type: "response_template",
    is_active: true,
    page_size: 50,
  });

  const filtered = entries.filter(
    (e) =>
      e.title.toLowerCase().includes(search.toLowerCase()) ||
      e.content.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Use a Response Template</DialogTitle>
        </DialogHeader>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates..."
            className="pl-9"
            autoFocus
          />
        </div>

        <div className="max-h-80 overflow-y-auto -mx-1">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <FileText className="w-8 h-8 text-muted-foreground/60 mb-2" strokeWidth={1.5} />
              <p className="text-sm text-muted-foreground">
                {entries.length === 0
                  ? "No response templates found. Add some in the Knowledge Base."
                  : "No templates match your search."}
              </p>
            </div>
          ) : (
            <div className="space-y-1 px-1">
              {filtered.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  disabled={loading}
                  onClick={() => onSelect(template)}
                  className="w-full text-left px-3 py-3 rounded-md hover:bg-accent border border-transparent hover:border-border transition-all group disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground truncate group-hover:text-brand-600">
                        {template.title}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">
                        {template.content.slice(0, 120)}
                        {template.content.length > 120 ? "…" : ""}
                      </p>
                    </div>
                    {loading ? (
                      <Loader2 className="w-4 h-4 animate-spin text-muted-foreground flex-shrink-0 mt-0.5" />
                    ) : null}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex justify-end pt-1">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
