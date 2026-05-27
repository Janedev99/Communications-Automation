"use client";

import { useEffect, useState } from "react";
import { Bookmark } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSavedFolders } from "@/hooks/use-emails";

const NEW_FOLDER_VALUE = "__new__";
const NO_FOLDER_VALUE = "__none__";

interface BulkSaveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Number of selected threads — shown in the title. */
  count: number;
  /** Persist the chosen folder (null = no folder) across all selected threads. */
  onConfirm: (folder: string | null) => void | Promise<void>;
  loading?: boolean;
}

/**
 * Folder picker for bulk-saving the selected threads. Mirrors the single-thread
 * SaveThreadDialog's folder UX — pick an existing folder, type a new one, or
 * save with no folder — but applies one folder to every selected thread via the
 * bulk endpoint. No per-thread note: a single note across many threads isn't
 * meaningful, so it's omitted here (use single-thread save for notes).
 */
export function BulkSaveDialog({
  open,
  onOpenChange,
  count,
  onConfirm,
  loading,
}: BulkSaveDialogProps) {
  const { folders } = useSavedFolders();
  const [pickedFolder, setPickedFolder] = useState<string>(NO_FOLDER_VALUE);
  const [newFolderName, setNewFolderName] = useState("");

  // Reset to "No folder" each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setPickedFolder(NO_FOLDER_VALUE);
    setNewFolderName("");
  }, [open]);

  const isNewFolder = pickedFolder === NEW_FOLDER_VALUE;
  const folderToSubmit = isNewFolder
    ? newFolderName.trim()
    : pickedFolder === NO_FOLDER_VALUE
    ? null
    : pickedFolder;

  const canSubmit = !loading && (!isNewFolder || newFolderName.trim().length > 0);

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
            Save {count} thread{count === 1 ? "" : "s"}
          </DialogTitle>
          <DialogDescription>
            File the selected thread{count === 1 ? "" : "s"} in a folder so you can find
            them later. Saved threads stay searchable from the Saved tab.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground" htmlFor="bulk-save-folder">
              Folder
            </label>
            <Select
              value={pickedFolder}
              onValueChange={(v: string | null) => v && setPickedFolder(v)}
            >
              <SelectTrigger id="bulk-save-folder" className="w-full">
                <SelectValue placeholder="No folder" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_FOLDER_VALUE}>
                  <span className="text-muted-foreground">No folder (just save)</span>
                </SelectItem>
                {existingFolders.map((folder) => (
                  <SelectItem key={folder.name} value={folder.name}>
                    <span className="truncate">{folder.name}</span>
                    <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                      {folder.count}
                    </span>
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
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(folderToSubmit)} disabled={!canSubmit}>
            {loading ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
