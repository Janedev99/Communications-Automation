"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ResolveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolve: (notes: string) => void | Promise<void>;
  loading?: boolean;
}

export function ResolveDialog({
  open,
  onOpenChange,
  onResolve,
  loading,
}: ResolveDialogProps) {
  const [notes, setNotes] = useState("");

  const handleSubmit = async () => {
    await onResolve(notes.trim());
    setNotes("");
  };

  const handleOpenChange = (v: boolean) => {
    if (!v) setNotes("");
    onOpenChange(v);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Resolve Escalation</DialogTitle>
          <DialogDescription>
            Add resolution notes to document how this escalation was handled.
          </DialogDescription>
        </DialogHeader>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            Resolution notes
          </label>
          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Describe how this was resolved..."
            rows={4}
            className="text-sm"
            disabled={loading}
          />
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => handleOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            className="bg-brand-500 hover:bg-brand-600 text-white"
            onClick={handleSubmit}
            disabled={loading}
          >
            {loading ? "Resolving..." : "Mark as Resolved"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
