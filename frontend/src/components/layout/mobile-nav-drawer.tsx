"use client";

import { useEffect, useRef } from "react";

interface MobileNavDrawerProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export function MobileNavDrawer({ open, onClose, children }: MobileNavDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Keep the off-canvas panel out of the tab order while closed. It stays in
  // the DOM (translate-x-full only moves it visually), and a CSS transform
  // does NOT remove descendants from keyboard focus — without `inert` a
  // keyboard user could Tab into the hidden drawer. Set imperatively because
  // a boolean `inert` JSX prop isn't reliably applied under React 18.
  useEffect(() => {
    if (panelRef.current) panelRef.current.inert = !open;
  }, [open]);

  // Body scroll lock + Escape key listener + auto-close when the viewport
  // grows past lg (the drawer becomes invisible via lg:hidden, but `open`
  // would otherwise stay true and leave the body scroll-locked).
  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);

    const desktopQuery = window.matchMedia("(min-width: 1024px)");
    const handleViewportChange = (e: MediaQueryListEvent) => {
      if (e.matches) onClose();
    };
    desktopQuery.addEventListener("change", handleViewportChange);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      desktopQuery.removeEventListener("change", handleViewportChange);
    };
  }, [open, onClose]);

  return (
    <div className="lg:hidden" aria-hidden={!open}>
      {/* Scrim */}
      <div
        onClick={onClose}
        className={[
          "fixed inset-0 z-40 bg-black/40 supports-[backdrop-filter]:backdrop-blur-sm transition-opacity duration-200",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        ].join(" ")}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className={[
          "fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] bg-background border-r border-border flex flex-col",
          "transition-transform duration-200 ease-in-out pb-[env(safe-area-inset-bottom)]",
          open ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
      >
        {children}
      </div>
    </div>
  );
}
