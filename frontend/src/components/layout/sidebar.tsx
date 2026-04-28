"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Mail,
  AlertTriangle,
  BookOpen,
  GraduationCap,
  History,
  Settings,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUser } from "@/hooks/use-user";
import { useDashboard } from "@/hooks/use-dashboard";
import { ThemeToggle } from "@/components/layout/theme-toggle";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const LAST_SEEN_KEY = "jane_sidebar_last_seen";

interface LastSeenCounts {
  new_threads: number;
  pending_escalations: number;
}

function getLastSeen(): LastSeenCounts {
  if (typeof window === "undefined") return { new_threads: 0, pending_escalations: 0 };
  try {
    const raw = localStorage.getItem(LAST_SEEN_KEY);
    if (!raw) return { new_threads: 0, pending_escalations: 0 };
    return JSON.parse(raw) as LastSeenCounts;
  } catch {
    return { new_threads: 0, pending_escalations: 0 };
  }
}

function setLastSeen(counts: LastSeenCounts): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(LAST_SEEN_KEY, JSON.stringify(counts));
}

function NotificationDot({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span
      role="status"
      className="absolute top-1 right-1 w-2 h-2 rounded-full bg-destructive ring-2 ring-background"
      aria-label="New items"
    />
  );
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const { isAdmin } = useUser();
  const { stats } = useDashboard();

  // Compute whether there are new items since last seen
  const lastSeenRef = useRef<LastSeenCounts>(getLastSeen());

  const currentNewThreads = stats?.last_24h?.new_threads ?? 0;
  const currentPendingEscalations = stats?.totals?.pending_escalations ?? 0;

  const hasNewEmails = currentNewThreads > lastSeenRef.current.new_threads;
  const hasNewEscalations = currentPendingEscalations > lastSeenRef.current.pending_escalations;

  // When navigating to a section, clear its badge and persist
  useEffect(() => {
    if (pathname.startsWith("/emails")) {
      const updated = { ...lastSeenRef.current, new_threads: currentNewThreads };
      lastSeenRef.current = updated;
      setLastSeen(updated);
    }
    if (pathname.startsWith("/escalations")) {
      const updated = { ...lastSeenRef.current, pending_escalations: currentPendingEscalations };
      lastSeenRef.current = updated;
      setLastSeen(updated);
    }
  }, [pathname, currentNewThreads, currentPendingEscalations]);

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  // High/critical escalation badge — count unresolved escalations w/ severity high or critical
  const highCriticalCount =
    (stats?.escalations_by_severity?.["high"] ?? 0) +
    (stats?.escalations_by_severity?.["critical"] ?? 0);
  const criticalCount = stats?.escalations_by_severity?.["critical"] ?? 0;

  const NAV_ITEMS = [
    { label: "Dashboard", href: "/", icon: LayoutDashboard, badge: false },
    { label: "Emails", href: "/emails", icon: Mail, badge: hasNewEmails },
    { label: "Escalations", href: "/escalations", icon: AlertTriangle, badge: hasNewEscalations },
    { label: "Knowledge Base", href: "/knowledge", icon: BookOpen, badge: false },
    { label: "Tutorials", href: "/tutorials", icon: GraduationCap, badge: false },
  ];

  return (
    <aside
      className={cn(
        "flex flex-col bg-background border-r border-border transition-all duration-200 ease-in-out flex-shrink-0",
        collapsed ? "w-16" : "w-56"
      )}
    >
      {/* Brand area */}
      <div className={cn("px-4 py-5 flex items-center", collapsed && "justify-center px-0")}>
        {collapsed ? (
          <div className="w-8 h-8 rounded-lg bg-primary text-primary-foreground font-semibold text-sm flex items-center justify-center flex-shrink-0 ring-1 ring-primary/20 shadow-sm">
            S
          </div>
        ) : (
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary text-primary-foreground font-semibold text-sm flex items-center justify-center flex-shrink-0 ring-1 ring-primary/20 shadow-sm">
              S
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground leading-tight tracking-tight truncate">
                Schiller CPA
              </div>
              <div className="text-[10px] text-muted-foreground leading-tight">Staff Portal</div>
            </div>
          </div>
        )}
      </div>

      {/* Main nav */}
      <nav className={cn("flex-1 px-2 space-y-0.5", collapsed && "px-2")}>
        {NAV_ITEMS.map(({ label, href, icon: Icon, badge }) => {
          const isEscalations = href === "/escalations";
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              className={cn(
                "relative flex items-center rounded-md text-sm font-medium transition-colors duration-150",
                collapsed ? "px-0 py-2 justify-center" : "px-3 py-2 gap-2.5",
                active
                  ? "text-primary bg-card shadow-sm ring-1 ring-border/60 font-semibold"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              )}
            >
              <span className="relative flex-shrink-0">
                <Icon className="w-5 h-5" strokeWidth={1.75} />
                <NotificationDot show={badge} />
              </span>
              {!collapsed && (
                <span className={cn("flex-1", isEscalations && highCriticalCount > 0 && "font-semibold")}>
                  {label}
                </span>
              )}
              {/* High/critical count badge + overdue pulsing dot */}
              {!collapsed && isEscalations && highCriticalCount > 0 && (
                <span
                  className="flex items-center gap-1.5 ml-auto"
                  aria-label={`${highCriticalCount} high or critical ${highCriticalCount === 1 ? "escalation" : "escalations"}`}
                >
                  {criticalCount > 0 && (
                    <span
                      className="w-2 h-2 rounded-full bg-destructive animate-pulse motion-reduce:animate-none"
                      aria-hidden="true"
                    />
                  )}
                  <span
                    className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-destructive text-destructive-foreground text-[10px] font-semibold tabular-nums"
                    aria-hidden="true"
                  >
                    {highCriticalCount > 99 ? "99+" : highCriticalCount}
                  </span>
                </span>
              )}
              {/* Collapsed state: numeric badge above icon */}
              {collapsed && isEscalations && highCriticalCount > 0 && (
                <span
                  className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-destructive text-destructive-foreground text-[9px] font-semibold leading-none tabular-nums"
                  aria-label={`${highCriticalCount} high or critical ${highCriticalCount === 1 ? "escalation" : "escalations"}`}
                >
                  {highCriticalCount > 9 ? "9+" : highCriticalCount}
                </span>
              )}
            </Link>
          );
        })}

        {/* Admin section */}
        {isAdmin && (
          <>
            <div className={cn("border-t border-border my-2", collapsed && "mx-1")} />
            <Link
              href="/audit-log"
              title={collapsed ? "Audit Log" : undefined}
              className={cn(
                "flex items-center rounded-md text-sm font-medium transition-colors duration-150",
                collapsed ? "px-0 py-2 justify-center" : "px-3 py-2 gap-2.5",
                isActive("/audit-log")
                  ? "text-primary bg-card shadow-sm ring-1 ring-border/60 font-semibold"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              )}
            >
              <History className="w-5 h-5 flex-shrink-0" strokeWidth={1.75} />
              {!collapsed && <span>Audit Log</span>}
            </Link>
            <Link
              href="/settings"
              title={collapsed ? "Settings" : undefined}
              className={cn(
                "flex items-center rounded-md text-sm font-medium transition-colors duration-150",
                collapsed ? "px-0 py-2 justify-center" : "px-3 py-2 gap-2.5",
                isActive("/settings")
                  ? "text-primary bg-card shadow-sm ring-1 ring-border/60 font-semibold"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              )}
            >
              <Settings className="w-5 h-5 flex-shrink-0" strokeWidth={1.75} />
              {!collapsed && <span>Settings</span>}
            </Link>
          </>
        )}
      </nav>

      {/* Footer: theme toggle + collapse */}
      <div className="px-2 py-2 border-t border-border space-y-1">
        <ThemeToggle collapsed={collapsed} />
        <button
          onClick={onToggle}
          className={cn(
            "flex items-center rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors duration-150 w-full",
            collapsed ? "justify-center py-1.5 px-0" : "gap-1.5 px-3 py-1.5"
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <>
              <ChevronLeft className="w-4 h-4" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
