"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { api, swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { formatDate } from "@/lib/utils";
import type { TodoResetState } from "@/lib/types";

const RESET_ENDPOINT = "/api/v1/system-settings/todo-reset";

/** Every cached view whose contents depend on the to-do cutoff. */
function dependsOnCutoff(key: unknown): boolean {
  return (
    typeof key === "string" &&
    (key.startsWith("/api/v1/dashboard/stats") ||
      key.startsWith("/api/v1/emails") ||
      key.startsWith("/api/v1/escalations"))
  );
}

/**
 * Admin control for "Start clean": hides everything with no activity since now
 * from the To-do lanes (For review / Escalated), the sidebar escalation dot,
 * and the dashboard counts. Nothing is deleted or changed — the threads stay
 * in All and search — and Undo restores the previous view.
 */
export function TodoResetCard() {
  const { data, error, mutate } = useSWR<TodoResetState>(RESET_ENDPOINT, swrFetcher);
  const { mutate: mutateGlobal } = useSWRConfig();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const refreshViews = async (next: TodoResetState) => {
    await mutate(next, { revalidate: false });
    await mutateGlobal(dependsOnCutoff);
  };

  const handleApply = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const next = await api.post<TodoResetState>(RESET_ENDPOINT);
      await refreshViews(next);
      setConfirmOpen(false);
      toast.success("To-do list cleared. Nothing was deleted — older items are still in All.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not start clean.");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const next = await api.delete<TodoResetState>(RESET_ENDPOINT);
      await refreshViews(next);
      toast.success("Reset undone. Your previous to-do list is back.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not undo the reset.");
      await mutate();
    } finally {
      setBusy(false);
    }
  };

  const wouldHide = data?.would_hide;

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="block text-sm font-medium text-foreground">Start clean</p>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            Clears the To-do lanes (For review and Escalated), the escalation
            count, and the dashboard counts so you only see what comes in from
            now on. Nothing is deleted or changed — every thread stays in{" "}
            <span className="font-medium">All</span> and in search.
          </p>
          <p className="text-xs text-muted-foreground mt-2" aria-live="polite">
            {error
              ? "Could not load the current state."
              : !data
              ? "Loading…"
              : data.cutoff_at
              ? `Showing activity since ${formatDate(data.cutoff_at)}${
                  data.set_by_name ? ` (set by ${data.set_by_name})` : ""
                }.`
              : "No reset active — the To-do lanes show everything."}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {data?.can_undo && (
            <Button variant="outline" onClick={handleUndo} disabled={busy}>
              Undo
            </Button>
          )}
          <Button onClick={() => setConfirmOpen(true)} disabled={busy || !data}>
            Start clean
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Start clean?"
        description={
          "This hides your current To-do items so you can start fresh. " +
          "Nothing is deleted — every thread stays in All and in search, and " +
          "any thread that gets a new client message comes back on its own. " +
          "You can Undo this from Settings at any time."
        }
        details={
          wouldHide ? (
            <p className="text-sm text-foreground">
              This will clear{" "}
              <span className="font-semibold tabular-nums">{wouldHide.escalations}</span>{" "}
              open {wouldHide.escalations === 1 ? "escalation" : "escalations"} and{" "}
              <span className="font-semibold tabular-nums">{wouldHide.reviews}</span>{" "}
              {wouldHide.reviews === 1 ? "thread" : "threads"} waiting for review.
            </p>
          ) : null
        }
        confirmLabel="Start clean"
        confirmVariant="default"
        onConfirm={handleApply}
        loading={busy}
      />
    </div>
  );
}
