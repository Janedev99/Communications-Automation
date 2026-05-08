"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { Plus, Wand2, ArrowLeft, Trash2, ArrowRight, FileText } from "lucide-react";
import { api, swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { useUser } from "@/hooks/use-user";
import { useRouter } from "next/navigation";
import { relativeTime } from "@/lib/utils";
import { Lock } from "lucide-react";
import type { ReleaseAdminResponse, DraftSuggestionResponse } from "@/lib/types";

const PASTE_MAX_CHARS = 50_000;

const KEY = "/api/v1/admin/releases";

export default function ReleaseNotesListPage() {
  const router = useRouter();
  const { isAdmin, isLoading: userLoading } = useUser();
  const { data, error, isLoading, mutate } = useSWR<ReleaseAdminResponse[]>(
    isAdmin ? KEY : null,
    swrFetcher,
  );

  const [generating, setGenerating] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ReleaseAdminResponse | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");

  if (userLoading) {
    return null;
  }

  if (!isAdmin) {
    return (
      <div className="bg-card border border-border rounded-lg p-8 text-center">
        <Lock className="w-10 h-10 text-muted-foreground mx-auto" strokeWidth={1.5} />
        <h2 className="text-lg font-semibold text-foreground mt-3">Admin access required</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Only admins can manage release notes.
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState
        title="Failed to load releases"
        description="Could not retrieve release notes."
        onRetry={mutate}
      />
    );
  }

  const releases = data ?? [];
  const drafts = releases.filter((r) => r.status === "draft");
  const published = releases.filter((r) => r.status === "published");

  /** Step 2 of the generate flow: take a successful suggestion, create a
   *  draft from it, and navigate to the editor. Shared between the
   *  github_api and manual_paste paths. */
  const createDraftFromSuggestion = async (suggestion: DraftSuggestionResponse) => {
    if (suggestion.commit_count === 0) {
      toast.info("No user-facing commits found in the input.");
      return;
    }
    const created = await api.post<ReleaseAdminResponse>(KEY, {
      title: suggestion.title_suggestion,
      summary: suggestion.summary_suggestion || null,
      highlights: suggestion.highlights_suggestion,
      generated_from: suggestion.generated_from,
      commit_sha_at_release: suggestion.commit_sha_at_release,
    });
    await mutate();
    if (suggestion.low_confidence) {
      toast.warning(
        "Draft created, but the AI response was unstructured. Review and add highlights manually.",
      );
    } else {
      toast.success("Draft created from commits.");
    }
    router.push(`/settings/release-notes/${created.id}`);
  };

  const handleGenerateFromCommits = async () => {
    setGenerating(true);
    try {
      try {
        const suggestion = await api.post<DraftSuggestionResponse>(
          "/api/v1/admin/releases/draft-from-commits",
          { source: "github_api" },
        );
        await createDraftFromSuggestion(suggestion);
      } catch (err: unknown) {
        // api.ts throws ApiError(status, message) where `message` is the
        // backend's response.detail field.
        const message = (err as Error)?.message ?? "";
        if (message === "github_not_configured") {
          // Open the manual-paste fallback dialog instead of failing hard.
          setPasteOpen(true);
          return;
        }
        if (message === "ai_unavailable") {
          toast.error("AI is not configured. Set up Groq or another LLM provider.");
          return;
        }
        toast.error(`Failed to generate from commits: ${message || "unknown error"}.`);
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleManualPasteGenerate = async () => {
    const lines = pasteText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (lines.length === 0) {
      toast.error("Paste at least one commit message.");
      return;
    }
    setGenerating(true);
    try {
      const suggestion = await api.post<DraftSuggestionResponse>(
        "/api/v1/admin/releases/draft-from-commits",
        { source: "manual_paste", commits: lines },
      );
      setPasteOpen(false);
      setPasteText("");
      await createDraftFromSuggestion(suggestion);
    } catch (err: unknown) {
      const message = (err as Error)?.message ?? "";
      if (message === "ai_unavailable") {
        toast.error("AI is not configured. Set up Groq or another LLM provider.");
      } else {
        toast.error(`Failed to generate: ${message || "unknown error"}.`);
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleNewDraft = async () => {
    setCreatingDraft(true);
    try {
      // Backend requires at least one of body / summary / highlights to be
      // non-empty on create. Seed summary so the editor opens with a valid
      // draft; admin replaces it before adding highlights and publishing.
      const created = await api.post<ReleaseAdminResponse>(KEY, {
        title: "Untitled release",
        summary: "Replace this with a short summary of what staff will notice.",
        highlights: [],
        generated_from: "manual_only",
      });
      await mutate();
      router.push(`/settings/release-notes/${created.id}`);
    } catch (err: unknown) {
      const message = (err as Error)?.message ?? "unknown error";
      toast.error(`Failed to create draft: ${message}.`);
    } finally {
      setCreatingDraft(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`${KEY}/${deleteTarget.id}`);
      await mutate();
      toast.success("Draft deleted.");
      setDeleteTarget(null);
    } catch {
      toast.error("Failed to delete. Published releases cannot be deleted.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Link
        href="/settings"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to settings
      </Link>

      <PageHeader
        title="Release Notes"
        subtitle="Manage What's New announcements shown to staff on login."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={handleGenerateFromCommits}
              disabled={generating || creatingDraft}
            >
              <Wand2 className="w-4 h-4 mr-1.5" aria-hidden="true" />
              {generating ? "Generating…" : "Generate from commits"}
            </Button>
            <Button onClick={handleNewDraft} disabled={creatingDraft || generating}>
              <Plus className="w-4 h-4 mr-1.5" aria-hidden="true" />
              {creatingDraft ? "Creating…" : "New draft"}
            </Button>
          </div>
        }
      />

      {/* Drafts section */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Drafts
          </h2>
          <span className="text-xs text-muted-foreground tabular-nums">
            ({drafts.length})
          </span>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="h-16 bg-muted animate-pulse rounded-lg"
              />
            ))}
          </div>
        ) : drafts.length === 0 ? (
          <div className="bg-card border border-border rounded-lg p-6 text-center">
            <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-2" strokeWidth={1.5} />
            <p className="text-sm text-muted-foreground">No drafts yet.</p>
            <p className="text-xs text-muted-foreground mt-1">
              Create a new draft or generate one from recent commits.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {drafts.map((release) => (
              <div
                key={release.id}
                className="flex items-center justify-between gap-3 bg-card border border-border rounded-lg px-4 py-3 hover:border-foreground/15 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Badge variant="secondary">DRAFT</Badge>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">
                      {release.title}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Created {relativeTime(release.created_at)} by {release.created_by.name}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleteTarget(release)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                    <span className="sr-only">Delete draft</span>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(`/settings/release-notes/${release.id}`)}
                  >
                    Open
                    <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Published section */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Published
          </h2>
          <span className="text-xs text-muted-foreground tabular-nums">
            ({published.length})
          </span>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="h-16 bg-muted animate-pulse rounded-lg"
              />
            ))}
          </div>
        ) : published.length === 0 ? (
          <p className="text-sm text-muted-foreground">No published releases yet.</p>
        ) : (
          <div className="space-y-2">
            {published.map((release) => (
              <div
                key={release.id}
                className="flex items-center justify-between gap-3 bg-card border border-border rounded-lg px-4 py-3 hover:border-foreground/15 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Badge variant="default" className="bg-brand-500 text-white border-transparent">
                    LIVE
                  </Badge>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">
                      {release.title}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Published {release.published_at ? relativeTime(release.published_at) : "—"}
                    </p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => router.push(`/settings/release-notes/${release.id}`)}
                >
                  View
                  <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Delete draft?"
        description={`Delete "${deleteTarget?.title ?? "this draft"}"? This cannot be undone.`}
        confirmLabel="Delete"
        confirmVariant="destructive"
        onConfirm={handleDeleteConfirm}
        loading={deleting}
      />

      {/* Manual-paste fallback dialog (shown when GitHub auto-fetch isn't configured) */}
      <Dialog open={pasteOpen} onOpenChange={setPasteOpen}>
        <DialogContent className="sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle>Paste recent commits</DialogTitle>
            <DialogDescription>
              GitHub auto-fetch isn&apos;t configured. Paste commit subjects from
              {" "}
              <code className="text-[11px] bg-muted px-1 rounded">git log --oneline</code>
              {" "}
              (one per line). Only <code className="text-[11px] bg-muted px-1 rounded">feat:</code>{" "}
              and <code className="text-[11px] bg-muted px-1 rounded">fix:</code> commits will be
              summarised by the AI.
            </DialogDescription>
          </DialogHeader>

          <Textarea
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value.slice(0, PASTE_MAX_CHARS))}
            placeholder={`feat: smarter draft suggestions\nfix: don't drop attachments on resend\nchore: bump deps`}
            rows={10}
            className="font-mono text-xs"
          />
          <p className="text-xs text-muted-foreground -mt-1">
            {pasteText.length.toLocaleString()} / {PASTE_MAX_CHARS.toLocaleString()} chars
          </p>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setPasteOpen(false);
                setPasteText("");
              }}
              disabled={generating}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleManualPasteGenerate()}
              disabled={generating || pasteText.trim().length === 0}
            >
              {generating ? "Generating…" : "Generate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
