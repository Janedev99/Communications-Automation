"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ReleaseNoteCard } from "./release-note-card";
import type { LatestUnreadResponse } from "@/lib/types";

interface Props {
  release: LatestUnreadResponse | null;
  open: boolean;
  /**
   * Called on ANY close (Esc, click outside, X corner, "Got it" button).
   * dontShowAgainEver=true means the user ticked the checkbox — the parent
   * should additionally call setHideForever(true) on the hook.
   */
  onClose: (dontShowAgainEver: boolean) => void;
}

export function WhatsNewModal({ release, open, onClose }: Props) {
  const [hideForever, setHideForever] = useState(false);
  const [busy, setBusy] = useState(false);

  // Reset checkbox each time the modal closes so stale state doesn't persist
  // if the modal reopens (e.g. during the same session).
  useEffect(() => {
    if (!open) setHideForever(false);
  }, [open]);

  if (!release) return null;

  const handleClose = () => {
    if (busy) return;
    setBusy(true);
    try {
      onClose(hideForever);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) handleClose();
      }}
    >
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader className="sr-only">
          <DialogTitle>{release.title}</DialogTitle>
        </DialogHeader>

        <ReleaseNoteCard
          title={release.title}
          summary={release.summary}
          highlights={release.highlights}
          body={release.body}
          publishedAt={release.published_at}
          compact
        />

        <label className="mt-4 flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={hideForever}
            onChange={(e) => setHideForever(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          Don&apos;t show this again, ever
        </label>

        <div className="mt-2 flex items-center justify-between">
          <Link
            href="/whats-new"
            onClick={() => onClose(hideForever)}
            className="text-xs text-muted-foreground hover:text-foreground underline-offset-4 hover:underline"
          >
            View all releases
          </Link>
          <Button onClick={handleClose} disabled={busy}>
            Got it
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
