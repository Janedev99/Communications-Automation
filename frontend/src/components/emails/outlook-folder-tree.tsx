"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Folder, FolderOpen, Loader2 } from "lucide-react";
import { useOutlookFolders } from "@/hooks/use-emails";
import { cn } from "@/lib/utils";
import type { OutlookFolder } from "@/lib/types";

/**
 * Read-only, lazy-expanding view of the mailbox's real Outlook folders.
 * Each node fetches its children only when expanded (the Inbox alone has
 * hundreds), and a search box filters the currently-loaded nodes by name.
 * Nothing here mutates the mailbox.
 */
export function OutlookFolderTree() {
  const [query, setQuery] = useState("");
  const { folders, isLoading, isError } = useOutlookFolders();

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h3 className="text-sm font-semibold text-foreground">Outlook folders</h3>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter loaded folders…"
          className="h-7 w-40 rounded-md border border-border bg-card px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />
      </div>
      {isError ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Couldn&apos;t load Outlook folders. Check the mailbox connection.
        </p>
      ) : isLoading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading folders…
        </p>
      ) : folders.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          No Outlook folders found.
        </p>
      ) : (
        <ul className="space-y-0.5">
          {folders.map((f) => (
            <FolderNode key={f.id} folder={f} depth={0} filter={query.trim().toLowerCase()} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FolderNode({
  folder,
  depth,
  filter,
}: {
  folder: OutlookFolder;
  depth: number;
  filter: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = folder.child_folder_count > 0;
  // Fetch children only once expanded (lazy).
  const { folders: children, isLoading } = useOutlookFolders(
    expanded ? folder.id : undefined,
  );

  const matches = !filter || folder.display_name.toLowerCase().includes(filter);
  const visibleChildren = useMemo(
    () => children.filter((c) => !filter || c.display_name.toLowerCase().includes(filter)),
    [children, filter],
  );
  // Hide a non-matching leaf while filtering; keep parents so matches stay reachable.
  if (filter && !matches && (!expanded || visibleChildren.length === 0)) return null;

  return (
    <li>
      <div
        className="flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-accent/50 transition-colors"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          onClick={() => hasChildren && setExpanded((v) => !v)}
          className={cn(
            "flex items-center justify-center w-4 h-4 shrink-0 text-muted-foreground",
            !hasChildren && "invisible",
          )}
          aria-label={expanded ? "Collapse" : "Expand"}
          aria-expanded={hasChildren ? expanded : undefined}
        >
          <ChevronRight className={cn("w-3.5 h-3.5 transition-transform", expanded && "rotate-90")} />
        </button>
        {expanded ? (
          <FolderOpen className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" strokeWidth={1.75} />
        ) : (
          <Folder className="w-4 h-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
        )}
        <span className="flex-1 truncate text-sm text-foreground">{folder.display_name}</span>
        {folder.unread_item_count > 0 && (
          <span className="text-[10px] font-semibold text-primary tabular-nums">
            {folder.unread_item_count}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground tabular-nums">
          {folder.total_item_count}
        </span>
      </div>
      {expanded &&
        (isLoading ? (
          <p
            className="flex items-center gap-2 text-xs text-muted-foreground py-1"
            style={{ paddingLeft: `${depth * 16 + 32}px` }}
          >
            <Loader2 className="w-3 h-3 animate-spin" /> Loading…
          </p>
        ) : (
          <ul className="space-y-0.5">
            {visibleChildren.map((c) => (
              <FolderNode key={c.id} folder={c} depth={depth + 1} filter={filter} />
            ))}
          </ul>
        ))}
    </li>
  );
}
