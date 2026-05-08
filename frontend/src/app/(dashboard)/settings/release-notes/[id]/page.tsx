"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowLeft,
  Wand2,
  AlertCircle,
  CheckCircle2,
  Save,
  Eye,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Lock,
} from "lucide-react";
import Link from "next/link";
import { api, swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ReleaseNoteCard } from "@/components/whats-new/release-note-card";
import { useUser } from "@/hooks/use-user";
import { cn, relativeTime } from "@/lib/utils";
import type {
  ReleaseAdminResponse,
  DraftSuggestionResponse,
  Highlight,
  HighlightCategory,
} from "@/lib/types";

const LIST_KEY = "/api/v1/admin/releases";
const MAX_HIGHLIGHTS = 20;
const MAX_HIGHLIGHT_TEXT = 140;
const MAX_SUMMARY = 400;

const CATEGORY_OPTIONS: { value: HighlightCategory; label: string }[] = [
  { value: "new", label: "NEW" },
  { value: "improved", label: "IMPROVED" },
  { value: "fixed", label: "FIXED" },
];

export default function ReleaseNoteEditPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { isAdmin, isLoading: userLoading } = useUser();

  const {
    data: list,
    isLoading: listLoading,
    mutate,
  } = useSWR<ReleaseAdminResponse[]>(isAdmin ? LIST_KEY : null, swrFetcher);

  const release = list?.find((r) => r.id === params.id);

  // Local form state
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  // Legacy body — preserved for already-published releases that pre-date
  // the structured shape. Editable so admins can clear / migrate.
  const [body, setBody] = useState<string>("");
  const [showLegacyBody, setShowLegacyBody] = useState(false);

  // Seed once the release loads
  useEffect(() => {
    if (release) {
      setTitle(release.title);
      setSummary(release.summary ?? "");
      setHighlights(release.highlights ?? []);
      setBody(release.body ?? "");
      setShowLegacyBody(!!release.body && release.body.trim().length > 0);
    }
  }, [release?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [showPublishConfirm, setShowPublishConfirm] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const isPublished = release?.status === "published";

  // Strict publish gate matches backend: title + summary + ≥1 highlight.
  const canPublish =
    !isPublished &&
    title.trim().length > 0 &&
    summary.trim().length > 0 &&
    highlights.length > 0 &&
    highlights.every((h) => h.text.trim().length > 0);

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

  // ── Highlight row helpers ──────────────────────────────────────────────
  const addHighlight = () => {
    if (highlights.length >= MAX_HIGHLIGHTS) return;
    setHighlights((prev) => [...prev, { category: "improved", text: "" }]);
  };

  const removeHighlight = (idx: number) => {
    setHighlights((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateHighlight = (idx: number, patch: Partial<Highlight>) => {
    setHighlights((prev) =>
      prev.map((h, i) => (i === idx ? { ...h, ...patch } : h)),
    );
  };

  // ── Mutations ───────────────────────────────────────────────────────────
  const buildPayload = () => ({
    title,
    summary: summary || null,
    // Backend coerces empty text to validation failure; we strip here too
    // so saving never persists junk rows.
    highlights: highlights
      .filter((h) => h.text.trim().length > 0)
      .map((h) => ({ category: h.category, text: h.text.trim() })),
    body: body || null,
  });

  const handleSave = async () => {
    if (!release) return;
    setSaving(true);
    try {
      await api.patch(`${LIST_KEY}/${release.id}`, buildPayload());
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
      // Save first so the publish gate sees the latest local edits.
      await api.patch(`${LIST_KEY}/${release.id}`, buildPayload());
      await api.post(`${LIST_KEY}/${release.id}/publish`);
      await mutate();
      toast.success("Release published! Staff will see the What's New modal on next load.");
      router.push("/settings/release-notes");
    } catch (err: unknown) {
      const message = (err as Error)?.message ?? "";
      if (message === "release_summary_required") {
        toast.error("Add a summary before publishing.");
      } else if (message === "release_highlights_required") {
        toast.error("Add at least one highlight before publishing.");
      } else if (message === "release_title_required") {
        toast.error("Add a title before publishing.");
      } else {
        toast.error(`Failed to publish: ${message || "unknown error"}.`);
      }
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
        {},
      );

      if (suggestion.commit_count === 0) {
        toast.info("No user-facing commits since the last release.");
        return;
      }

      // Local state first — replaces title/summary/highlights atomically
      // even before the PATCH lands.
      setTitle(suggestion.title_suggestion);
      setSummary(suggestion.summary_suggestion);
      setHighlights(suggestion.highlights_suggestion);

      await api.patch(`${LIST_KEY}/${release.id}`, {
        title: suggestion.title_suggestion,
        summary: suggestion.summary_suggestion || null,
        highlights: suggestion.highlights_suggestion,
      });
      await mutate();

      if (suggestion.low_confidence) {
        toast.warning(
          "AI returned an unstructured response. Please review and add highlights manually.",
        );
      } else {
        toast.success("Draft regenerated from commits.");
      }
    } catch (err: unknown) {
      const message = (err as Error)?.message ?? "";
      if (message === "release_meta_unavailable") {
        toast.error(
          "Build-time commit metadata is missing. Restart the backend to regenerate it.",
        );
      } else if (message === "ai_unavailable") {
        toast.error("AI is not configured. Set up Groq or another LLM provider.");
      } else {
        toast.error(`Failed to regenerate: ${message || "unknown error"}.`);
      }
    } finally {
      setRegenerating(false);
    }
  };

  const summaryLen = summary.length;
  const summaryOver = summaryLen > MAX_SUMMARY;

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
                title={
                  canPublish
                    ? "Publish this release"
                    : "Publish requires title + summary + at least one highlight"
                }
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
              maxLength={120}
              className={cn(isPublished && "opacity-60 cursor-not-allowed")}
            />
          </div>

          <div>
            <label
              htmlFor="release-summary"
              className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5"
            >
              Summary
            </label>
            <Textarea
              id="release-summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              disabled={isPublished}
              placeholder="1-2 sentences describing what staff will notice this release."
              rows={3}
              className={cn(
                "text-sm resize-none",
                isPublished && "opacity-60 cursor-not-allowed",
              )}
            />
            <p
              className={cn(
                "text-xs mt-1 tabular-nums",
                summaryOver ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {summaryLen} / {MAX_SUMMARY}
            </p>
          </div>

          {/* Highlights list */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Highlights{" "}
                <span className="text-muted-foreground/70 normal-case font-normal">
                  ({highlights.length}/{MAX_HIGHLIGHTS})
                </span>
              </label>
              {!isPublished && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addHighlight}
                  disabled={highlights.length >= MAX_HIGHLIGHTS}
                >
                  <Plus className="w-3.5 h-3.5 mr-1" />
                  Add
                </Button>
              )}
            </div>

            {highlights.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border p-4 text-center">
                <p className="text-sm text-muted-foreground">
                  No highlights yet.
                </p>
                {!isPublished && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Add at least one before publishing — it&apos;s what staff see as a chip.
                  </p>
                )}
              </div>
            ) : (
              <ul className="space-y-2">
                {highlights.map((h, i) => {
                  const overLimit = h.text.length > MAX_HIGHLIGHT_TEXT;
                  return (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-lg border border-border bg-card p-2"
                    >
                      <select
                        value={h.category}
                        onChange={(e) =>
                          updateHighlight(i, {
                            category: e.target.value as HighlightCategory,
                          })
                        }
                        disabled={isPublished}
                        className={cn(
                          "h-9 rounded-md border border-input bg-background px-2 text-xs font-semibold uppercase tracking-wider shrink-0",
                          "focus:outline-none focus:ring-2 focus:ring-ring",
                          isPublished && "opacity-60 cursor-not-allowed",
                        )}
                        aria-label="Highlight category"
                      >
                        {CATEGORY_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                      <div className="flex-1 min-w-0">
                        <Input
                          value={h.text}
                          onChange={(e) =>
                            updateHighlight(i, { text: e.target.value })
                          }
                          disabled={isPublished}
                          placeholder="Lead with a verb — adds, speeds up, fixes…"
                          maxLength={MAX_HIGHLIGHT_TEXT + 20}
                          className={cn(
                            "h-9 text-sm",
                            overLimit && "border-destructive",
                          )}
                        />
                        {h.text.length > 100 && (
                          <p
                            className={cn(
                              "text-[10px] mt-0.5 tabular-nums",
                              overLimit
                                ? "text-destructive"
                                : "text-muted-foreground",
                            )}
                          >
                            {h.text.length} / {MAX_HIGHLIGHT_TEXT}
                          </p>
                        )}
                      </div>
                      {!isPublished && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeHighlight(i)}
                          className="h-9 w-9 p-0 text-muted-foreground hover:text-destructive shrink-0"
                          aria-label="Remove highlight"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Legacy body — collapsed by default unless content present */}
          {(body || showLegacyBody) && (
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <button
                type="button"
                onClick={() => setShowLegacyBody((v) => !v)}
                className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground"
              >
                {showLegacyBody ? (
                  <ChevronDown className="w-3.5 h-3.5" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5" />
                )}
                Legacy markdown body{" "}
                {body && (
                  <span className="text-muted-foreground/70 normal-case font-normal">
                    ({body.length} chars)
                  </span>
                )}
              </button>
              {showLegacyBody && (
                <>
                  <Textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    disabled={isPublished}
                    placeholder="Legacy markdown body — only rendered when no highlights are set. Migrate content into highlights above."
                    rows={6}
                    className={cn(
                      "font-mono text-xs resize-none mt-2",
                      isPublished && "opacity-60 cursor-not-allowed",
                    )}
                  />
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Legacy body is shown as a fallback only when there are no
                    highlights. Publishing requires highlights — once you add
                    them, the body is hidden from staff.
                  </p>
                </>
              )}
            </div>
          )}

          {release && (
            <p className="text-xs text-muted-foreground">
              Created by {release.created_by.name} · Last updated{" "}
              {relativeTime(release.updated_at)}
            </p>
          )}
        </div>

        {/* Right: live preview */}
        <div>
          <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
            <Eye className="w-3.5 h-3.5" />
            Preview
          </div>
          <div className="sticky top-4">
            <ReleaseNoteCard
              title={title}
              summary={summary}
              highlights={highlights.filter(
                (h) => h.text.trim().length > 0,
              )}
              body={body}
              publishedAt={release?.published_at ?? new Date().toISOString()}
            />
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
