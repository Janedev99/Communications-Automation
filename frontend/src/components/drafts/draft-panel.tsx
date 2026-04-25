"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Check,
  X,
  Send,
  FileEdit,
  Loader2,
  Lock,
  LayoutTemplate,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RejectionDialog } from "./rejection-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { TemplatePickerDialog } from "./template-picker-dialog";
import { DRAFT_STATUS_BADGE_CLASSES, DRAFT_STATUS_LABELS } from "@/lib/constants";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { cn, formatDate, relativeTime } from "@/lib/utils";
import { ConfidenceMeter } from "@/components/ui/confidence-meter";
import { SourcePill } from "@/components/ui/source-pill";
import type { DraftResponse, EmailThread, KnowledgeEntry } from "@/lib/types";

interface DraftPanelProps {
  thread: EmailThread;
  draft: DraftResponse | undefined;
  onDraftChange: () => void;
}

type AutoSaveState = "saved" | "saving" | "unsaved" | "idle";

/**
 * State machine for the send flow:
 *  idle → pending_send (10s countdown)
 *       → sending (network request in flight)
 *       → sent | error | cancelled (terminal or recoverable)
 */
type SendState =
  | { phase: "idle" }
  | { phase: "pending_send"; countdown: number }
  | { phase: "sending" }
  | { phase: "sent"; sentAt: string }
  | { phase: "error"; message: string }
  | { phase: "cancelled" };

const TONE_OPTIONS = [
  { value: "professional", label: "Professional" },
  { value: "empathetic", label: "Empathetic" },
  { value: "urgent", label: "Urgent" },
  { value: "direct", label: "Direct" },
];

const UNDO_COUNTDOWN_SECONDS = 10;

