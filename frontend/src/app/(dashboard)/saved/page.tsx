"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Bookmark, BookmarkCheck, Folder, Inbox } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { CategoryBadge } from "@/components/emails/category-badge";
import { useEmails, useSavedFolders } from "@/hooks/use-emails";
import { cn, relativeTime } from "@/lib/utils";

const ALL_FOLDERS = "__all__";
const UNFILED = "__unfiled__";

export default function SavedPage() {
  const { folders, isLoading: foldersLoading, mutate: mutateFolders } = useSavedFolders();
  const [activeFolder, setActiveFolder] = useState<string>(ALL_FOLDERS);

  // The list query: when ALL_FOLDERS, fetch all saved; otherwise filter by folder
  // (UNFILED maps to the empty-string folder param the backend treats as NULL).
  const folderParam =
    activeFolder === ALL_FOLDERS
      ? undefined
      : activeFolder === UNFILED
      ? ""
      : activeFolder;

  const { threads, total, isLoading, isError, mutate } = useEmails({
    saved: true,
    folder: folderParam,
    page: 1,
    page_size: 100,
  });

  const totalSaved = useMemo(
    () => folders.reduce((sum, f) => sum + f.count, 0),
    [folders],
  );

  const handleRefresh = () => {
    mutate();
    mutateFolders();
  };

  const namedFolders = folders.filter((f) => f.name != null) as Array<{
    name: string;
    count: number;
  }>;
  const unfiledCount = folders.find((f) => f.name == null)?.count ?? 0;

  return (
    <div>
      <PageHeader
        title="Saved"
        subtitle="Threads you flagged for later — filed by client, project, or whatever folder you choose."
      />

      {/* Folder rail + list — two-column on lg+ */}
      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
        {/* Folder rail */}
        <aside className="lg:sticky lg:top-2 lg:self-start space-y-1">
          <FolderButton
            label="All saved"
            icon={Bookmark}
            count={totalSaved}
            active={activeFolder === ALL_FOLDERS}
            onClick={() => setActiveFolder(ALL_FOLDERS)}
          />
          {unfiledCount > 0 && (
            <FolderButton
              label="No folder"
              icon={Inbox}
              count={unfiledCount}
              active={activeFolder === UNFILED}
              onClick={() => setActiveFolder(UNFILED)}
              muted
            />
          )}
          {namedFolders.length > 0 && (
            <div className="pt-2 mt-2 border-t border-border/60">
              <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Folders
              </p>
              <div className="space-y-0.5">
                {namedFolders.map((f) => (
                  <FolderButton
                    key={f.name}
                    label={f.name}
                    icon={Folder}
                    count={f.count}
                    active={activeFolder === f.name}
                    onClick={() => setActiveFolder(f.name)}
                  />
                ))}
              </div>
            </div>
          )}
          {foldersLoading && namedFolders.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">Loading folders…</p>
          )}
        </aside>

        {/* List of saved threads */}
        <section>
          {isError ? (
            <ErrorState
              title="Failed to load saved threads"
              description="Could not retrieve your saved items."
              onRetry={handleRefresh}
            />
          ) : isLoading ? (
            <TableSkeleton rows={6} />
          ) : threads.length === 0 ? (
            <EmptyState activeFolder={activeFolder} />
          ) : (
            <>
              <p className="text-xs text-muted-foreground mb-3 tabular-nums">
                {total} saved thread{total === 1 ? "" : "s"}
              </p>
              <ul className="space-y-2">
                {threads.map((t) => (
                  <li key={t.id}>
                    <Link
                      href={`/emails/${t.id}`}
                      className="block bg-card border border-border rounded-lg px-4 py-3 hover:bg-accent/40 hover:border-foreground/20 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <BookmarkCheck
                              className="w-3.5 h-3.5 text-amber-700 dark:text-amber-300 fill-current shrink-0"
                              strokeWidth={1.75}
                              aria-hidden="true"
                            />
                            <h3 className="text-sm font-semibold text-foreground leading-snug truncate">
                              {t.subject}
                            </h3>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                            {t.client_name && (
                              <span className="text-foreground/80">{t.client_name}</span>
                            )}
                            <span className="truncate">{t.client_email}</span>
                            {t.saved_folder && (
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[10px] font-medium text-muted-foreground">
                                <Folder className="w-3 h-3" strokeWidth={1.75} aria-hidden="true" />
                                {t.saved_folder}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-1 shrink-0">
                          <CategoryBadge category={t.category} />
                          <span className="text-[10px] text-muted-foreground tabular-nums">
                            {relativeTime(t.updated_at)}
                          </span>
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function FolderButton({
  label,
  icon: Icon,
  count,
  active,
  onClick,
  muted,
}: {
  label: string;
  icon: typeof Folder;
  count: number;
  active: boolean;
  onClick: () => void;
  muted?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors text-left",
        active
          ? "bg-card text-foreground ring-1 ring-border shadow-sm"
          : "text-muted-foreground hover:text-foreground hover:bg-accent",
      )}
    >
      <Icon
        className={cn(
          "w-4 h-4 shrink-0",
          muted && !active && "text-muted-foreground/70",
        )}
        strokeWidth={1.75}
        aria-hidden="true"
      />
      <span className="flex-1 truncate">{label}</span>
      <span className="text-[11px] font-semibold tabular-nums text-muted-foreground">
        {count}
      </span>
    </button>
  );
}

function EmptyState({ activeFolder }: { activeFolder: string }) {
  const isAll = activeFolder === ALL_FOLDERS;
  return (
    <div className="bg-card border border-border rounded-xl p-12 text-center">
      <Bookmark
        className="w-10 h-10 text-muted-foreground/60 mx-auto"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <h3 className="text-sm font-semibold text-foreground mt-3">
        {isAll ? "No saved threads yet" : "Nothing in this folder"}
      </h3>
      <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
        {isAll
          ? "Open any thread and click the Save button in the header to file it here."
          : "Saved threads in another folder won't appear in this view."}
      </p>
    </div>
  );
}
