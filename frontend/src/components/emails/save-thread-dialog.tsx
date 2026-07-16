"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { Bookmark } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  saveMessage,
  saveThread,
  useSavedFolders,
} from "@/hooks/use-emails";
import { cn } from "@/lib/utils";
import type { EmailThread } from "@/lib/types";

/**
 * The dialog is granularity-agnostic: pass `kind: "thread"` to save the
 * whole thread, or `kind: "message"` with a messageId to save just one
 * bubble. Per Jane: "so often it's just the singular email" — but
 * sometimes she wants the entire conversation, hence both.
 */
type SaveTarget =
  | { kind: "thread" }
  | { kind: "message"; messageId: string };

interface SaveThreadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  thread: EmailThread;
  onSaved: (updated: EmailThread) => void;
  /** Defaults to whole-thread save for back-compat. */
  target?: SaveTarget;
}

const NEW_FOLDER_VALUE = "__new__";
const NO_FOLDER_VALUE = "__none__";

/**
 * Save-to-folder dialog. Mirrors Jane's Outlook-folder workflow: pick an
 * existing folder, or type a new one (e.g. a client name), and optionally
 * leave a note explaining why this thread matters.
 */
export function SaveThreadDialog({
  open,
  onOpenChange,
  thread,
  onSaved,
  target = { kind: "thread" },
}: SaveThreadDialogProps) {
  const { folders, mutate: mutateFolders } = useSavedFolders();

  // Resolve the entity-specific state (thread vs single message) so the
  // rest of the component can work in terms of `current` regardless.
  const targetMessage =
    target.kind === "message"
      ? thread.messages.find((m) => m.id === target.messageId) ?? null
      : null;

  const current = target.kind === "message"
    ? {
        isSaved: targetMessage?.is_saved ?? false,
        folder: targetMessage?.saved_folder ?? null,
        note: targetMessage?.saved_note ?? null,
      }
    : {
        isSaved: thread.is_saved,
        folder: thread.saved_folder,
        note: thread.saved_note,
      };

  // Folder picker state — sentinels for "new folder" and "no folder"
  const [pickedFolder, setPickedFolder] = useState<string>(NO_FOLDER_VALUE);
  const [newFolderName, setNewFolderName] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  // Registry can hold hundreds of folders post-Outlook-import, so the picker
  // is a search-filtered, height-capped list rather than a plain dropdown.
  const [folderQuery, setFolderQuery] = useState("");
  // Combobox-style keyboard nav: index into "No folder" + filtered folders +
  // "New folder…", driven entirely from the search input so keyboard users
  // never have to tab through every row.
  const [activeIndex, setActiveIndex] = useState(0);

  // Pre-fill from current state when dialog opens (re-saves edit metadata)
  useEffect(() => {
    if (!open) return;
    if (current.isSaved) {
      setPickedFolder(current.folder ?? NO_FOLDER_VALUE);
    } else {
      setPickedFolder(NO_FOLDER_VALUE);
    }
    setNewFolderName("");
    setNote(current.note ?? "");
    setFolderQuery("");
    setActiveIndex(0);
  }, [open, current.isSaved, current.folder, current.note]);

  // Reset the active option whenever the query changes so a fresh search
  // doesn't leave the highlight pointing at a now-hidden row.
  useEffect(() => {
    setActiveIndex(0);
  }, [folderQuery]);

  const isNewFolder = pickedFolder === NEW_FOLDER_VALUE;
  const folderToSubmit = isNewFolder
    ? newFolderName.trim()
    : pickedFolder === NO_FOLDER_VALUE
    ? null
    : pickedFolder;

  // Validation: if user chose "New folder", they must type a name
  const canSubmit =
    !saving && (!isNewFolder || newFolderName.trim().length > 0);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    try {
      const body = {
        folder: folderToSubmit ?? null,
        note: note.trim() || null,
      };
      const updated =
        target.kind === "message"
          ? await saveMessage(thread.id, target.messageId, body)
          : await saveThread(thread.id, body);
      onSaved(updated);
      // Folder counts depend on both thread and message saves — refresh
      // the rail so a newly-created folder shows up immediately.
      mutateFolders();
      const subject =
        target.kind === "message" ? "this email" : "this thread";
      toast.success(
        folderToSubmit
          ? `Saved ${subject} to "${folderToSubmit}".`
          : `Saved ${subject}.`,
      );
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  // Existing folder options, sorted with the unsorted bucket first
  const existingFolders = folders.filter((f) => f.name != null) as Array<{
    name: string;
    count: number;
  }>;

  // Case-insensitive name filter — "No folder" and "New folder…" stay
  // visible regardless of the query so the escape hatches are never hidden.
  const folderFilter = folderQuery.trim().toLowerCase();
  const filteredFolders = folderFilter
    ? existingFolders.filter((f) => f.name.toLowerCase().includes(folderFilter))
    : existingFolders;

  const isMessageTarget = target.kind === "message";
  const titleAction = current.isSaved ? "Update saved" : "Save this";
  const titleSubject = isMessageTarget ? "email" : "thread";

  // Option 0 = "No folder", options 1..N = filteredFolders, option N+1 =
  // "+ New folder…" — this is the same order the list renders in.
  const optionCount = filteredFolders.length + 2;
  const safeActiveIndex = Math.min(activeIndex, optionCount - 1);
  const optionId = (index: number) => `save-folder-option-${index}`;

  // Always-visible selection line — the old SelectTrigger always showed the
  // chosen folder; a filtered search can hide the selected row entirely, so
  // this keeps the current pick visible regardless of the query.
  const selectedFolderLabel = isNewFolder
    ? newFolderName.trim() || "New folder…"
    : pickedFolder === NO_FOLDER_VALUE
    ? "No folder"
    : pickedFolder;

  useEffect(() => {
    if (!open) return;
    document
      .getElementById(optionId(safeActiveIndex))
      ?.scrollIntoView({ block: "nearest" });
  }, [safeActiveIndex, open]);

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
        setPickedFolder(NO_FOLDER_VALUE);
      } else if (safeActiveIndex === optionCount - 1) {
        setPickedFolder(NEW_FOLDER_VALUE);
      } else {
        const folder = filteredFolders[safeActiveIndex - 1];
        if (folder) setPickedFolder(folder.name);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bookmark className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
            {titleAction} {titleSubject}
          </DialogTitle>
          <DialogDescription>
            {isMessageTarget
              ? "File this single email under a folder so you can find it later — the rest of the thread stays untouched."
              : "File this thread in a folder so you can find it later. Saved threads stay searchable from the Saved tab."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground" htmlFor="save-folder-search">
              Folder
            </label>
            <input
              id="save-folder-search"
              type="text"
              value={folderQuery}
              onChange={(e) => setFolderQuery(e.target.value)}
              onKeyDown={handleFolderSearchKeyDown}
              placeholder="Search folders…"
              role="combobox"
              aria-expanded="true"
              aria-controls="save-folder-listbox"
              aria-activedescendant={optionId(safeActiveIndex)}
              className="flex h-8 w-full rounded-md border border-border bg-card px-2.5 text-sm outline-none placeholder:text-muted-foreground transition-colors hover:border-foreground/20 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
            />
            <p className="text-xs text-muted-foreground truncate">
              Selected: {selectedFolderLabel}
            </p>
            <div
              id="save-folder-listbox"
              role="listbox"
              aria-label="Folders"
              className="max-h-64 overflow-y-auto rounded-lg border border-border bg-popover p-1"
            >
              <FolderOptionRow
                id={optionId(0)}
                label="No folder (just save)"
                muted
                selected={pickedFolder === NO_FOLDER_VALUE}
                active={safeActiveIndex === 0}
                onClick={() => setPickedFolder(NO_FOLDER_VALUE)}
              />
              {filteredFolders.map((folder, i) => (
                <FolderOptionRow
                  key={folder.name}
                  id={optionId(i + 1)}
                  label={folder.name}
                  count={folder.count}
                  selected={pickedFolder === folder.name}
                  active={safeActiveIndex === i + 1}
                  onClick={() => setPickedFolder(folder.name)}
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
                onClick={() => setPickedFolder(NEW_FOLDER_VALUE)}
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

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground" htmlFor="save-note">
              Note <span className="text-muted-foreground">(optional)</span>
            </label>
            <Textarea
              id="save-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why this thread matters — e.g. client confirmed extension, or contains W-2 info."
              maxLength={2000}
              rows={3}
              className="resize-none"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {saving ? "Saving…" : current.isSaved ? "Update" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * One row in the search-filtered folder list. Mirrors the look of the old
 * `SelectItem` rows (rounded, padded, accent-highlighted when
 * selected/hovered) so swapping the dropdown for a plain scrollable list
 * doesn't change how the picker reads visually.
 */
function FolderOptionRow({
  id,
  label,
  count,
  selected,
  active,
  muted,
  accent,
  onClick,
}: {
  id?: string;
  label: string;
  count?: number;
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
      {count !== undefined && (
        <span className="text-[11px] text-muted-foreground tabular-nums">
          {count}
        </span>
      )}
    </button>
  );
}
