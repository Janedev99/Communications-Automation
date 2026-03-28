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
};

function getPageName(pathname: string): string {
  if (PAGE_NAMES[pathname]) return PAGE_NAMES[pathname];
  if (pathname.startsWith("/emails/")) return "Thread Detail";
  return "";
}

export function Header() {
  const pathname = usePathname();
  const { user, logout } = useUser();
  const pageName = getPageName(pathname);

  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 flex-shrink-0">
      {/* Left: breadcrumb */}
      <span className="text-sm text-gray-500">{pageName}</span>

      {/* Right: user info + logout */}
      <div className="flex items-center gap-3">
        {user && (
          <>
            <span className="text-sm font-medium text-gray-700">{user.name}</span>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-medium",
                ROLE_BADGE_CLASSES[user.role]
              )}
            >
              {ROLE_LABELS[user.role]}
            </span>
            <button
              onClick={logout}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors duration-150"
            >
              <LogOut className="w-4 h-4" />
              <span>Sign out</span>
            </button>
          </>
        )}
      </div>
    </header>
  );
}
