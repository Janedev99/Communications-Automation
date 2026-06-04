"use client";

import { PenLine } from "lucide-react";
import { useUser } from "@/hooks/use-user";

/**
 * Read-only preview of the signature that will be appended when the current
 * user sends. Signatures are a SEND-time concern (the sender's personal
 * signature, or the company block as fallback) — they are not part of the
 * editable body, so staff can't accidentally mangle them while editing.
 * Renders nothing if no signature would be appended.
 */
export function SignaturePreview() {
  const { user } = useUser();
  const signature = user?.effective_signature?.trim();
  if (!signature) return null;

  const isPersonal = !!user?.signature?.trim();

  return (
    <div className="rounded-lg bg-muted/50 border border-dashed border-border px-3 py-2">
      <p className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground mb-1">
        <PenLine className="w-3 h-3" aria-hidden="true" />
        Signature — added when you send
        <span className="text-muted-foreground/70 font-normal">
          ({isPersonal ? "yours" : "company"} · edit in Settings)
        </span>
      </p>
      <pre className="text-xs text-muted-foreground font-mono whitespace-pre-wrap leading-relaxed">
        {signature}
      </pre>
    </div>
  );
}
