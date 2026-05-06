"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowDownAZ,
  ArrowUpDown,
  Bookmark,
  BookmarkCheck,
  Folder,
  FolderInput,
  Inbox,
  Mail,
  MessagesSquare,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page-header";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { CategoryBadge } from "@/components/emails/category-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  deleteSavedFolder,
  saveMessage,
  saveThread,
  useEmails,
  useSavedFolders,
  useSavedMessages,
  type SavedMessageSort,
  type ThreadSort,
} from "@/hooks/use-emails";
import { cn, relativeTime } from "@/lib/utils";
import type { EmailThreadListItem, SavedMessageItem } from "@/lib/types";

const ALL_FOLDERS = "__all__";
const UNFILED = "__unfiled__";

type SavedTab = "threads" | "messages";

// Move target — narrow type so the dialog handler knows which mutator to call.
type MoveTarget =
  | { kind: "thread"; thread: EmailThreadListItem }
  | { kind: "message"; message: SavedMessageItem };

// ── Sort options shown in the dropdown ────────────────────────────────────────
// Keep separate per-tab because the message list sorts by saved_at (when YOU
// saved it), while the thread list sorts by updated_at (when the thread last
// changed). Both expose the same subject/client axes.

const THREAD_SORT_OPTIONS: { value: ThreadSort; label: string }[] = [
  { value: "updated_desc", label: "Newest first" },
  { value: "updated_asc", label: "Oldest first" },
  { value: "subject_asc", label: "Subject A → Z" },
  { value: "subject_desc", label: "Subject Z → A" },
  { value: "client_asc", label: "Client A → Z" },
  { value: "client_desc", label: "Client Z → A" },
];

const MESSAGE_SORT_OPTIONS: { value: SavedMessageSort; label: string }[] = [
  { value: "saved_desc", label: "Recently saved" },
  { value: "saved_asc", label: "Oldest saved first" },
  { value: "subject_asc", label: "Subject A → Z" },
  { value: "subject_desc", label: "Subject Z → A" },
  { value: "client_asc", label: "Client A → Z" },
  { value: "client_desc", label: "Client Z → A" },
];

