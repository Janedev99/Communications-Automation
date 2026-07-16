"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import { Compose } from "./compose";

/**
 * Compose view modes, Gmail-style:
 *  - full:      full-page workspace over the content area (sidebar stays visible)
 *  - docked:    small window pinned bottom-right, floats over any page
 *  - minimized: collapsed to just its title bar, still bottom-right
 */
export type ComposeViewMode = "full" | "docked" | "minimized";

interface ComposeContextValue {
  open: boolean;
  viewMode: ComposeViewMode;
  /** Open a fresh compose in full-page mode. */
  openCompose: () => void;
  setViewMode: (mode: ComposeViewMode) => void;
  /** Tear the window down (clears the in-progress email). */
  close: () => void;
}

const ComposeContext = createContext<ComposeContextValue | null>(null);

/**
 * App-wide compose state. Only `open` + `viewMode` live here — the in-progress
 * email (recipients, subject, body, attachments) lives inside <Compose/>, which
 * <ComposeMount/> renders once inside the persistent dashboard layout. Because
 * that subtree never unmounts across route changes or mode switches, the draft
 * survives minimizing to the corner and navigating away to read other mail.
 */
export function ComposeProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ComposeViewMode>("full");
  const pathname = usePathname();
  const prevPathRef = useRef(pathname);

  const openCompose = useCallback(() => {
    setViewMode("full");
    setOpen(true);
  }, []);

  const close = useCallback(() => setOpen(false), []);

  // When the route changes while a full-page compose is open, demote it to the
  // docked window so the page the user navigated to is actually visible (with
  // the draft still floating in the corner). Only reacts to real path changes,
  // not the initial mount.
  useEffect(() => {
    if (prevPathRef.current !== pathname) {
      prevPathRef.current = pathname;
      if (open) {
        setViewMode((m) => (m === "full" ? "docked" : m));
      }
    }
  }, [pathname, open]);

  return (
    <ComposeContext.Provider value={{ open, viewMode, openCompose, setViewMode, close }}>
      {children}
    </ComposeContext.Provider>
  );
}

/**
 * Renders the compose window when open. Mounted inside the dashboard layout's
 * (relatively positioned) content column so full mode covers the content area
 * while the sidebar stays reachable.
 */
export function ComposeMount() {
  const { open } = useCompose();
  if (!open) return null;
  return <Compose />;
}

export function useCompose(): ComposeContextValue {
  const ctx = useContext(ComposeContext);
  if (!ctx) {
    throw new Error("useCompose must be used within a <ComposeProvider>");
  }
  return ctx;
}
