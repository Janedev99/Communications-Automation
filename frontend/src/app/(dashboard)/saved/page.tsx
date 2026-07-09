"use client";

import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import {
  ArrowUpDown,
  Bookmark,
  BookmarkCheck,
  ChevronRight,
  Folder,
  FolderInput,
  Inbox,
  Mail,
  MessagesSquare,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page-header";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { CategoryBadge } from "@/components/emails/category-badge";
import { FolderDeleteDialog } from "@/components/emails/folder-delete-dialog";
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
  createFolder,
  saveMessage,
  saveThread,
  useEmails,
  useSavedFolders,
  useSavedMessages,
  type SavedMessageSort,
  type ThreadSort,
} from "@/hooks/use-emails";
import { cn, relativeTime } from "@/lib/utils";
import type { EmailThreadListItem, SavedFolder, SavedMessageItem } from "@/lib/types";

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

// ── Folder rail tree ──────────────────────────────────────────────────────────
// After the Outlook import (Task 8), every folder shown in the rail — app
// folders and imported Outlook folders alike — is a registry row with an
// id/parent_id, so we build a single nested tree instead of splitting into a
// flat app-folder list + a separate live-Graph tree.

interface FolderNodeData {
  folder: SavedFolder;
  children: FolderNodeData[];
}

/**
 * Nests folders by `parent_id`. Legacy label-only folders (pre-registry rows
 * that never got an `id` migrated) can't participate in parent/child lookups
 * by id, so they're rendered as root-level leaves rather than dropped.
 */