export default function SavedPage() {
  const {
    folders,
    isLoading: foldersLoading,
    mutate: mutateFolders,
  } = useSavedFolders();
  const [activeFolder, setActiveFolder] = useState<string>(ALL_FOLDERS);
  const [activeTab, setActiveTab] = useState<SavedTab>("threads");
  const [threadSort, setThreadSort] = useState<ThreadSort>("updated_desc");
  const [messageSort, setMessageSort] = useState<SavedMessageSort>("saved_desc");

  // Folder-deletion confirm state — we use a single ConfirmDialog driven by
  // a "pendingDelete" string (folder name to delete) rather than one
  // dialog per folder, which would render N dialogs in the DOM.
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Move-to-folder dialog state — shared between thread cards and message cards.
  const [moveTarget, setMoveTarget] = useState<MoveTarget | null>(null);

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
    sort: threadSort,
    page: 1,
    page_size: 100,
  });

  const {
    messages,
    isLoading: messagesLoading,
    isError: messagesError,
    mutate: mutateMessages,
  } = useSavedMessages({ folder: folderParam, sort: messageSort });

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

  // Confirm + execute folder deletion. The backend rejects with 409 if the
  // folder still has items — we surface that message verbatim so the user
  // gets the "move them first" prompt without us re-implementing the rule.
  const handleDeleteFolder = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteSavedFolder(pendingDelete);
      toast.success(`Deleted folder "${pendingDelete}".`);
      // If the deleted folder was the active one, pop back to All saved
      // so we don't render an empty filtered view.
      if (activeFolder === pendingDelete) {
        setActiveFolder(ALL_FOLDERS);
      }
      mutateFolders();
      mutateThreads();
      mutateMessages();
      setPendingDelete(null);
    } catch (err: unknown) {
      // The 409 detail tells the user exactly what to do — pass through.
      toast.error(err instanceof Error ? err.message : "Could not delete folder.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Saved"
        subtitle="Whole threads or single emails you flagged for later — filed by client, project, or whatever folder you choose."
      />

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
        {/* Folder rail */}
        <aside className="lg:sticky lg:top-2 lg:self-start space-y-1">
          <FolderRailItem
            label="All saved"
            icon={Bookmark}
            count={totalThreads + totalMessages}
            active={activeFolder === ALL_FOLDERS}
            onClick={() => setActiveFolder(ALL_FOLDERS)}
          />
          {unfiledCount > 0 && (
            <FolderRailItem
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
                  <FolderRailItem
                    key={f.name}
                    label={f.name}
                    icon={Folder}
                    count={f.count}
                    active={activeFolder === f.name}
                    onClick={() => setActiveFolder(f.name)}
                    onDelete={() => setPendingDelete(f.name)}
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

        {/* Tabs + sort + list */}
        <section>
          <div className="flex items-center gap-1 mb-3 border-b border-border/60">
            <TabButton
              active={activeTab === "threads"}
              onClick={() => setActiveTab("threads")}
              icon={MessagesSquare}
              label="Threads"
              count={folderParam !== undefined ? threadTotal : totalThreads}
            />
            <TabButton
              active={activeTab === "messages"}
              onClick={() => setActiveTab("messages")}
              icon={Mail}
              label="Single emails"
              count={folderParam !== undefined ? messages.length : totalMessages}
            />
            {/* Sort dropdown — right-aligned, scoped to the active tab.
                The two tabs sort by different default axes (saved_at vs
                updated_at), so each gets its own state. */}
            <div className="ml-auto pb-2 pr-1">
              {activeTab === "threads" ? (
                <SortPicker
                  value={threadSort}
                  options={THREAD_SORT_OPTIONS}
                  onChange={(v) => setThreadSort(v as ThreadSort)}
                />
              ) : (
                <SortPicker
                  value={messageSort}
                  options={MESSAGE_SORT_OPTIONS}
                  onChange={(v) => setMessageSort(v as SavedMessageSort)}
                />
              )}
            </div>
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
              <EmptyState kind="threads" activeFolder={activeFolder} />
            ) : (
              <ul className="space-y-2">
                {threads.map((t) => (
                  <ThreadCard
                    key={t.id}
                    thread={t}
                    onMove={() => setMoveTarget({ kind: "thread", thread: t })}
                  />
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
                <MessageCard
                  key={m.id}
                  message={m}
                  onMove={() => setMoveTarget({ kind: "message", message: m })}
                />
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Folder-delete confirm. The backend follows the Outlook /
          Gmail-label model: deleting a folder unfiles every item that
          was in it (sets saved_folder = NULL) but keeps them saved.
          Items survive — they just move to the "No folder" bucket. */}
      <ConfirmDialog
        open={!!pendingDelete}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={`Delete folder "${pendingDelete ?? ""}"?`}
        description={
          (() => {
            const folder = namedFolders.find((f) => f.name === pendingDelete);
            if (!folder || folder.count === 0) {
              return "This folder is empty. It will be removed from your folder list.";
            }
            const parts: string[] = [];
            if (folder.thread_count > 0) {
              parts.push(
                `${folder.thread_count} thread${folder.thread_count === 1 ? "" : "s"}`,
              );
            }
            if (folder.message_count > 0) {
              parts.push(
                `${folder.message_count} email${folder.message_count === 1 ? "" : "s"}`,
              );
            }
            return (
              `${parts.join(" and ")} in this folder will stay saved — ` +
              "they'll just move to \"No folder.\" The folder label is " +
              "removed from your folder list."
            );
          })()
        }
        confirmLabel="Delete folder"
        confirmVariant="destructive"
        onConfirm={handleDeleteFolder}
        loading={deleting}
      />

      {/* Move-to-folder dialog. Reuses saveThread / saveMessage internally
          since "move" is just a save with a different folder. */}
      {moveTarget && (
        <MoveToFolderDialog
          target={moveTarget}
          existingFolders={namedFolders.map((f) => f.name)}
          onClose={() => setMoveTarget(null)}
          onMoved={() => {
            handleRefresh();
            setMoveTarget(null);
          }}
        />
      )}
    </div>
  );
}

// ── Card components ──────────────────────────────────────────────────────────
// Pulled out so the move button doesn't trigger the card's link — having
// nested clickable elements requires a wrapping div, not a wrapping <a>.

function ThreadCard({
  thread: t,
  onMove,
}: {
  thread: EmailThreadListItem;
  onMove: () => void;
}) {
  return (
    <li className="bg-card border border-border rounded-lg hover:bg-accent/40 hover:border-foreground/20 transition-colors">
      <div className="flex items-start gap-3 px-4 py-3">
        <Link
          href={`/emails/${t.id}`}
          className="flex items-start justify-between gap-3 flex-1 min-w-0"
        >
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
              {t.saved_folder && <FolderChip name={t.saved_folder} />}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            <CategoryBadge category={t.category} />
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {relativeTime(t.updated_at)}
            </span>
          </div>
        </Link>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onMove();
          }}
          className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title="Move to a different folder"
          aria-label="Move thread to a different folder"
        >
          <FolderInput className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
          Move
        </button>
      </div>
    </li>
  );
}

function MessageCard({
  message: m,
  onMove,
}: {
  message: SavedMessageItem;
  onMove: () => void;
}) {
  return (
    <li className="bg-card border border-border rounded-lg hover:bg-accent/40 hover:border-foreground/20 transition-colors">
      <div className="flex items-start gap-3 px-4 py-3">
        <Link
          href={`/emails/${m.thread_id}`}
          className="flex items-start justify-between gap-3 flex-1 min-w-0"
        >
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
        </Link>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onMove();
          }}
          className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title="Move to a different folder"
          aria-label="Move email to a different folder"
        >
          <FolderInput className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
          Move
        </button>
      </div>
    </li>
  );
}

// ── Sort + folder rail + chips ───────────────────────────────────────────────

