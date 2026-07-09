"use client";

import { useEffect, useState } from "react";
import { ChevronDown, PenLine } from "lucide-react";
import { useUser } from "@/hooks/use-user";
import { cn } from "@/lib/utils";

// Collapse preference is shared across every place the preview renders (compose
// dock + draft panel) and persists per browser, so once Jane tucks the
// signature away to reclaim editing space it stays that way.
const COLLAPSE_KEY = "jane_signature_preview_collapsed";

/**
 * Read-only preview of the signature that will be appended when the current
 * user sends. Signatures are a SEND-time concern (the sender's personal
 * signature, or the company block as fallback) — they are not part of the
 * editable body, so staff can't accidentally mangle them while editing.
 *
 * The block is collapsible: the header stays visible as a toggle, and
 * collapsing hides the signature text to give the draft/compose editor more
 * room. Renders nothing if no signature would be appended.
 */
export function SignaturePreview() {
  const { user } = useUser();
  // Default expanded on the server + first client render (stable markup); the
  // stored preference applies after mount.
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
  }, []);

  const signature = user?.effective_signature?.trim();
  if (!signature) return null;

  const isPersonal = !!user?.signature?.trim();

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
  };

  return (
    <div className="rounded-lg bg-muted/50 border border-dashed border-border px-3 py-2">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        aria-label={collapsed ? "Show signature preview" : "Hide signature preview"}
        className="flex w-full items-center gap-1.5 text-[11px] font-medium text-muted-foreground"
      >
        <PenLine className="w-3 h-3 shrink-0" aria-hidden="true" />
        Signature — added when you send
        <span className="text-muted-foreground/70 font-normal">
          ({isPersonal ? "yours" : "company"} · edit in Settings)
        </span>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 ml-auto shrink-0 transition-transform duration-150",
            collapsed && "-rotate-90"
          )}
          aria-hidden="true"
        />
      </button>
      {!collapsed && (
        <pre className="mt-1 text-xs text-muted-foreground font-mono whitespace-pre-wrap leading-relaxed">
          {signature}
        </pre>
      )}
    </div>
  );
}
