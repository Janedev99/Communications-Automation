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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Resolve escalation</DialogTitle>
          <DialogDescription>
            Add resolution notes to document how this escalation was handled. They&rsquo;ll
            be visible in the escalation log.
          </DialogDescription>
        </DialogHeader>

        <div>
          <label
            htmlFor="resolution-notes"
            className="block text-sm font-medium text-foreground mb-1.5"
          >
            Resolution notes
          </label>
          <Textarea
            id="resolution-notes"
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
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !notes.trim()}>
            {loading ? "Resolving..." : "Mark as resolved"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
