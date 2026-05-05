"use client";

import { useEffect, useState } from "react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { saveThread, useSavedFolders } from "@/hooks/use-emails";
import type { EmailThread } from "@/lib/types";

interface SaveThreadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  thread: EmailThread;
  onSaved: (updated: EmailThread) => void;
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
}: SaveThreadDialogProps) {
  const { folders } = useSavedFolders();

  // Folder picker state — sentinels for "new folder" and "no folder"
  const [pickedFolder, setPickedFolder] = useState<string>(NO_FOLDER_VALUE);
  const [newFolderName, setNewFolderName] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  // Pre-fill from current state when dialog opens (re-saves edit metadata)
  useEffect(() => {
    if (!open) return;
    if (thread.is_saved) {
      setPickedFolder(thread.saved_folder ?? NO_FOLDER_VALUE);
    } else {
      setPickedFolder(NO_FOLDER_VALUE);
    }
    setNewFolderName("");
    setNote(thread.saved_note ?? "");
  }, [open, thread.is_saved, thread.saved_folder, thread.saved_note]);

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
      const updated = await saveThread(thread.id, {
        folder: folderToSubmit ?? null,
        note: note.trim() || null,
      });
      onSaved(updated);
      toast.success(
        folderToSubmit
          ? `Saved to "${folderToSubmit}".`
          : "Saved.",
      );
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not save thread.");
    } finally {
      setSaving(false);
    }
  };

  // Existing folder options, sorted with the unsorted bucket first
  const existingFolders = folders.filter((f) => f.name != null) as Array<{
    name: string;
    count: number;
  }>;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bookmark className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
            {thread.is_saved ? "Update saved thread" : "Save this thread"}
          </DialogTitle>
          <DialogDescription>
            File this thread in a folder so you can find it later.
            Saved threads stay searchable from the Saved tab.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground" htmlFor="save-folder">
              Folder
            </label>
            <Select value={pickedFolder} onValueChange={(v: string | null) => v && setPickedFolder(v)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="No folder" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_FOLDER_VALUE}>
                  <span className="text-muted-foreground">No folder (just save)</span>
                </SelectItem>
                {existingFolders.length > 0 && (
                  <>
                    {existingFolders.map((folder) => (
                      <SelectItem key={folder.name} value={folder.name}>
                        <span className="truncate">{folder.name}</span>
                        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                          {folder.count}
                        </span>
                      </SelectItem>
                    ))}
                  </>
                )}
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
            {saving ? "Saving…" : thread.is_saved ? "Update" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
