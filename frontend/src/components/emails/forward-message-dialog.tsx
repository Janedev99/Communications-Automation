"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { forwardMessage } from "@/lib/api";
import { ApiError } from "@/lib/types";
import type { EmailThread } from "@/lib/types";

interface ForwardMessageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  thread: EmailThread;
  /** Called after a successful forward so the parent can refresh the thread
   *  (the forwarded copy is recorded as a new outbound message on it). */
  onForwarded?: () => void;
}

/** Split a comma-separated recipient input into trimmed, non-empty addresses. */
function splitRecipients(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Forwards the thread's LATEST INBOUND message (with its attachments, via
 * the provider's native forward) to new recipients. Two triggers open this
 * dialog from ThreadDetail: the desktop header button row and the mobile
 * "more actions" menu.
 */
export function ForwardMessageDialog({
  open,
  onOpenChange,
  thread,
  onForwarded,
}: ForwardMessageDialogProps) {
  const [to, setTo] = useState("");
  const [showCc, setShowCc] = useState(false);
  const [cc, setCc] = useState("");
  const [note, setNote] = useState("");
  const [toInvalid, setToInvalid] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Reset on every open so a re-opened dialog never carries a stale draft.
  useEffect(() => {
    if (!open) return;
    setTo("");
    setShowCc(false);
    setCc("");
    setNote("");
    setToInvalid(false);
  }, [open]);

  const latestInbound = [...thread.messages]
    .filter((m) => m.direction === "inbound")
    .sort((a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime())[0];

  const canSubmit = !submitting && to.trim().length > 0 && !!latestInbound;

  const handleSubmit = async () => {
    if (!canSubmit || !latestInbound) return;
    setSubmitting(true);
    try {
      await forwardMessage(thread.id, latestInbound.id, {
        to: to.trim(),
        cc: cc.trim() || undefined,
        note: note.trim() || undefined,
      });
      const addresses = splitRecipients(to);
      const label =
        addresses.length > 1 ? `${addresses[0]} +${addresses.length - 1}` : addresses[0];
      toast.success(`Forwarded to ${label}.`);
      onOpenChange(false);
      onForwarded?.();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 501) {
          toast.error("Forwarding isn't available for this mailbox.");
          onOpenChange(false);
          return;
        }
        if (err.status === 404) {
          toast.error("The original message is no longer available to forward.");
          onOpenChange(false);
          return;
        }
        if (err.status === 422) {
          setToInvalid(true);
          toast.error("Check the email addresses and try again.");
          return;
        }
      }
      toast.error("Couldn't forward the email. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Forward this conversation</DialogTitle>
          <DialogDescription>
            The original messages and their attachments are included automatically.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <label htmlFor="forward-to" className="text-xs font-medium text-muted-foreground mb-1.5">
              To
            </label>
            <Input
              id="forward-to"
              autoFocus
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                if (toInvalid) setToInvalid(false);
              }}
              placeholder="name@example.com"
              aria-required="true"
              aria-invalid={toInvalid || undefined}
              className="h-9"
            />
          </div>

          {!showCc ? (
            <button
              type="button"
              onClick={() => setShowCc(true)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Add Cc
            </button>
          ) : (
            <div className="space-y-1.5">
              <label htmlFor="forward-cc" className="text-xs font-medium text-muted-foreground mb-1.5">
                Cc
              </label>
              <Input
                id="forward-cc"
                autoFocus
                value={cc}
                onChange={(e) => setCc(e.target.value)}
                placeholder="cc@example.com"
                className="h-9"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="forward-note" className="text-xs font-medium text-muted-foreground mb-1.5">
              Note <span className="text-muted-foreground/70">(optional)</span>
            </label>
            <Textarea
              id="forward-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add a note (optional)"
              rows={3}
              className="resize-none"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" aria-hidden="true" />
                Forwarding…
              </>
            ) : (
              "Forward"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
