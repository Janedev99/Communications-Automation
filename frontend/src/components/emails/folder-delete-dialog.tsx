"use client";

import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { deleteSavedFolder } from "@/hooks/use-emails";
import type { SavedFolder } from "@/lib/types";

interface FolderDeleteDialogProps {
  folder: SavedFolder;
  /**
   * Names of direct child folders in the tree, if any — cheap to pass in
   * from the caller since `saved/page.tsx` already has the full nested
   * `folderTree` built for the rail. Surfaces a "subfolders will be
   * deleted too" note without this component needing its own fetch.
   */
  childNames?: string[];
  onClose: () => void;
  onDeleted: () => void;
}

/**
 * Dedicated folder-delete confirmation. Mirrors the app's existing
 * `<ConfirmDialog>` primitive (Base UI Dialog under the hood, same as
 * `save-thread-dialog.tsx`) rather than introducing a new dialog shell,
 * so folder deletion reads as part of the same confirm-dialog family as
 * every other destructive action in the app.
 *
 * Delete is idempotent (204) even when the folder still has items filed
 * directly under it — those items simply become unfiled ("No folder")
 * rather than being blocked or cascaded. Any error message returned by the
 * backend is still surfaced verbatim via toast, same pattern as
 * move/create-folder.
 */
export function FolderDeleteDialog({
  folder,
  childNames = [],
  onClose,
  onDeleted,
}: FolderDeleteDialogProps) {
  const [deleting, setDeleting] = useState(false);

  const outlookCount = folder.outlook_item_count ?? 0;
  const hasChildren = childNames.length > 0;

  const handleConfirm = async () => {
    if (!folder.name) return;
    setDeleting(true);
    try {
      await deleteSavedFolder(folder.name);
      toast.success(`Deleted folder "${folder.name}".`);
      onDeleted();
      onClose();
    } catch (err: unknown) {
      // The 409 detail tells the user exactly what to do (move items
      // out first) — pass it through rather than a generic message.
      toast.error(err instanceof Error ? err.message : "Could not delete folder.");
    } finally {
      setDeleting(false);
    }
  };

  const description =
    folder.count > 0
      ? 'This removes the folder from the app. Items filed here stay saved and move to "No folder".'
      : "This folder is empty. It will be removed from your folder list.";

  return (
    <ConfirmDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Delete "${folder.name}"?`}
      description={description}
      details={
        (outlookCount > 0 || hasChildren) && (
          <div className="space-y-1.5 text-sm">
            {outlookCount > 0 && (
              <p className="text-amber-600 dark:text-amber-400">
                If Outlook folder sync is enabled, this also moves {outlookCount} email
                {outlookCount === 1 ? "" : "s"} in Outlook to Deleted Items (recoverable).
              </p>
            )}
            {hasChildren && (
              <p className="text-muted-foreground">Subfolders will be deleted too.</p>
            )}
          </div>
        )
      }
      confirmLabel="Delete folder"
      confirmVariant="destructive"
      onConfirm={handleConfirm}
      loading={deleting}
    />
  );
}
