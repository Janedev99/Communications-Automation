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

interface RejectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReject: (reason: string) => void | Promise<void>;
  loading?: boolean;
}

export function RejectionDialog({
  open,
  onOpenChange,
  onReject,
  loading,
}: RejectionDialogProps) {
  const [reason, setReason] = useState("");

  const handleSubmit = async () => {
    if (!reason.trim()) return;
    await onReject(reason.trim());
    setReason("");
  };

  const handleOpenChange = (v: boolean) => {
    if (!v) setReason("");
    onOpenChange(v);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Reject Draft</DialogTitle>
          <DialogDescription>
            Please provide a reason for rejection so the AI can improve the next draft.
          </DialogDescription>
        </DialogHeader>

        <Textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="What should be changed..."
          rows={4}
          className="text-sm"
          disabled={loading}
        />

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => handleOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleSubmit}
            disabled={loading || !reason.trim()}
          >
            {loading ? "Rejecting..." : "Reject Draft"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
