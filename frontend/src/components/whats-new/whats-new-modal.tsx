"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
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

  const dateLabel = new Date(release.published_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

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

        <article className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm dark:shadow-none">
          <header className="flex items-center gap-2 mb-3">
            <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-brand-500 to-brand-700 px-2.5 py-0.5 text-xs font-semibold text-white">
              <Sparkles className="h-3 w-3" aria-hidden="true" />
              What&apos;s new
            </span>
            <span className="text-xs text-slate-400 dark:text-slate-500">·</span>
            <span className="text-xs text-slate-500 dark:text-slate-400">{dateLabel}</span>
          </header>

          <h2 className="text-lg font-bold text-slate-900 dark:text-white tracking-tight mb-3">
            {release.title}
          </h2>

          {/*
            @tailwindcss/typography is NOT installed — no prose classes.
            We use a text-sm wrapper; react-markdown renders semantic HTML
            (p, ul, li, strong, code, etc.) with browser defaults, which
            looks fine for short release note bodies.
          */}
          <div className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed max-h-[50vh] overflow-y-auto [&_p]:mb-2 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:mb-2 [&_li]:mb-0.5 [&_strong]:font-semibold [&_code]:rounded [&_code]:bg-slate-100 [&_code]:dark:bg-slate-800 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h3]:font-semibold [&_h3]:text-slate-900 [&_h3]:dark:text-white [&_h3]:mt-3 [&_h3]:mb-1">
            <ReactMarkdown>{release.body}</ReactMarkdown>
          </div>
        </article>

        <label className="mt-4 flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={hideForever}
            onChange={(e) => setHideForever(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 dark:border-slate-700"
          />
          Don&apos;t show this again, ever
        </label>

        <DialogFooter className="mt-2">
          <Button onClick={handleClose} disabled={busy}>
            Got it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
