"use client";

import { Inbox, ShieldX, Trash2, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Top-level mail "folder" the email list is scoped to. Inbox is the working
 * view (excludes deleted + spam server-side); Spam and Deleted are dedicated
 * read views onto the terminal-status threads, mirroring Outlook's Junk /
 * Deleted Items folders. Switching folders maps to the `status` query the
 * list endpoint already supports.
 */
export type MailFolder = "inbox" | "spam" | "deleted";

interface FolderTab {
  id: MailFolder;
  label: string;
  icon: LucideIcon;
}

const FOLDERS: FolderTab[] = [
  { id: "inbox", label: "Inbox", icon: Inbox },
  { id: "spam", label: "Spam", icon: ShieldX },
  { id: "deleted", label: "Deleted", icon: Trash2 },
];

interface FolderTabsNavProps {
  active: MailFolder;
  onChange: (next: MailFolder) => void;
}

export function FolderTabsNav({ active, onChange }: FolderTabsNavProps) {
  return (
    <nav
      role="tablist"
      aria-label="Mail folder"
      className="inline-flex items-center gap-0.5 mb-3 p-0.5 rounded-lg bg-muted/60"
    >
      {FOLDERS.map((f) => {
        const isActive = active === f.id;
        const Icon = f.icon;
        return (
          <button
            key={f.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(f.id)}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 h-8 rounded-md text-sm font-medium transition-colors duration-150 whitespace-nowrap",
              isActive
                ? "bg-card text-foreground ring-1 ring-border shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-accent",
            )}
          >
            <Icon className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
            <span>{f.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
