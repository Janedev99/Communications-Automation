"use client";

import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { KnowledgeEntry, EntryType } from "@/lib/types";

interface KnowledgeFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entry?: KnowledgeEntry;
  onSaved: () => void;
}

export function KnowledgeForm({ open, onOpenChange, entry, onSaved }: KnowledgeFormProps) {
  const isEdit = !!entry;

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("");
  const [entryType, setEntryType] = useState<EntryType>("response_template");
  const [tags, setTags] = useState("");
  const [loading, setLoading] = useState(false);

  // Populate form when editing
  useEffect(() => {
    if (entry) {
      setTitle(entry.title);
      setContent(entry.content);
      setCategory(entry.category ?? "");
      setEntryType(entry.entry_type);
      setTags(entry.tags?.join(", ") ?? "");
    } else {
      setTitle("");
      setContent("");
      setCategory("");
      setEntryType("response_template");
      setTags("");
    }
  }, [entry, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;

    setLoading(true);
    try {
      const payload = {
        title: title.trim(),
        content: content.trim(),
        category: category.trim() || null,
        entry_type: entryType,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };

      if (isEdit && entry) {
        await api.put(`/api/v1/knowledge/${entry.id}`, payload);
        toast.success("Entry updated.");
      } else {
        await api.post("/api/v1/knowledge", payload);
        toast.success("Entry created.");
      }

      onSaved();
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save entry.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit Entry" : "New Knowledge Entry"}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Title
            </label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Tax filing extension policy"
              required
              disabled={loading}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Entry Type
            </label>
            <Select value={entryType} onValueChange={(v) => setEntryType(v as EntryType)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="response_template">Response Template</SelectItem>
                <SelectItem value="policy">Policy</SelectItem>
                <SelectItem value="snippet">Snippet</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Category <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <Select value={category || "_all"} onValueChange={(v) => setCategory(v === "_all" ? "" : v)}>
              <SelectTrigger disabled={loading}>
                <SelectValue placeholder="All Categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="_all">All Categories</SelectItem>
                <SelectItem value="status_update">Status Update</SelectItem>
                <SelectItem value="document_request">Document Request</SelectItem>
                <SelectItem value="appointment">Appointment</SelectItem>
                <SelectItem value="clarification">Clarification</SelectItem>
                <SelectItem value="general_inquiry">General Inquiry</SelectItem>
                <SelectItem value="complaint">Complaint</SelectItem>
                <SelectItem value="urgent">Urgent</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Tags <span className="text-gray-400 font-normal">(comma-separated)</span>
            </label>
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g., extension, deadline, 1040"
              disabled={loading}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Content
            </label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Enter the knowledge content..."
              className="min-h-[200px] text-sm leading-relaxed"
              required
              disabled={loading}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              className="bg-brand-500 hover:bg-brand-600 text-white"
              disabled={loading || !title.trim() || !content.trim()}
            >
              {loading
                ? "Saving..."
                : isEdit
                ? "Save Changes"
                : "Create Entry"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