export function DraftPanel({ thread, draft, onDraftChange }: DraftPanelProps) {
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [creatingFromTemplate, setCreatingFromTemplate] = useState(false);
  const [showRejectionDialog, setShowRejectionDialog] = useState(false);
  // Regenerate confirm dialog (Item 3)
  const [showRegenerateConfirm, setShowRegenerateConfirm] = useState(false);
  const [showSendConfirm, setShowSendConfirm] = useState(false);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [editedText, setEditedText] = useState(draft?.body_text ?? "");
  const [showOriginal, setShowOriginal] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle");
  // Tone selector — defaults to thread's suggested tone
  const [selectedTone, setSelectedTone] = useState<string>(
    thread.suggested_reply_tone ?? "professional"
  );

  // Send state machine (Item 2)
  const [sendState, setSendState] = useState<SendState>({ phase: "idle" });
  const sendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Ref to stable idempotency key per send attempt
  const sendIdempotencyKeyRef = useRef<string>("");

  // Clean up timers on unmount
  useEffect(() => {
    return () => {
      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
      if (sendTimerRef.current) clearTimeout(sendTimerRef.current);
      if (sendIntervalRef.current) clearInterval(sendIntervalRef.current);
    };
  }, []);

  // Sync editedText when draft changes
  useEffect(() => {
    setEditedText(draft?.body_text ?? "");
    setAutoSaveState("idle");
    setSendState({ phase: "idle" });
  }, [draft?.id, draft?.body_text]);

  // Sync tone from thread whenever thread updates
  useEffect(() => {
    setSelectedTone(thread.suggested_reply_tone ?? "professional");
  }, [thread.suggested_reply_tone]);

  // Focus Cancel button when pending_send banner appears (a11y)
  const cancelSendBtnRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (sendState.phase === "pending_send") {
      cancelSendBtnRef.current?.focus();
    }
  }, [sendState.phase]);

  // Escape key triggers Cancel during countdown (a11y)
  useEffect(() => {
    if (sendState.phase !== "pending_send") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelSend();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
    // cancelSend is stable — declared below with useCallback
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sendState.phase]);

  const handleTextChange = useCallback(
    (value: string) => {
      setEditedText(value);
      setAutoSaveState("unsaved");

      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
      autoSaveTimer.current = setTimeout(async () => {
        if (!draft) return;
        setAutoSaveState("saving");
        try {
          await api.put(`/api/v1/emails/${thread.id}/drafts/${draft.id}`, { body_text: value });
          setAutoSaveState("saved");
          onDraftChange();
        } catch {
          setAutoSaveState("unsaved");
          toast.error("Failed to auto-save draft.");
        }
      }, 1000);
    },
    [draft, thread.id, onDraftChange]
  );

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.post(`/api/v1/emails/${thread.id}/generate-draft`, {
        tone: selectedTone,
      });
      onDraftChange();
      toast.success("Draft generated successfully.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to generate draft.");
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async () => {
    if (!draft) return;
    setApproving(true);
    try {
      await api.post(`/api/v1/emails/${thread.id}/drafts/${draft.id}/approve`);
      onDraftChange();
      toast.success("Draft approved.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to approve draft.");
    } finally {
      setApproving(false);
    }
  };

  const handleReject = async (reason: string) => {
    if (!draft) return;
    setRejecting(true);
    try {
      await api.post(`/api/v1/emails/${thread.id}/drafts/${draft.id}/reject`, {
        rejection_reason: reason,
      });
      setShowRejectionDialog(false);
      onDraftChange();
      toast.success("Draft rejected.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to reject draft.");
    } finally {
      setRejecting(false);
    }
  };

  /**
   * Item 3 — Regenerate with confirm dialog.
   * When a draft exists (pending|edited|approved), shows a confirm dialog.
   * If no draft, proceeds directly.
   */
  const handleRegenerateClick = () => {
    if (draft && draft.status !== "rejected" && draft.status !== "sent") {
      setShowRegenerateConfirm(true);
    } else {
      handleGenerate();
    }
  };

  /**
   * Confirm handler: atomically reject the current draft and generate a new one
   * via the /regenerate endpoint (single request, distinct audit action).
   * Falls back to generate-only when no draft exists yet.
   */
  const handleRegenerateConfirmed = async () => {
    if (!draft) {
      setShowRegenerateConfirm(false);
      await handleGenerate();
      return;
    }
    setShowRegenerateConfirm(false);
    setGenerating(true);
    try {
      // Single atomic endpoint: rejects current draft + generates fresh one.
      // Audit action recorded as draft_regenerated (not draft.rejected + draft.manually_triggered).
      await api.post(`/api/v1/emails/${thread.id}/drafts/${draft.id}/regenerate`, {
        tone: selectedTone,
      });
      onDraftChange();
      toast.success("New draft generated.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to regenerate draft. Please try again.");
      onDraftChange(); // refresh so panel reflects current state
    } finally {
      setGenerating(false);
    }
  };

  // ── Send state machine (Item 2) ────────────────────────────────────────────

  const clearSendTimers = useCallback(() => {
    if (sendTimerRef.current) clearTimeout(sendTimerRef.current);
    if (sendIntervalRef.current) clearInterval(sendIntervalRef.current);
  }, []);

  const cancelSend = useCallback(() => {
    clearSendTimers();
    setSendState({ phase: "cancelled" });
    // Restore to idle briefly so user can send again
    setTimeout(() => setSendState({ phase: "idle" }), 0);
  }, [clearSendTimers]);

  const executeSend = useCallback(async () => {
    if (!draft) return;
    setSendState({ phase: "sending" });
    try {
      await api.post(`/api/v1/emails/${thread.id}/drafts/${draft.id}/send`, {
        idempotency_key: sendIdempotencyKeyRef.current,
      });
      const sentAt = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      setSendState({ phase: "sent", sentAt });
      onDraftChange();
    } catch (err: unknown) {
      // 409 = already sent — treat as success per backend idempotency contract
      if (err instanceof ApiError && err.status === 409) {
        toast.info("Email was already sent.");
        setSendState({ phase: "sent", sentAt: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) });
        onDraftChange();
        return;
      }
      const message = err instanceof Error ? err.message : "Failed to send email.";
      setSendState({ phase: "error", message });
    }
  }, [draft, thread.id, onDraftChange]);

  /** Called when user confirms the Send confirm dialog */
  const handleSendWithCountdown = useCallback(() => {
    setShowSendConfirm(false);
    // Fresh idempotency key per send attempt
    sendIdempotencyKeyRef.current = `${draft?.id ?? "unknown"}-${Date.now()}`;

    let remaining = UNDO_COUNTDOWN_SECONDS;
    setSendState({ phase: "pending_send", countdown: remaining });

    sendIntervalRef.current = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearSendTimers();
        executeSend();
      } else {
        setSendState({ phase: "pending_send", countdown: remaining });
      }
    }, 1000);
  }, [draft?.id, clearSendTimers, executeSend]);

  // ── Template handling ──────────────────────────────────────────────────────

  const handleTemplateSelect = async (template: KnowledgeEntry) => {
    setCreatingFromTemplate(true);
    try {
      await api.post(`/api/v1/emails/${thread.id}/drafts`, {
        body_text: template.content,
      });
      setShowTemplatePicker(false);
      onDraftChange();
      toast.success(`Template "${template.title}" applied.`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to create draft from template.");
    } finally {
      setCreatingFromTemplate(false);
    }
  };

  const autoSaveLabel =
    autoSaveState === "saving"
      ? "Saving..."
      : autoSaveState === "saved"
      ? "Auto-saved"
      : autoSaveState === "unsaved"
      ? "Unsaved changes"
      : "";

  // ── Render panel header ────────────────────────────────────────────────────
  const panelHeader = (
    <div className="px-5 py-4 border-b border-border flex-shrink-0 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-foreground">Draft Response</span>
        {draft && (
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-medium",
                DRAFT_STATUS_BADGE_CLASSES[draft.status]
              )}
            >
              {DRAFT_STATUS_LABELS[draft.status]}
            </span>
            <span className="text-xs text-muted-foreground">v{draft.version}</span>
          </div>
        )}
      </div>
      {/* Phase 3: AI source + confidence — always show, even before a draft exists */}
      <div className="flex items-center gap-3">
        <SourcePill source={thread.categorization_source ?? "claude"} />
        <ConfidenceMeter
          value={thread.category_confidence}
          compact
          className="flex-1 max-w-xs"
        />
      </div>
    </div>
  );

  // ── State A: No draft ──────────────────────────────────────────────────────
  if (!draft) {
    // Item 1: show draft-failed banner when the thread flags a previous failure
    const hasDraftFailure = thread.draft_generation_failed;

    return (
      <div className="bg-card flex flex-col h-full">
        {panelHeader}
        <div className="flex flex-col items-center justify-center flex-1 px-6 text-center gap-4">

          {/* Item 1 — Draft-generation-failed banner */}
          {hasDraftFailure ? (
            <div
              role="alert"
              className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 flex items-start gap-3 w-full text-left"
            >
              <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-amber-900 text-sm">AI draft failed to generate</p>
                <p className="text-xs text-amber-800 mt-0.5">
                  {thread.draft_generation_failed_at
                    ? `Last attempted ${relativeTime(thread.draft_generation_failed_at)}.`
                    : "The last generation attempt failed."}{" "}
                  You can retry or write a response manually.
                </p>
                <div className="flex items-center gap-2 mt-3">
                  <Button
                    size="sm"
                    className="bg-amber-600 hover:bg-amber-700 text-white"
                    onClick={handleGenerate}
                    disabled={generating}
                    aria-label="Retry AI draft generation"
                  >
                    {generating ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      "Retry draft"
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-amber-700 hover:text-amber-900 hover:bg-amber-100"
                    onClick={async () => {
                      // Create an empty manual draft so the editor opens
                      try {
                        await api.post(`/api/v1/emails/${thread.id}/drafts`, { body_text: "" });
                        onDraftChange();
                      } catch (err: unknown) {
                        toast.error(err instanceof Error ? err.message : "Could not create draft.");
                      }
                    }}
                    disabled={generating}
                    aria-label="Write a manual response"
                  >
                    Write manually
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <>
              <FileEdit className="w-10 h-10 text-muted-foreground/60" strokeWidth={1.5} />
              <p className="text-sm text-muted-foreground">
                No draft has been generated for this thread yet.
              </p>
            </>
          )}

          {/* Tone selector */}
          <div className="w-full max-w-[220px]">
            <label className="block text-xs font-medium text-muted-foreground mb-1.5 text-left">
              Tone
            </label>
            <Select value={selectedTone} onValueChange={(v) => v && setSelectedTone(v)}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TONE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value} className="text-xs">
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {!hasDraftFailure && (
            <div className="flex flex-col gap-2 w-full max-w-[220px]">
              <Button
                className="bg-brand-500 hover:bg-brand-600 text-white w-full"
                onClick={handleGenerate}
                disabled={generating || creatingFromTemplate}
              >
                {generating ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Generating...
                  </>
                ) : (
                  "Generate AI Draft"
                )}
              </Button>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => setShowTemplatePicker(true)}
                disabled={generating || creatingFromTemplate}
              >
                {creatingFromTemplate ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Applying...
                  </>
                ) : (
                  <>
                    <LayoutTemplate className="w-4 h-4 mr-2" />
                    Use Template
                  </>
                )}
              </Button>
            </div>
          )}
        </div>

        <TemplatePickerDialog
          open={showTemplatePicker}
          onOpenChange={setShowTemplatePicker}
          onSelect={handleTemplateSelect}
          loading={creatingFromTemplate}
        />
      </div>
    );
  }

  // ── State C: Draft rejected ────────────────────────────────────────────────
  if (draft.status === "rejected") {
    return (
      <div className="bg-card flex flex-col h-full">
        {panelHeader}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-5 mt-4 px-4 py-3 rounded-md bg-red-50 border border-red-200">
            <p className="text-xs font-medium text-red-600 uppercase tracking-wide">Rejected</p>
            <p className="text-sm text-red-700 mt-1">{draft.rejection_reason}</p>
            {draft.reviewed_at && (
              <p className="text-xs text-red-400 mt-2">{formatDate(draft.reviewed_at)}</p>
            )}
          </div>
          <div className="px-5 py-4">
            <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
              {draft.body_text}
            </p>
          </div>
        </div>
        <div className="px-5 py-4 border-t border-border flex-shrink-0 space-y-3">
          {/* Tone selector before regenerate */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">Tone</label>
            <Select value={selectedTone} onValueChange={(v) => v && setSelectedTone(v)}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TONE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value} className="text-xs">
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex gap-2">
            {/* No confirm needed in rejected state — Regenerate proceeds directly */}
            <Button
              className="bg-brand-500 hover:bg-brand-600 text-white flex-1"
              onClick={handleGenerate}
              disabled={generating || creatingFromTemplate}
            >
              {generating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Generating...
                </>
              ) : (
                "Generate New Draft"
              )}
            </Button>
            <Button
              variant="outline"
              onClick={() => setShowTemplatePicker(true)}
              disabled={generating || creatingFromTemplate}
              title="Use a template"
            >
              <LayoutTemplate className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <TemplatePickerDialog
          open={showTemplatePicker}
          onOpenChange={setShowTemplatePicker}
          onSelect={handleTemplateSelect}
          loading={creatingFromTemplate}
        />
      </div>
    );
  }

  // ── State D: Draft sent ────────────────────────────────────────────────────
  if (draft.status === "sent") {
    return (
      <div className="bg-card flex flex-col h-full">
        {panelHeader}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-5 mt-4 px-4 py-3 rounded-md bg-emerald-50 border border-emerald-200">
            <p className="text-sm text-emerald-700 font-medium">Draft sent successfully</p>
            {draft.reviewed_at && (
              <p className="text-xs text-emerald-500 mt-1">
                Sent {formatDate(draft.reviewed_at)}
              </p>
            )}
          </div>
          <div className="px-5 py-4">
            <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
              {draft.body_text}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── State B: Draft pending, edited, or approved (active editing) ───────────
  const displayText = showOriginal
    ? (draft.original_body_text ?? draft.body_text)
    : editedText;

  // Determine if the send-countdown banner is currently active
  const inSendFlow =
    sendState.phase === "pending_send" ||
    sendState.phase === "sending" ||
    sendState.phase === "sent" ||
    sendState.phase === "error";

  return (
    <div className="bg-card flex flex-col h-full">
      {panelHeader}

      {/* Editor */}
      <div className="flex-1 px-5 py-4 overflow-hidden flex flex-col">
        {draft.status === "approved" && (
          <div className="flex items-center gap-1.5 mb-2 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-md px-3 py-1.5">
            <Lock className="w-3.5 h-3.5 flex-shrink-0" />
            <span>Approved — editing locked</span>
          </div>
        )}
        <Textarea
          value={displayText}
          onChange={(e) => !showOriginal && handleTextChange(e.target.value)}
          readOnly={showOriginal || draft.status === "approved"}
          className={cn(
            "flex-1 w-full resize-none border-0 focus-visible:ring-0 focus-visible:ring-offset-0 text-sm text-foreground leading-relaxed p-0 min-h-[200px]",
            draft.status === "approved" && "bg-muted"
          )}
          placeholder="Draft content will appear here..."
        />
        {autoSaveLabel && !showOriginal && (
          <p className="text-[10px] text-muted-foreground mt-1">{autoSaveLabel}</p>
        )}
      </div>

      {/* Version/meta bar */}
      {draft.original_body_text && draft.original_body_text !== draft.body_text && (
        <div className="px-5 py-2 bg-muted border-t border-border/60 flex items-center justify-between flex-shrink-0">
          <span className="text-xs text-muted-foreground">
            Version {draft.version} — Original available
          </span>
          <button
            onClick={() => setShowOriginal((v) => !v)}
            className="text-xs text-brand-500 hover:text-brand-600 cursor-pointer"
          >
            {showOriginal ? "View current" : "View original"}
          </button>
        </div>
      )}

      {/* Tone selector (shown only when draft is pending/edited, not approved) */}
      {draft.status !== "approved" && (
        <div className="px-5 pt-3 pb-1 flex-shrink-0">
          <label className="block text-xs font-medium text-muted-foreground mb-1">Tone override</label>
          <Select value={selectedTone} onValueChange={(v) => v && setSelectedTone(v)}>
            <SelectTrigger className="h-7 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TONE_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value} className="text-xs">
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Action buttons */}
      <div className="px-5 py-4 border-t border-border flex-shrink-0">
        {/* Item 2 — In-panel send countdown / send state banners */}
        {draft.status === "approved" && inSendFlow ? (
          <>
            {sendState.phase === "pending_send" && (
              <div
                aria-live="polite"
                aria-label={`Sending in ${sendState.countdown} seconds`}
                className="flex items-center justify-between gap-3 w-full bg-brand-50 border border-brand-200 rounded-md px-4 py-2.5"
              >
                <div className="flex items-center gap-3">
                  {/* Countdown progress ring (SVG) */}
                  <div className="relative w-8 h-8 flex-shrink-0">
                    <svg className="w-8 h-8 -rotate-90" viewBox="0 0 32 32" aria-hidden="true">
                      <circle
                        cx="16" cy="16" r="12"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        className="text-brand-200"
                      />
                      <circle
                        cx="16" cy="16" r="12"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        className="text-brand-500"
                        strokeDasharray={`${2 * Math.PI * 12}`}
                        strokeDashoffset={`${2 * Math.PI * 12 * (1 - sendState.countdown / UNDO_COUNTDOWN_SECONDS)}`}
                        strokeLinecap="round"
                      />
                    </svg>
                    <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-brand-600">
                      {sendState.countdown}
                    </span>
                  </div>
                  <span className="text-sm font-medium text-foreground">
                    Sending in {sendState.countdown}s…
                  </span>
                </div>
                <Button
                  ref={cancelSendBtnRef}
                  variant="outline"
                  size="sm"
                  onClick={cancelSend}
                  aria-label="Cancel send"
                >
                  Cancel send
                </Button>
              </div>
            )}

            {sendState.phase === "sending" && (
              <div className="flex items-center gap-2 w-full bg-muted border border-border rounded-md px-4 py-2.5">
                <Loader2 className="w-4 h-4 animate-spin text-brand-500" />
                <span className="text-sm text-muted-foreground">Sending…</span>
              </div>
            )}

            {sendState.phase === "sent" && (
              <div className="flex items-center gap-2 w-full bg-emerald-50 border border-emerald-200 rounded-md px-4 py-2.5">
                <CheckCircle className="w-4 h-4 text-emerald-600" />
                <span className="text-sm font-medium text-emerald-700">
                  Sent at {sendState.sentAt}
                </span>
              </div>
            )}

            {sendState.phase === "error" && (
              <div className="flex items-center justify-between gap-3 w-full bg-red-50 border border-red-200 rounded-md px-4 py-2.5">
                <div className="flex items-center gap-2 min-w-0">
                  <X className="w-4 h-4 text-red-500 flex-shrink-0" />
                  <span className="text-sm text-red-700 truncate">{sendState.message}</span>
                  {draft.send_attempts > 1 && (
                    <span className="flex-shrink-0 text-xs font-medium text-red-500 bg-red-100 rounded px-1.5 py-0.5">
                      Attempt {draft.send_attempts}
                    </span>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="border-red-300 text-red-600 hover:bg-red-100 flex-shrink-0"
                  onClick={executeSend}
                >
                  Retry
                </Button>
              </div>
            )}
          </>
        ) : (
          /* Normal action buttons when not in send flow */
          <div className="flex items-center gap-2">
            {draft.status !== "approved" && (
              <>
                <Button
                  onClick={handleApprove}
                  disabled={approving}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  data-shortcut="approve"
                >
                  <Check className="w-4 h-4 mr-1.5" />
                  {approving ? "Approving..." : "Approve"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setShowRejectionDialog(true)}
                  disabled={rejecting}
                  className="border-red-300 text-red-600 hover:bg-red-50 hover:text-red-700"
                  data-shortcut="reject"
                >
                  <X className="w-4 h-4 mr-1.5" />
                  Reject
                </Button>
                {/* Item 3 — Regenerate triggers confirm dialog when draft exists */}
                <Button
                  variant="outline"
                  onClick={handleRegenerateClick}
                  disabled={generating}
                  title="Regenerate draft with AI"
                >
                  <RefreshCw className="w-4 h-4 mr-1.5" />
                  {generating ? "Regenerating..." : "Regenerate"}
                </Button>
              </>
            )}

            {draft.status === "approved" && (
              <>
                <Button
                  onClick={() => setShowSendConfirm(true)}
                  disabled={sendState.phase !== "idle"}
                  className="bg-brand-500 hover:bg-brand-600 text-white"
                >
                  <Send className="w-4 h-4 mr-1.5" />
                  Send
                </Button>
                {/* Item 3 — Regenerate from approved also needs confirm */}
                <Button
                  variant="outline"
                  onClick={handleRegenerateClick}
                  disabled={generating}
                  title="Reject this draft and generate a new one with AI"
                >
                  <RefreshCw className="w-4 h-4 mr-1.5" />
                  {generating ? "Regenerating..." : "Regenerate"}
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      <RejectionDialog
        open={showRejectionDialog}
        onOpenChange={setShowRejectionDialog}
        onReject={handleReject}
        loading={rejecting}
      />

      {/* Item 3 — Regenerate confirm dialog */}
      <ConfirmDialog
        open={showRegenerateConfirm}
        onOpenChange={setShowRegenerateConfirm}
        title="Discard current draft and regenerate?"
        description="This will reject the current draft and ask the AI to generate a new one. Any edits you've made will be lost."
        confirmLabel="Discard & regenerate"
        confirmVariant="destructive"
        onConfirm={handleRegenerateConfirmed}
        loading={generating}
      />

      {/* Send confirm dialog */}
      <ConfirmDialog
        open={showSendConfirm}
        onOpenChange={setShowSendConfirm}
        title="Send this email?"
        description={`Send this email to ${thread.client_email}? You'll have 10 seconds to cancel.`}
        confirmLabel="Send"
        confirmVariant="default"
        onConfirm={handleSendWithCountdown}
      />
    </div>
  );
}
