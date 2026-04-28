"use client";

import { usePathname } from "next/navigation";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUser } from "@/hooks/use-user";
import { ROLE_BADGE_CLASSES, ROLE_LABELS } from "@/lib/constants";

const PAGE_NAMES: Record<string, string> = {
  "/": "Dashboard",
  "/emails": "Emails",
  "/escalations": "Escalations",
  "/knowledge": "Knowledge Base",
  "/settings": "Settings",
  "/settings/triage-rules": "Triage Rules",
  "/settings/integrations": "Integrations",
  "/audit-log": "Audit Log",
  "/tutorials": "Tutorials",
};

function getPageName(pathname: string): string {
  if (PAGE_NAMES[pathname]) return PAGE_NAMES[pathname];
  if (pathname.startsWith("/emails/")) return "Thread Detail";
  return "";
}

function initialsFromName(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

export function Header() {
  const pathname = usePathname();
  const { user, logout } = useUser();
  const pageName = getPageName(pathname);

  return (
    <header className="h-14 bg-card/50 backdrop-blur-sm border-b border-border flex items-center justify-between px-6 flex-shrink-0">
      {/* Left: page label */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm font-medium text-foreground truncate">{pageName}</span>
      </div>

      {/* Right: user */}
      <div className="flex items-center gap-2">
        {user && (
          <>
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="flex items-center justify-center w-7 h-7 rounded-full bg-primary/10 text-primary text-[11px] font-semibold tracking-tight"
              >
                {initialsFromName(user.name)}
              </span>
              <div className="hidden md:flex flex-col leading-tight">
                <span className="text-sm font-medium text-foreground">{user.name}</span>
                <span
                  className={cn(
                    "text-[10px] font-medium uppercase tracking-wider",
                    ROLE_BADGE_CLASSES[user.role].split(" ").find((c) => c.startsWith("text-")) ??
                      "text-muted-foreground",
                  )}
                >
                  {ROLE_LABELS[user.role]}
                </span>
              </div>
            </div>
            <button
              onClick={logout}
              aria-label="Sign out"
              className="ml-2 inline-flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Sign out"
            >
              <LogOut className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
            </button>
          </>
        )}
      </div>
    </header>
  );
}
