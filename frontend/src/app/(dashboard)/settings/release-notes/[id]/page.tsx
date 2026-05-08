"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import { toast } from "sonner";
import {
  ArrowLeft,
  Wand2,
  AlertCircle,
  CheckCircle2,
  Save,
  Eye,
} from "lucide-react";
import Link from "next/link";
import { api, swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { useUser } from "@/hooks/use-user";
import { cn, relativeTime } from "@/lib/utils";
import { Lock } from "lucide-react";
import type { ReleaseAdminResponse, DraftSuggestionResponse } from "@/lib/types";

const LIST_KEY = "/api/v1/admin/releases";

export default function ReleaseNoteEditPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { isAdmin, isLoading: userLoading } = useUser();

  // Fetch list and find by id — no single-item endpoint exists.
  const {
    data: list,
    isLoading: listLoading,
    mutate,
  } = useSWR<ReleaseAdminResponse[]>(isAdmin ? LIST_KEY : null, swrFetcher);

  const release = list?.find((r) => r.id === params.id);

  // Local form state
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  // Seed once the release loads
  useEffect(() => {
    if (release) {
      setTitle(release.title);
      setBody(release.body);
    }
  }, [release?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [showPublishConfirm, setShowPublishConfirm] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const isPublished = release?.status === "published";
  const canPublish = !isPublished && title.trim().length > 0 && body.trim().length > 0;

  if (userLoading || listLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground animate-pulse">Loading…</div>
    );
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

  if (!listLoading && !release) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Release not found.{" "}
        <Link href="/settings/release-notes" className="underline hover:text-foreground">
          Back to list
        </Link>
      </div>
    );
  }

  const handleSave = async () => {
    if (!release) return;
    setSaving(true);
    try {
      await api.patch(`${LIST_KEY}/${release.id}`, { title, body });
      await mutate();
      toast.success("Draft saved.");
    } catch {
      toast.error("Failed to save. Published releases cannot be edited.");
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async () => {
    if (!release) return;
    setPublishing(true);
    try {
      await api.post(`${LIST_KEY}/${release.id}/publish`);
      await mutate();
      toast.success("Release published! Staff will see the What's New modal on next load.");
      router.push("/settings/release-notes");
    } catch {
      toast.error("Failed to publish. It may already be published.");
    } finally {
      setPublishing(false);
      setShowPublishConfirm(false);
    }
  };

  const handleRegenerate = async () => {
    if (!release) return;
    setRegenerating(true);
    try {
      const suggestion = await api.post<DraftSuggestionResponse>(
        `${LIST_KEY}/draft-from-commits`,
        { source: "github_api" },
      );

      if (suggestion.commit_count === 0) {
        toast.info("No user-facing commits since the last release.");
        return;
      }

      await api.patch(`${LIST_KEY}/${release.id}`, {
        title: suggestion.title_suggestion,
        body: suggestion.body_suggestion,
      });
      setTitle(suggestion.title_suggestion);
      setBody(suggestion.body_suggestion);
      await mutate();
      toast.success("Draft regenerated from commits.");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail ?? "";
      if (detail === "github_not_configured") {
        toast.error("GitHub auto-fetch isn't configured.");
      } else if (detail === "ai_unavailable") {
        toast.error("AI is not configured. Set up Groq or another LLM provider.");
      } else {
        toast.error("Failed to regenerate. Try again later.");
      }
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Top nav */}
      <div className="flex items-center justify-between gap-4">
        <Link
          href="/settings/release-notes"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Release Notes
        </Link>

        <div className="flex items-center gap-2">
          {release && (
            <Badge variant={isPublished ? "default" : "secondary"}>
              {isPublished ? "PUBLISHED" : "DRAFT"}
            </Badge>
          )}

          {!isPublished && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRegenerate}
                disabled={regenerating || saving}
              >
                <Wand2 className="w-3.5 h-3.5 mr-1.5" />
                {regenerating ? "Regenerating…" : "Regenerate with AI"}
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={handleSave}
                disabled={saving || regenerating}
              >
                <Save className="w-3.5 h-3.5 mr-1.5" />
                {saving ? "Saving…" : "Save draft"}
              </Button>

              <Button
                size="sm"
                onClick={() => setShowPublishConfirm(true)}
                disabled={!canPublish || saving || regenerating}
              >
                <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
                Publish
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Published read-only banner */}
      {isPublished && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
          <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium text-amber-700 dark:text-amber-300">
              This release is published.
            </p>
            <p className="text-amber-600 dark:text-amber-400 mt-0.5">
              Edits are not allowed. To issue a correction, create a new draft release.
              {release?.published_at && (
                <span className="ml-1">
                  Published {relativeTime(release.published_at)}.
                </span>
              )}
            </p>
          </div>
        </div>
      )}

      {/* Two-column editor / preview */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: form */}
        <div className="space-y-4">
          <div>
            <label
              htmlFor="release-title"
              className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5"
            >
              Title
            </label>
            <Input
              id="release-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={isPublished}
              placeholder="e.g. What's New in May 2025"
              className={cn(isPublished && "opacity-60 cursor-not-allowed")}
            />
          </div>

          <div>
            <label
              htmlFor="release-body"
              className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5"
            >
              Body (Markdown)
            </label>
            <Textarea
              id="release-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              disabled={isPublished}
              placeholder="Write release notes in Markdown. Use ## headings, **bold**, and bullet lists."
              rows={18}
              className={cn(
                "font-mono text-sm resize-none",
                isPublished && "opacity-60 cursor-not-allowed",
              )}
            />
          </div>

          {release && (
            <p className="text-xs text-muted-foreground">
              Created by {release.created_by.name} · Last updated {relativeTime(release.updated_at)}
            </p>
          )}
        </div>

        {/* Right: live preview */}
        <div>
          <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
            <Eye className="w-3.5 h-3.5" />
            Preview
          </div>
          <div className="bg-card border border-border rounded-xl p-5 min-h-[300px]">
            {title ? (
              <h2 className="text-lg font-bold text-foreground mb-3">{title}</h2>
            ) : (
              <p className="text-sm text-muted-foreground italic mb-3">Title will appear here…</p>
            )}
            {body ? (
              <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed">
                <ReactMarkdown>{body}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic">
                Body preview will appear here as you type…
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Publish confirm dialog */}
      <ConfirmDialog
        open={showPublishConfirm}
        onOpenChange={setShowPublishConfirm}
        title="Publish this release?"
        description="This will show the What's New modal to all staff on their next dashboard load. Continue?"
        confirmLabel="Publish"
        confirmVariant="default"
        onConfirm={handlePublish}
        loading={publishing}
      />
    </div>
  );
}
