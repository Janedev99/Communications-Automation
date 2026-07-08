"use client";

import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  /** Optional extra content rendered as a sibling block AFTER the
   *  description (not inside its <p>) — e.g. a recipient list for the send
   *  confirmation dialog. */
  details?: ReactNode;
  confirmLabel?: string;
  confirmVariant?: "default" | "destructive";
  onConfirm: () => void | Promise<void>;
  loading?: boolean;
  /** Disable the confirm button independent of `loading` (e.g. an empty
   *  recipient list should block sending even before a request is in flight). */
  confirmDisabled?: boolean;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  details,
  confirmLabel = "Confirm",
  confirmVariant = "destructive",
  onConfirm,
  loading,
  confirmDisabled,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {details}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant={confirmVariant}
            onClick={onConfirm}
            disabled={loading || confirmDisabled}
          >
            {loading ? "Processing..." : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
