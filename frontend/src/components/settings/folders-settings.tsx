"use client";

import { useState } from "react";
import { Download, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";
import { mutate as globalMutate } from "swr";
import { Button } from "@/components/ui/button";
import { importOutlookFolders, syncFoldersToOutlook } from "@/hooks/use-emails";

const SAVED_FOLDERS_KEY = "/api/v1/emails/saved/folders";

/**
 * Admin controls for the shared folder registry ↔ Outlook. Both actions are
 * additive/read-through only — Import pulls Outlook's custom folders into the
 * app's registry, Sync creates the app's folders in Outlook. Neither ever
 * deletes anything on either side (see spec invariants).
 */
export function FoldersSettings() {
  const [importing, setImporting] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const handleImport = async () => {
    if (importing) return;
    setImporting(true);
    try {
      const r = await importOutlookFolders();
      await globalMutate(SAVED_FOLDERS_KEY);
      toast.success(
        `Imported ${r.imported} folder${r.imported === 1 ? "" : "s"} from Outlook.`,
        { description: `${r.updated} updated, ${r.total} total.` }
      );
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not import folders from Outlook.");
    } finally {
      setImporting(false);
    }
  };

  const handleSync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const r = await syncFoldersToOutlook();
      await globalMutate(SAVED_FOLDERS_KEY);
      toast.success("Synced folders to Outlook.", {
        description: `${r.created} created, ${r.existing} already there.`,
      });
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not sync folders to Outlook.");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-3">
      <div>
        <h3 className="text-sm font-medium text-foreground">Outlook folders</h3>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          Keep the app&apos;s folder registry and your Outlook mailbox&apos;s custom
          folders in sync.
        </p>
      </div>
      <div className="flex flex-col sm:flex-row gap-2.5">
        <Button variant="outline" onClick={handleImport} disabled={importing || syncing}>
          {importing ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Download className="w-4 h-4 mr-2" />
          )}
          Import from Outlook
        </Button>
        <Button variant="outline" onClick={handleSync} disabled={importing || syncing}>
          {syncing ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Upload className="w-4 h-4 mr-2" />
          )}
          Sync to Outlook
        </Button>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        Import pulls your Outlook folders into the app. Sync creates your app
        folders in Outlook. Neither ever deletes anything in Outlook.
      </p>
    </div>
  );
}