function buildFolderTree(folders: SavedFolder[]): FolderNodeData[] {
  const byId = new Map<string, FolderNodeData>();
  folders.forEach((f) => {
    if (f.id) byId.set(f.id, { folder: f, children: [] });
  });
  const roots: FolderNodeData[] = [];
  folders.forEach((f) => {
    if (!f.id) {
      // No id to nest by — surface it as a leaf at the top level.
      roots.push({ folder: f, children: [] });
      return;
    }
    const node = byId.get(f.id)!;
    const parent = f.parent_id ? byId.get(f.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
}

function subtreeMatches(node: FolderNodeData, filter: string): boolean {
  if (!filter) return true;
  if ((node.folder.name ?? "").toLowerCase().includes(filter)) return true;
  return node.children.some((c) => subtreeMatches(c, filter));
}

/**
 * Finds a folder's node in the tree so its direct children can be listed
 * (for the "subfolders will be deleted too" note in the delete dialog).
 * Matches by id when both sides have one; falls back to name for legacy
 * label-only folders that never got an id migrated.
 */
function findNodeByFolder(
  nodes: FolderNodeData[],
  folder: SavedFolder,
): FolderNodeData | undefined {
  for (const node of nodes) {
    const sameFolder = folder.id
      ? node.folder.id === folder.id
      : node.folder.name === folder.name;
    if (sameFolder) return node;
    const found = findNodeByFolder(node.children, folder);
    if (found) return found;
  }
  return undefined;
}

/**
 * One row in the folder tree, recursing into its children. Mirrors the
 * compact `FolderRailItem` styling so the tree reads as part of the same
 * rail, with a chevron column for expand/collapse and hover-revealed
 * "+subfolder" / delete actions.
 */
function FolderTreeRow({
  node,
  depth,
  activeFolder,
  filter,
  onSelect,
  onDelete,
  onAddChild,
}: {
  node: FolderNodeData;
  depth: number;
  activeFolder: string;
  filter: string;
  onSelect: (name: string) => void;
  onDelete: (f: SavedFolder) => void;
  onAddChild: (parent: SavedFolder) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const f = node.folder;
  const nameMatch = !filter || (f.name ?? "").toLowerCase().includes(filter);
  const descMatch = node.children.some((c) => subtreeMatches(c, filter));
  if (filter && !nameMatch && !descMatch) return null;

  return (
    <div>
      <div
        className={cn(
          "group/row relative flex items-center rounded-md transition-colors",
          activeFolder === f.name
            ? "bg-card text-foreground ring-1 ring-border shadow-sm"
            : "text-muted-foreground hover:text-foreground hover:bg-accent",
        )}
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        <button
          type="button"
          onClick={() => node.children.length > 0 && setExpanded((v) => !v)}
          className={cn(
            "flex items-center justify-center w-4 h-6 shrink-0",
            node.children.length === 0 && "invisible",
          )}
          aria-label={expanded ? "Collapse folder" : "Expand folder"}
        >
          <ChevronRight
            className={cn("w-3 h-3 transition-transform", expanded && "rotate-90")}
            strokeWidth={1.75}
            aria-hidden="true"
          />
        </button>
        <button
          type="button"
          onClick={() => f.name && onSelect(f.name)}
          className="flex-1 flex items-center gap-1.5 py-1 pr-2 text-sm text-left min-w-0"
        >
          <Folder className="w-3.5 h-3.5 shrink-0" strokeWidth={1.75} aria-hidden="true" />
          <span className="flex-1 truncate">{f.name}</span>
          <span className="text-[10px] tabular-nums text-muted-foreground">{f.count}</span>
        </button>
        {f.id && (
          <button
            type="button"
            onClick={() => onAddChild(f)}
            className={cn(
              "shrink-0 p-0.5 rounded transition-colors",
              "text-muted-foreground/60 hover:text-foreground hover:bg-accent",
              "opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100",
            )}
            title="New subfolder"
            aria-label={`New subfolder in ${f.name}`}
          >
            <Plus className="w-3 h-3" strokeWidth={1.75} />
          </button>
        )}
        <button
          type="button"
          onClick={() => onDelete(f)}
          className={cn(
            "shrink-0 mr-1 p-0.5 rounded transition-colors",
            "text-muted-foreground/60 hover:text-destructive hover:bg-destructive/10",
            "opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100",
          )}
          title={`Delete folder "${f.name}"`}
          aria-label={`Delete folder ${f.name}`}
        >
          <Trash2 className="w-3 h-3" strokeWidth={1.75} />
        </button>
      </div>
      {expanded &&
        node.children.map((c) => (
          <FolderTreeRow
            key={c.folder.id}
            node={c}
            depth={depth + 1}
            activeFolder={activeFolder}
            filter={filter}
            onSelect={onSelect}
            onDelete={onDelete}
            onAddChild={onAddChild}
          />
        ))}
    </div>
  );
}

export default function SavedPage() {
  const {
    folders,
    isLoading: foldersLoading,
    mutate: mutateFolders,
  } = useSavedFolders();
  const [activeFolder, setActiveFolder] = useState<string>(ALL_FOLDERS);
  // Shared filter text for the folder tree (app folders + imported Outlook
  // folders — all registry rows post-import).
  const [folderQuery, setFolderQuery] = useState("");
  const [activeTab, setActiveTab] = useState<SavedTab>("threads");
  const [threadSort, setThreadSort] = useState<ThreadSort>("updated_desc");
  const [messageSort, setMessageSort] = useState<SavedMessageSort>("saved_desc");

  // Folder-deletion confirm state — a single dialog driven by the folder
  // pending deletion (not just its name), so the dialog can read
  // `outlook_item_count` for the Outlook-impact warning, rather than one
  // dialog per folder rendered in the DOM.
  const [pendingFolderDelete, setPendingFolderDelete] = useState<SavedFolder | null>(null);

  // Move-to-folder dialog state — shared between thread cards and message cards.
  const [moveTarget, setMoveTarget] = useState<MoveTarget | null>(null);

  // New-subfolder dialog state — set to the parent folder being added under.
  const [newSubfolderParent, setNewSubfolderParent] = useState<SavedFolder | null>(null);

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

  const namedFolders = folders.filter(
    (f): f is SavedFolder & { name: string } => f.name != null,
  );
  const unfiledFolder = folders.find((f) => f.name == null);
  const unfiledCount = unfiledFolder?.count ?? 0;

  const folderTree = buildFolderTree(namedFolders);
  const folderFilter = folderQuery.trim().toLowerCase();

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
          {/* Registry-driven folder tree: after the Outlook import, every
              folder — app-created or imported from Outlook — is a row in
              the same registry with an id/parent_id, so this renders one
              nested tree instead of a flat app-folder list plus a separate
              live-Graph tree. */}
          {namedFolders.length > 0 && (
            <div className="pt-2 mt-2 border-t border-border/60">
              <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Folders
              </p>
              <input
                value={folderQuery}
                onChange={(e) => setFolderQuery(e.target.value)}
                placeholder="Filter folders…"
                className="mb-1 mx-1 h-6 w-[calc(100%-0.5rem)] rounded-md border border-border bg-card px-2 text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
              <div className="space-y-0.5">
                {folderTree.map((node) => (
                  <FolderTreeRow
                    key={node.folder.id ?? node.folder.name}
                    node={node}
                    depth={0}
                    activeFolder={activeFolder}
                    filter={folderFilter}
                    onSelect={(name) => setActiveFolder(name)}
                    onDelete={(f) => setPendingFolderDelete(f)}
                    onAddChild={(parent) => setNewSubfolderParent(parent)}
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
          Items survive — they just move to the "No folder" bucket. This
          is the single folder-delete confirmation path (dedicated
          component, not the generic <ConfirmDialog> used elsewhere on
          this page) so it can read `outlook_item_count` for the
          Outlook-impact warning and note affected subfolders. */}
      {pendingFolderDelete && (
        <FolderDeleteDialog
          folder={pendingFolderDelete}
          childNames={
            findNodeByFolder(folderTree, pendingFolderDelete)
              ?.children.map((c) => c.folder.name)
              .filter((n): n is string => n != null) ?? []
          }
          onClose={() => setPendingFolderDelete(null)}
          onDeleted={() => {
            mutateFolders();
            mutateThreads();
            mutateMessages();
            // If the deleted folder was the active one, pop back to All
            // saved so we don't render an empty filtered view.
            if (activeFolder === pendingFolderDelete.name) {
              setActiveFolder(ALL_FOLDERS);
            }
          }}
        />
      )}

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

      {/* New-subfolder dialog, opened from the "+" on a tree row. */}
      {newSubfolderParent && (
        <NewSubfolderDialog
          parent={newSubfolderParent}
          onClose={() => setNewSubfolderParent(null)}
          onCreated={() => {
            mutateFolders();
            setNewSubfolderParent(null);
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
      {/* Leading spacer matches the Outlook nodes' expand-chevron column so the
          folder icons line up across the whole unified list. */}
      <span className="w-4 shrink-0" aria-hidden="true" />
      <button
        onClick={onClick}
        className="flex-1 flex items-center gap-1.5 py-1 pr-2 text-sm text-left min-w-0"
      >
        <Icon
          className={cn(
            "w-3.5 h-3.5 shrink-0",
            muted && !active && "text-muted-foreground/70",
          )}
          strokeWidth={1.75}
          aria-hidden="true"
        />
        <span className="flex-1 truncate">{label}</span>
        <span className="text-[10px] tabular-nums text-muted-foreground">
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
            "shrink-0 mr-1 p-0.5 rounded transition-colors",
            "text-muted-foreground/60 hover:text-destructive hover:bg-destructive/10",
            "opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100",
          )}
          title={`Delete folder "${label}"`}
          aria-label={`Delete folder ${label}`}
        >
          <Trash2 className="w-3 h-3" strokeWidth={1.75} />
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
  // Same rationale as SaveThreadDialog: the registry can hold hundreds of
  // folders post-Outlook-import, so this is a search-filtered, height-capped
  // list rather than a plain dropdown.
  const [folderQuery, setFolderQuery] = useState("");
  // Combobox-style keyboard nav: index into "No folder" + filtered folders +
  // "New folder…", driven entirely from the search input so keyboard users
  // never have to tab through every row.
  const [activeIndex, setActiveIndex] = useState(0);

  // Reset the active option whenever the query changes so a fresh search
  // doesn't leave the highlight pointing at a now-hidden row.
  useEffect(() => {
    setActiveIndex(0);
  }, [folderQuery]);

  const isNewFolder = picked === NEW_FOLDER_VALUE;
  const targetFolder = isNewFolder
    ? newFolderName.trim()
    : picked === NO_FOLDER_VALUE
    ? null
    : picked;

  const folderFilter = folderQuery.trim().toLowerCase();
  const filteredFolders = folderFilter
    ? existingFolders.filter((name) => name.toLowerCase().includes(folderFilter))
    : existingFolders;

  // Option 0 = "No folder", options 1..N = filteredFolders, option N+1 =
  // "+ New folder…" — this is the same order the list renders in.
  const optionCount = filteredFolders.length + 2;
  const safeActiveIndex = Math.min(activeIndex, optionCount - 1);
  const optionId = (index: number) => `move-folder-option-${index}`;

  // Always-visible selection line — the old SelectTrigger always showed the
  // chosen folder; a filtered search can hide the selected row entirely, so
  // this keeps the current pick visible regardless of the query.
  const selectedFolderLabel = isNewFolder
    ? newFolderName.trim() || "New folder…"
    : picked === NO_FOLDER_VALUE
    ? "No folder"
    : picked;

  useEffect(() => {
    document
      .getElementById(optionId(safeActiveIndex))
      ?.scrollIntoView({ block: "nearest" });
  }, [safeActiveIndex]);

  const handleFolderSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, optionCount - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (safeActiveIndex === 0) {
        setPicked(NO_FOLDER_VALUE);
      } else if (safeActiveIndex === optionCount - 1) {
        setPicked(NEW_FOLDER_VALUE);
      } else {
        const folder = filteredFolders[safeActiveIndex - 1];
        if (folder) setPicked(folder);
      }
    }
  };

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
          <label className="text-xs font-medium text-foreground" htmlFor="move-folder-search">
            Folder
          </label>
          <input
            id="move-folder-search"
            type="text"
            value={folderQuery}
            onChange={(e) => setFolderQuery(e.target.value)}
            onKeyDown={handleFolderSearchKeyDown}
            placeholder="Search folders…"
            role="combobox"
            aria-expanded="true"
            aria-controls="move-folder-listbox"
            aria-activedescendant={optionId(safeActiveIndex)}
            className="flex h-8 w-full rounded-md border border-border bg-card px-2.5 text-sm outline-none placeholder:text-muted-foreground transition-colors hover:border-foreground/20 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
          />
          <p className="text-xs text-muted-foreground truncate">
            Selected: {selectedFolderLabel}
          </p>
          <div
            id="move-folder-listbox"
            role="listbox"
            aria-label="Folders"
            className="max-h-64 overflow-y-auto rounded-lg border border-border bg-popover p-1"
          >
            <FolderOptionRow
              id={optionId(0)}
              label="No folder"
              muted
              selected={picked === NO_FOLDER_VALUE}
              active={safeActiveIndex === 0}
              onClick={() => setPicked(NO_FOLDER_VALUE)}
            />
            {filteredFolders.map((name, i) => (
              <FolderOptionRow
                key={name}
                id={optionId(i + 1)}
                label={name}
                selected={picked === name}
                active={safeActiveIndex === i + 1}
                onClick={() => setPicked(name)}
              />
            ))}
            {folderFilter && filteredFolders.length === 0 && existingFolders.length > 0 && (
              <p
                className="px-2 py-1.5 text-xs text-muted-foreground"
                aria-live="polite"
              >
                No folders match &quot;{folderQuery}&quot;.
              </p>
            )}
            <FolderOptionRow
              id={optionId(filteredFolders.length + 1)}
              label="+ New folder…"
              accent
              selected={isNewFolder}
              active={safeActiveIndex === filteredFolders.length + 1}
              onClick={() => setPicked(NEW_FOLDER_VALUE)}
            />
          </div>
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

/**
 * One row in the search-filtered folder list used by MoveToFolderDialog.
 * Mirrors SaveThreadDialog's `FolderOptionRow` so the two "pick a folder"
 * surfaces read as the same control.
 */
function FolderOptionRow({
  id,
  label,
  selected,
  active,
  muted,
  accent,
  onClick,
}: {
  id?: string;
  label: string;
  selected: boolean;
  active?: boolean;
  muted?: boolean;
  accent?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      id={id}
      role="option"
      aria-selected={selected}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-left transition-colors",
        selected
          ? "bg-accent text-accent-foreground"
          : active
          ? "bg-accent/60"
          : "hover:bg-accent/60",
      )}
    >
      <span
        className={cn(
          "flex-1 truncate",
          muted && "text-muted-foreground",
          accent && "text-primary",
        )}
      >
        {label}
      </span>
    </button>
  );
}

// ── New-subfolder dialog ─────────────────────────────────────────────────────
// Minimal controlled-input dialog for the tree row's hover "+" action —
// mirrors MoveToFolderDialog's shape (Dialog + single field + Cancel/submit
// footer) rather than a window.prompt.

function NewSubfolderDialog({
  parent,
  onClose,
  onCreated,
}: {
  parent: SavedFolder;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = !submitting && name.trim().length > 0;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const trimmed = name.trim();
      await createFolder({ name: trimmed, parent_id: parent.id ?? null });
      toast.success(`Created folder "${trimmed}".`);
      onCreated();
    } catch (err: unknown) {
      // Backend rejects duplicate names with a 409 — uniqueness is global
      // (case-insensitive) across the whole folder tree, not just siblings
      // under the same parent. Surface its detail message verbatim, same
      // pattern as delete/move.
      toast.error(err instanceof Error ? err.message : "Could not create folder.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Folder className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
            New subfolder
          </DialogTitle>
          <DialogDescription className="truncate" title={parent.name ?? ""}>
            Inside &quot;{parent.name}&quot;
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5 py-2">
          <label className="text-xs font-medium text-foreground">Folder name</label>
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
            }}
            placeholder="e.g. 2025 Return"
            maxLength={128}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? "Creating…" : "Create"}
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