function SortPicker({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (next: string) => void;
}) {
  return (
    <div className="inline-flex items-center gap-1.5">
      <ArrowUpDown
        className="w-3.5 h-3.5 text-muted-foreground"
        strokeWidth={1.75}
        aria-hidden="true"
      />
      <Select value={value} onValueChange={(v: string | null) => v && onChange(v)}>
        <SelectTrigger className="h-7 text-xs min-w-[150px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value} className="text-xs">
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
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

/**
 * Folder row in the rail. When ``onDelete`` is provided, a hover-revealed
 * trash icon appears at the right of the row. Clicking the icon doesn't
 * select the folder (stopPropagation) so the user can delete without
 * having to navigate into the folder first.
 */
function FolderRailItem({
  label,
  icon: Icon,
  count,
  active,
  onClick,
  onDelete,
  muted,
}: {
  label: string;
  icon: typeof Folder;
  count: number;
  active: boolean;
  onClick: () => void;
  onDelete?: () => void;
  muted?: boolean;
}) {
  return (
    <div
      className={cn(
        "group/row relative flex items-center rounded-md transition-colors",
        active
          ? "bg-card text-foreground ring-1 ring-border shadow-sm"
          : "text-muted-foreground hover:text-foreground hover:bg-accent",
      )}
    >
      <button
        onClick={onClick}
        className="flex-1 flex items-center gap-2.5 px-3 py-2 text-sm font-medium text-left min-w-0"
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
      {onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className={cn(
            "shrink-0 mr-1 p-1 rounded transition-colors",
            "text-muted-foreground/60 hover:text-destructive hover:bg-destructive/10",
            "opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100",
          )}
          title={`Delete folder "${label}"`}
          aria-label={`Delete folder ${label}`}
        >
          <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
        </button>
      )}
    </div>
  );
}

// ── Move-to-folder dialog ────────────────────────────────────────────────────

const NEW_FOLDER_VALUE = "__new__";
const NO_FOLDER_VALUE = "__none__";

function MoveToFolderDialog({
  target,
  existingFolders,
  onClose,
  onMoved,
}: {
  target: MoveTarget;
  existingFolders: string[];
  onClose: () => void;
  onMoved: () => void;
}) {
  const currentFolder =
    target.kind === "thread"
      ? target.thread.saved_folder
      : target.message.saved_folder;

  const [picked, setPicked] = useState<string>(currentFolder ?? NO_FOLDER_VALUE);
  const [newFolderName, setNewFolderName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isNewFolder = picked === NEW_FOLDER_VALUE;
  const targetFolder = isNewFolder
    ? newFolderName.trim()
    : picked === NO_FOLDER_VALUE
    ? null
    : picked;

  const noChange =
    !isNewFolder &&
    ((picked === NO_FOLDER_VALUE && currentFolder == null) ||
      picked === currentFolder);

  const canSubmit =
    !submitting && !noChange && (!isNewFolder || newFolderName.trim().length > 0);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      // Both kinds use the existing save endpoints with a different folder —
      // "move" is just a re-save under a new folder, so we get audit logging
      // (email.save_updated / email.message_save_updated) for free.
      if (target.kind === "thread") {
        await saveThread(target.thread.id, {
          folder: targetFolder ?? null,
          note: null,
        });
      } else {
        await saveMessage(target.message.thread_id, target.message.id, {
          folder: targetFolder ?? null,
          note: null,
        });
      }
      toast.success(
        targetFolder
          ? `Moved to "${targetFolder}".`
          : "Moved out of folder.",
      );
      onMoved();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not move.");
    } finally {
      setSubmitting(false);
    }
  };

  const subjectLine =
    target.kind === "thread"
      ? target.thread.subject
      : target.message.thread_subject;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderInput className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
            Move {target.kind === "thread" ? "thread" : "email"}
          </DialogTitle>
          <DialogDescription className="truncate" title={subjectLine}>
            {subjectLine}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5 py-2">
          <label className="text-xs font-medium text-foreground">Folder</label>
          <Select value={picked} onValueChange={(v: string | null) => v && setPicked(v)}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="No folder" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_FOLDER_VALUE}>
                <span className="text-muted-foreground">No folder</span>
              </SelectItem>
              {existingFolders.map((name) => (
                <SelectItem key={name} value={name}>
                  <span className="truncate">{name}</span>
                </SelectItem>
              ))}
              <SelectItem value={NEW_FOLDER_VALUE}>
                <span className="text-primary">+ New folder…</span>
              </SelectItem>
            </SelectContent>
          </Select>
          {isNewFolder && (
            <Input
              autoFocus
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="e.g. Smith — 2025 Return"
              maxLength={128}
              className="mt-1.5"
            />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? "Moving…" : "Move"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Empty state ──────────────────────────────────────────────────────────────

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
        {isAll ? `No ${noun} yet` : "Nothing in this folder"}
      </h3>
      <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
        {isAll ? cta : `No ${noun} matching this folder.`}
      </p>
    </div>
  );
}
