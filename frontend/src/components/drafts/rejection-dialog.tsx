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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reject draft</DialogTitle>
          <DialogDescription>
            Tell the AI what to change so the next draft lands better.
          </DialogDescription>
        </DialogHeader>

        <div>
          <label
            htmlFor="rejection-reason"
            className="block text-sm font-medium text-foreground mb-1.5"
          >
            Reason
          </label>
          <Textarea
            id="rejection-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Tone is too formal, missed mentioning the deadline..."
            rows={4}
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
          <Button
            variant="destructive"
            onClick={handleSubmit}
            disabled={loading || !reason.trim()}
          >
            {loading ? "Rejecting..." : "Reject draft"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
