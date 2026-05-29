"use client";

import { createContext, useCallback, useContext, useState } from "react";
import { ComposeDock, type ComposePrefill } from "./compose-dock";

interface ComposeContextValue {
  /** Open the docked compose window, optionally pre-filling fields. */
  openCompose: (prefill?: ComposePrefill) => void;
}

const ComposeContext = createContext<ComposeContextValue | null>(null);

/**
 * App-wide compose state. Mounted once in the dashboard layout so the docked
 * window floats over any page (Gmail-style) and a single instance is shared.
 * Closing tears the window down (clearing the draft); minimizing keeps it.
 */
export function ComposeProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [prefill, setPrefill] = useState<ComposePrefill | undefined>(undefined);

  const openCompose = useCallback((p?: ComposePrefill) => {
    setPrefill(p);
    setOpen(true);
  }, []);

  return (
    <ComposeContext.Provider value={{ openCompose }}>
      {children}
      {open && (
        <ComposeDock prefill={prefill} onClose={() => setOpen(false)} />
      )}
    </ComposeContext.Provider>
  );
}

export function useCompose(): ComposeContextValue {
  const ctx = useContext(ComposeContext);
  if (!ctx) {
    throw new Error("useCompose must be used within a <ComposeProvider>");
  }
  return ctx;
}
