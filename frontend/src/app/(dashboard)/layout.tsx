"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { KeyboardShortcutsDialog } from "@/components/shared/keyboard-shortcuts-dialog";
import { useUser } from "@/hooks/use-user";
import { api } from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const { isLoading: authLoading } = useUser();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 1024) {
        setCollapsed(true);
      }
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

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

      // Email list shortcuts: j/k navigation + Enter to open
      if (pathname === "/emails") {
        const rows = document.querySelectorAll<HTMLElement>("[data-thread-row]");
        if (rows.length === 0) return;

        const focused = document.querySelector<HTMLElement>("[data-thread-row][data-focused='true']");
        const currentIndex = focused ? Array.from(rows).indexOf(focused) : -1;

        if (e.key === "j") {
          e.preventDefault();
          const nextIndex = Math.min(currentIndex + 1, rows.length - 1);
          rows.forEach((r) => r.removeAttribute("data-focused"));
          rows[nextIndex]?.setAttribute("data-focused", "true");
          rows[nextIndex]?.focus();
          return;
        }

        if (e.key === "k") {
          e.preventDefault();
          const prevIndex = Math.max(currentIndex - 1, 0);
          rows.forEach((r) => r.removeAttribute("data-focused"));
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
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
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
