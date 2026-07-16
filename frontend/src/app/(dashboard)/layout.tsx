"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { MobileNavDrawer } from "@/components/layout/mobile-nav-drawer";
import { KeyboardShortcutsDialog } from "@/components/shared/keyboard-shortcuts-dialog";
import { useUser } from "@/hooks/use-user";
import { api } from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const { isLoading: authLoading } = useUser();
  const router = useRouter();
  const pathname = usePathname();

  // Stable callbacks so MobileNavDrawer's effect deps don't re-subscribe its
  // keydown/matchMedia listeners on every layout re-render.
  const openMobileNav = useCallback(() => setMobileNavOpen(true), []);
  const closeMobileNav = useCallback(() => setMobileNavOpen(false), []);

  // Desktop sidebar collapse on small windows (lg+ only — below lg the drawer handles nav)
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024 && window.innerWidth < 1280) {
        setCollapsed(true);
      }
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  // Global keyboard shortcut handler
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Never fire when the user is typing in an input/textarea/select/contenteditable
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      // ? — show shortcuts help
      if (e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setShowShortcuts((v) => !v);
        return;
      }

      // Thread-detail shortcuts: a = approve, r = reject
      if (pathname.startsWith("/emails/") && pathname.split("/").length >= 3) {
        if (e.key === "a" && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          // Trigger approve button if visible
          const approveBtn = document.querySelector<HTMLButtonElement>(
            "[data-shortcut='approve']"
          );
          approveBtn?.click();
          return;
        }
        if (e.key === "r" && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          const rejectBtn = document.querySelector<HTMLButtonElement>(
            "[data-shortcut='reject']"
          );
          rejectBtn?.click();
          return;
        }
      }

      // Email list shortcuts: j/k navigation + Enter to open.
      // Both the mobile card list and the desktop table are always in the
      // DOM (toggled via CSS breakpoints), so filter to the visible render
      // path — offsetParent is null for display:none subtrees.
      if (pathname === "/emails") {
        const rows = Array.from(
          document.querySelectorAll<HTMLElement>("[data-thread-row]")
        ).filter((el) => el.offsetParent !== null);
        if (rows.length === 0) return;

        const focused = rows.find((r) => r.getAttribute("data-focused") === "true") ?? null;
        const currentIndex = focused ? rows.indexOf(focused) : -1;

        // Clear on every row (visible or hidden) so a viewport resize can't
        // leave a stale data-focused marker on the other render path.
        const clearFocused = () =>
          document
            .querySelectorAll<HTMLElement>("[data-thread-row][data-focused='true']")
            .forEach((r) => r.removeAttribute("data-focused"));

        if (e.key === "j") {
          e.preventDefault();
          const nextIndex = Math.min(currentIndex + 1, rows.length - 1);
          clearFocused();
          rows[nextIndex]?.setAttribute("data-focused", "true");
          rows[nextIndex]?.focus();
          return;
        }

        if (e.key === "k") {
          e.preventDefault();
          const prevIndex = Math.max(currentIndex - 1, 0);
          clearFocused();
          rows[prevIndex]?.setAttribute("data-focused", "true");
          rows[prevIndex]?.focus();
          return;
        }

        if (e.key === "Enter" && focused) {
          e.preventDefault();
          const threadId = focused.getAttribute("data-thread-id");
          if (threadId) {
            router.push(`/emails/${threadId}`);
          }
          return;
        }
      }
    },
    [pathname, router]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // RunPod pre-warm + login-time draft catch-up. Fires once per
  // dashboard-layout mount (per login session). Both endpoints are
  // fire-and-forget: errors logged to console, never surface to the user.
  //
  // - /runpod/wake : tells the backend to start the RunPod pod in
  //   background NOW, so by the time Jane clicks Generate Draft the
  //   pod is already warm (or close to it).
  // - /runpod/login-sweep : finds T1/T2 threads missing drafts and
  //   queues them for background generation, so Jane sees drafts
  //   ready when she navigates to the emails page.
  //
  // Gated on !authLoading so we don't fire before the user is logged in
  // (the api helper would 401 and redirect). wakeFiredRef ensures we
  // never fire twice for the same session even if useEffect re-runs.
  const wakeFiredRef = useRef(false);
  useEffect(() => {
    if (authLoading || wakeFiredRef.current) return;
    wakeFiredRef.current = true;
    api.post("/api/v1/runpod/wake").catch((err) => {
      // Don't disrupt the user — drafts still work without pre-warm,
      // just slower on cold-start. The orchestrator's normal paths
      // catch and handle this on demand.
      console.warn("[runpod] wake failed (non-fatal):", err);
    });
    api.post("/api/v1/runpod/login-sweep").catch((err) => {
      console.warn("[runpod] login-sweep failed (non-fatal):", err);
    });
  }, [authLoading]);

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar — hidden below lg, shown at lg+ */}
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />

      {/* Mobile drawer — renders the sidebar without its desktop hide class */}
      <MobileNavDrawer open={mobileNavOpen} onClose={closeMobileNav}>
        <Sidebar
          collapsed={false}
          onToggle={() => {}}
          inDrawer
          onNavigate={closeMobileNav}
        />
      </MobileNavDrawer>

      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header onOpenNav={openMobileNav} navOpen={mobileNavOpen} />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          {children}
        </main>
      </div>

      <KeyboardShortcutsDialog
        open={showShortcuts}
        onOpenChange={setShowShortcuts}
      />
    </div>
  );
}
