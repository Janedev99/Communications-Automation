"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Mail,
  AlertTriangle,
  BookOpen,
  Settings,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUser } from "@/hooks/use-user";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const NAV_ITEMS = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Emails", href: "/emails", icon: Mail },
  { label: "Escalations", href: "/escalations", icon: AlertTriangle },
  { label: "Knowledge Base", href: "/knowledge", icon: BookOpen },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const { isAdmin } = useUser();

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <aside
      className={cn(
        "flex flex-col bg-gray-50 border-r border-gray-200 transition-all duration-200 ease-in-out flex-shrink-0",
        collapsed ? "w-16" : "w-56"
      )}
    >
      {/* Brand area */}
      <div className={cn("px-4 py-5 flex items-center", collapsed && "justify-center px-0")}>
        {collapsed ? (
          <div className="w-8 h-8 rounded-lg bg-brand-500 text-white font-bold text-sm flex items-center justify-center flex-shrink-0">
            S
          </div>
        ) : (
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-brand-500 text-white font-bold text-sm flex items-center justify-center flex-shrink-0">
              S
            </div>
            <div>
              <div className="text-sm font-bold text-gray-800 leading-tight">Schiller CPA</div>
              <div className="text-[10px] text-gray-400 leading-tight">Staff Portal</div>
            </div>
          </div>
        )}
      </div>

      {/* Main nav */}
      <nav className={cn("flex-1 px-2 space-y-0.5", collapsed && "px-2")}>
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            title={collapsed ? label : undefined}
            className={cn(
              "flex items-center rounded-md text-sm font-medium transition-colors duration-150",
              collapsed ? "px-0 py-2 justify-center" : "px-3 py-2 gap-2.5",
              isActive(href)
                ? "text-brand-600 bg-white shadow-sm ring-1 ring-gray-200/60 font-semibold"
                : "text-gray-600 hover:text-gray-800 hover:bg-gray-100"
            )}
          >
            <Icon className="w-5 h-5 flex-shrink-0" strokeWidth={1.75} />
            {!collapsed && <span>{label}</span>}
          </Link>
        ))}

        {/* Admin section */}
        {isAdmin && (
          <>
            <div className={cn("border-t border-gray-200 my-2", collapsed && "mx-1")} />
            <Link
              href="/settings"
              title={collapsed ? "Settings" : undefined}
              className={cn(
                "flex items-center rounded-md text-sm font-medium transition-colors duration-150",
                collapsed ? "px-0 py-2 justify-center" : "px-3 py-2 gap-2.5",
                isActive("/settings")
                  ? "text-brand-600 bg-white shadow-sm ring-1 ring-gray-200/60 font-semibold"
                  : "text-gray-600 hover:text-gray-800 hover:bg-gray-100"
              )}
            >
              <Settings className="w-5 h-5 flex-shrink-0" strokeWidth={1.75} />
              {!collapsed && <span>Settings</span>}
            </Link>
          </>
        )}
      </nav>

      {/* Collapse toggle */}
      <div className="px-2 py-3 border-t border-gray-200">
        <button
          onClick={onToggle}
          className={cn(
            "flex items-center rounded-md text-xs text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors duration-150 w-full",
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
