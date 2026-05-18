"use client";

import { useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const STORAGE_KEY = "jane_feedback_loop_onboarded";

/**
 * One-shot tooltip-style hint introducing the feedback loop on first view
 * of a generated draft. Dismissible; persists dismissal in localStorage so
 * it never re-fires. Non-blocking — Jane can ignore it and keep working.
 *
 * Renders inline (not as a floating popover) to avoid layout headaches in
 * the existing draft-panel sidebar. Lives directly below the AI insight
 * indicator so the visual relationship is obvious.
 */
export function FeedbackOnboarding() {
  const [shouldShow, setShouldShow] = useState(false);

  useEffect(() => {
    // Read on mount — SSR-safe via window guard
    if (typeof window === "undefined") return;
    const seen = window.localStorage.getItem(STORAGE_KEY);
    if (!seen) setShouldShow(true);
  }, []);

  const dismiss = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "1");
    }
    setShouldShow(false);
  };

  if (!shouldShow) return null;

  return (
    <div className="relative rounded-lg ring-1 ring-primary/30 bg-primary/5 px-3 py-3 text-xs">
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss tip"
        className="absolute top-2 right-2 text-muted-foreground hover:text-foreground transition-colors"
      >
        <X className="h-3 w-3" />
      </button>

      <div className="flex items-start gap-2 pr-5">
        <Sparkles className="h-3.5 w-3.5 mt-0.5 text-primary shrink-0" />
        <div className="flex-1 space-y-1.5">
          <p className="font-medium text-foreground">
            The AI learns from how you edit.
          </p>
          <p className="text-muted-foreground leading-relaxed">
            Every time you approve, edit, or reject a draft, the system uses
            that signal to generate better drafts next time — for similar
            emails. No setup required; just keep working naturally.
          </p>
          <div className="pt-1">
            <Button
              size="xs"
              variant="secondary"
              onClick={dismiss}
              className="text-[11px]"
            >
              Got it
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
