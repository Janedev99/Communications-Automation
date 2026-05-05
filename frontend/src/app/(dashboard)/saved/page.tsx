"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Bookmark,
  BookmarkCheck,
  Folder,
  Inbox,
  Mail,
  MessagesSquare,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { CategoryBadge } from "@/components/emails/category-badge";
import {
  useEmails,
  useSavedFolders,
  useSavedMessages,
} from "@/hooks/use-emails";
import { cn, relativeTime } from "@/lib/utils";

const ALL_FOLDERS = "__all__";
const UNFILED = "__unfiled__";

type SavedTab = "threads" | "messages";

export default function SavedPage() {
  const {
    folders,
    isLoading: foldersLoading,
    mutate: mutateFolders,
  } = useSavedFolders();
  const [activeFolder, setActiveFolder] = useState<string>(ALL_FOLDERS);
  const [activeTab, setActiveTab] = useState<SavedTab>("threads");

  // The list query: when ALL_FOLDERS, fetch all saved; otherwise filter by folder
  // (UNFILED maps to the empty-string folder param the backend treats as NULL).
  const folderParam =
    activeFolder === ALL_FOLDERS
      ? undefined
      : activeFolder === UNFILED
      ? ""
      : activeFolder;

  const {
    threads,
    total: threadTotal,
    isLoading: threadsLoading,
    isError: threadsError,
    mutate: mutateThreads,
  } = useEmails({
    saved: true,
    folder: folderParam,
    page: 1,
    page_size: 100,
  });

  const {
    messages,
    isLoading: messagesLoading,
    isError: messagesError,
    mutate: mutateMessages,
  } = useSavedMessages({ folder: folderParam });

  // Aggregates for the rail + tab counts
  const totalThreads = useMemo(
    () => folders.reduce((sum, f) => sum + (f.thread_count ?? 0), 0),
    [folders],
  );
  const totalMessages = useMemo(
    () => folders.reduce((sum, f) => sum + (f.message_count ?? 0), 0),
    [folders],
  );

  const handleRefresh = () => {
    mutateThreads();
    mutateMessages();
    mutateFolders();
  };

  const namedFolders = folders.filter((f) => f.name != null) as Array<{
    name: string;
    count: number;
    thread_count: number;
    message_count: number;
  }>;
  const unfiledFolder = folders.find((f) => f.name == null);
  const unfiledCount = unfiledFolder?.count ?? 0;

  return (
    <div>
      <PageHeader
        title="Saved"
        subtitle="Whole threads or single emails you flagged for later — filed by client, project, or whatever folder you choose."
      />

      {/* Folder rail + list — two-column on lg+ */}
      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
        {/* Folder rail */}
        <aside className="lg:sticky lg:top-2 lg:self-start space-y-1">
          <FolderButton
            label="All saved"
            icon={Bookmark}
            count={totalThreads + totalMessages}
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
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Loading folders…
            </p>
          )}
        </aside>

        {/* Tabs + list */}
        <section>
          <div className="flex items-center gap-1 mb-3 border-b border-border/60">
            <TabButton
              active={activeTab === "threads"}
              onClick={() => setActiveTab("threads")}
              icon={MessagesSquare}
              label="Threads"
              count={
                folderParam !== undefined
                  ? threadTotal
                  : totalThreads
              }
            />
            <TabButton
              active={activeTab === "messages"}
              onClick={() => setActiveTab("messages")}
              icon={Mail}
              label="Single emails"
              count={
                folderParam !== undefined
                  ? messages.length
                  : totalMessages
              }
            />
          </div>

          {activeTab === "threads" ? (
            threadsError ? (
              <ErrorState
                title="Failed to load saved threads"
                description="Could not retrieve your saved items."
                onRetry={handleRefresh}
              />
            ) : threadsLoading ? (
              <TableSkeleton rows={6} />
            ) : threads.length === 0 ? (
              <EmptyState
                kind="threads"
                activeFolder={activeFolder}
              />
            ) : (
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
                              <span className="text-foreground/80">
                                {t.client_name}
                              </span>
                            )}
                            <span className="truncate">{t.client_email}</span>
                            {t.saved_folder && (
                              <FolderChip name={t.saved_folder} />
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
            )
          ) : messagesError ? (
            <ErrorState
              title="Failed to load saved emails"
              description="Could not retrieve your saved messages."
              onRetry={handleRefresh}
            />
          ) : messagesLoading ? (
            <TableSkeleton rows={6} />
          ) : messages.length === 0 ? (
            <EmptyState kind="messages" activeFolder={activeFolder} />
          ) : (
            <ul className="space-y-2">
              {messages.map((m) => (
                <li key={m.id}>
                  <Link
                    href={`/emails/${m.thread_id}`}
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
                            {m.thread_subject}
                          </h3>
                          <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
                            {m.direction === "inbound" ? "from client" : "sent by us"}
                          </span>
                        </div>
                        {/* The actual message preview — this is what makes per-message
                            saves more useful than per-thread for "I want this exact email." */}
                        <p className="text-sm text-foreground/85 leading-relaxed line-clamp-2 mb-1">
                          {m.body_text ?? "(no content)"}
                        </p>
                        <div className="flex items-center gap-2 text-[11px] text-muted-foreground flex-wrap">
                          <span className="truncate">{m.sender}</span>
                          {m.saved_folder && <FolderChip name={m.saved_folder} />}
                          {m.saved_note && (
                            <span
                              className="text-amber-700 dark:text-amber-400 truncate max-w-[260px]"
                              title={m.saved_note}
                            >
                              note: {m.saved_note}
                            </span>
                          )}
                        </div>
                      </div>
                      <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">
                        {relativeTime(m.received_at)}
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function FolderChip({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[10px] font-medium text-muted-foreground">
      <Folder className="w-3 h-3" strokeWidth={1.75} aria-hidden="true" />
      {name}
    </span>
  );
}

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Folder;
  label: string;
  count: number;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-2 px-3 py-2 -mb-px text-sm font-medium border-b-2 transition-colors",
        active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
      <span>{label}</span>
      <span
        className={cn(
          "inline-flex items-center justify-center min-w-[1.5rem] h-5 px-1.5 rounded text-[11px] font-semibold tabular-nums",
          active
            ? "bg-primary/10 text-primary"
            : "bg-muted text-muted-foreground",
        )}
      >
        {count}
      </span>
    </button>
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

function EmptyState({
  kind,
  activeFolder,
}: {
  kind: "threads" | "messages";
  activeFolder: string;
}) {
  const isAll = activeFolder === ALL_FOLDERS;
  const noun = kind === "threads" ? "saved threads" : "saved emails";
  const cta =
    kind === "threads"
      ? "Open any thread and click Save in the header to file the whole conversation."
      : "Open any thread and click the bookmark on a single message bubble to save just that email.";
  return (
    <div className="bg-card border border-border rounded-xl p-12 text-center">
      <Bookmark
        className="w-10 h-10 text-muted-foreground/60 mx-auto"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <h3 className="text-sm font-semibold text-foreground mt-3">
        {isAll ? `No ${noun} yet` : `Nothing in this folder`}
      </h3>
      <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
        {isAll ? cta : `No ${noun} matching this folder.`}
      </p>
    </div>
  );
}
