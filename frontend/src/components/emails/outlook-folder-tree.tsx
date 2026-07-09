"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Folder, FolderOpen, Loader2 } from "lucide-react";
import { useOutlookFolders } from "@/hooks/use-emails";
import { cn } from "@/lib/utils";
import type { OutlookFolder } from "@/lib/types";

/**
 * Jane's own Outlook folders, rendered inline in the Saved-page folder rail as
 * part of the single unified "Folders" list (alongside the app's saved
 * folders). Custom mode hides Outlook's built-in system folders and surfaces
 * the folders she created, nested. Read-only: nothing here mutates the mailbox.
 * Clicking a folder filters the saved list by that folder name
 * (`onSelectFolder`). The `query` prop is the shared filter text owned by the
 * rail — this component renders no heading or filter box of its own.
 */
export function OutlookFolderTree({
  activeFolder,
  onSelectFolder,
  query = "",
}: {
  activeFolder: string | null;
  onSelectFolder: (name: string) => void;
  query?: string;
}) {
  const { folders, isLoading, isError } = useOutlookFolders(undefined, true);

  if (isError) {
    return (
      <p className="px-3 py-1.5 text-[11px] text-muted-foreground">
        Couldn&apos;t load Outlook folders.
      </p>
    );
  }
  if (isLoading) {
    return (
      <p className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground">
        <Loader2 className="w-3 h-3 animate-spin" /> Loading…
      </p>
    );
  }
  if (folders.length === 0) return null;

  return (
    <div className="space-y-0.5">
      {folders.map((f) => (
        <FolderNode
          key={f.id}
          folder={f}
          depth={0}
          filter={query.trim().toLowerCase()}
          activeFolder={activeFolder}
          onSelectFolder={onSelectFolder}
        />
      ))}
    </div>
  );
}

function FolderNode({
  folder,
  depth,
  filter,
  activeFolder,
  onSelectFolder,
}: {
  folder: OutlookFolder;
  depth: number;
  filter: string;
  activeFolder: string | null;
  onSelectFolder: (name: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = folder.child_folder_count > 0;
  const { folders: children, isLoading } = useOutlookFolders(
    expanded ? folder.id : undefined,
    true,
  );

  const matches = !filter || folder.display_name.toLowerCase().includes(filter);
  const visibleChildren = useMemo(
    () => children.filter((c) => !filter || c.display_name.toLowerCase().includes(filter)),
    [children, filter],
  );
  if (filter && !matches && (!expanded || visibleChildren.length === 0)) return null;

  const active = activeFolder === folder.display_name;

  return (
    <div>
      <div
        className={cn(
          "group/of flex items-center rounded-md transition-colors",
          active
            ? "bg-card text-foreground ring-1 ring-border shadow-sm"
            : "text-muted-foreground hover:text-foreground hover:bg-accent",
        )}
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        <button
          type="button"
          onClick={() => hasChildren && setExpanded((v) => !v)}
          className={cn(
            "flex items-center justify-center w-4 h-6 shrink-0",
            !hasChildren && "invisible",
          )}
          aria-label={expanded ? "Collapse" : "Expand"}
          aria-expanded={hasChildren ? expanded : undefined}
        >
          <ChevronRight className={cn("w-3 h-3 transition-transform", expanded && "rotate-90")} />
        </button>
        <button
          type="button"
          onClick={() => onSelectFolder(folder.display_name)}
          className="flex-1 flex items-center gap-1.5 py-1 pr-2 text-left min-w-0 text-sm"
          title={folder.display_name}
        >
          {expanded ? (
            <FolderOpen className="w-3.5 h-3.5 shrink-0 text-amber-600 dark:text-amber-400" strokeWidth={1.75} />
          ) : (
            <Folder className="w-3.5 h-3.5 shrink-0" strokeWidth={1.75} />
          )}
          <span className="flex-1 truncate">{folder.display_name}</span>
          <span className="text-[10px] tabular-nums text-muted-foreground">
            {folder.total_item_count}
          </span>
        </button>
      </div>
      {expanded &&
        (isLoading ? (
          <p
            className="flex items-center gap-1.5 py-1 text-[11px] text-muted-foreground"
            style={{ paddingLeft: `${depth * 12 + 24}px` }}
          >
            <Loader2 className="w-3 h-3 animate-spin" /> Loading…
          </p>
        ) : (
          <div className="space-y-0.5">
            {visibleChildren.map((c) => (
              <FolderNode
                key={c.id}
                folder={c}
                depth={depth + 1}
                filter={filter}
                activeFolder={activeFolder}
                onSelectFolder={onSelectFolder}
              />
            ))}
          </div>
        ))}
    </div>
  );
}
