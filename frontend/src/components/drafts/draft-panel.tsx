"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Check, X, Send, FileEdit, Loader2, Lock, LayoutTemplate } from "lucide-react";
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
import { cn, formatDate } from "@/lib/utils";
import type { DraftResponse, EmailThread, KnowledgeEntry } from "@/lib/types";

interface DraftPanelProps {
  thread: EmailThread;
  draft: DraftResponse | undefined;
  onDraftChange: () => void;
}

type AutoSaveState = "saved" | "saving" | "unsaved" | "idle";

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
  const [sending, setSending] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [creatingFromTemplate, setCreatingFromTemplate] = useState(false);
  const [showRejectionDialog, setShowRejectionDialog] = useState(false);
  const [showSendConfirm, setShowSendConfirm] = useState(false);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [editedText, setEditedText] = useState(draft?.body_text ?? "");
  const [showOriginal, setShowOriginal] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle");
  // Tone selector — defaults to thread's suggested tone
  const [selectedTone, setSelectedTone] = useState<string>(
    thread.suggested_reply_tone ?? "professional"
  );
  // Undo-send countdown
  const [undoCountdown, setUndoCountdown] = useState<number | null>(null);
  const undoTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sendCancelledRef = useRef(false);

  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up timers on unmount
  useEffect(() => {
    return () => {
      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
      if (undoTimerRef.current) clearInterval(undoTimerRef.current);
    };
  }, []);

  // Sync editedText when draft changes
  useEffect(() => {
    setEditedText(draft?.body_text ?? "");
    setAutoSaveState("idle");
  }, [draft?.id, draft?.body_text]);

  // Sync tone from thread whenever thread updates
  useEffect(() => {
    setSelectedTone(thread.suggested_reply_tone ?? "professional");
  }, [thread.suggested_reply_tone]);

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

  // Performs the actual send after the undo countdown expires
  const executeSend = async () => {
    if (!draft) return;
    setSending(true);
    try {
      await api.post(`/api/v1/emails/${thread.id}/drafts/${draft.id}/send`);
      onDraftChange();
      toast.success("Email sent successfully.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to send email.");
    } finally {
      setSending(false);
    }
  };

  // Starts the 10-second undo countdown after the confirm dialog is accepted
  const handleSendWithUndo = () => {
    setShowSendConfirm(false);
    sendCancelledRef.current = false;
    setUndoCountdown(UNDO_COUNTDOWN_SECONDS);

    let remaining = UNDO_COUNTDOWN_SECONDS;

    toast.loading(`Sending in ${remaining}s…`, {
      id: "undo-send",
      action: {
        label: "Undo",
        onClick: () => {
          sendCancelledRef.current = true;
          if (undoTimerRef.current) clearInterval(undoTimerRef.current);
          setUndoCountdown(null);
          toast.dismiss("undo-send");
          toast.info("Send cancelled.");
        },
      },
      duration: (UNDO_COUNTDOWN_SECONDS + 1) * 1000,
    });

    undoTimerRef.current = setInterval(() => {
      remaining -= 1;
      if (sendCancelledRef.current) {
        clearInterval(undoTimerRef.current!);
        setUndoCountdown(null);
        return;
      }
      if (remaining <= 0) {
        clearInterval(undoTimerRef.current!);
        setUndoCountdown(null);
        toast.dismiss("undo-send");
        if (!sendCancelledRef.current) {
          executeSend();
        }
      } else {
        setUndoCountdown(remaining);
        toast.loading(`Sending in ${remaining}s…`, {
          id: "undo-send",
          action: {
            label: "Undo",
            onClick: () => {
              sendCancelledRef.current = true;
              if (undoTimerRef.current) clearInterval(undoTimerRef.current);
              setUndoCountdown(null);
              toast.dismiss("undo-send");
              toast.info("Send cancelled.");
            },
          },
          duration: (remaining + 1) * 1000,
        });
      }
    }, 1000);
  };

  // Handle template selection — creates a manual draft via POST /emails/{id}/drafts
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
    <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
      <span className="text-sm font-semibold text-gray-700">Draft Response</span>
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
          <span className="text-xs text-gray-400">v{draft.version}</span>
        </div>
      )}
    </div>
  );

  // ── State A: No draft ──────────────────────────────────────────────────────
  if (!draft) {
    return (
      <div className="bg-white flex flex-col h-full">
        {panelHeader}
        <div className="flex flex-col items-center justify-center flex-1 px-6 text-center gap-4">
          <FileEdit className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="text-sm text-gray-500">
            No draft has been generated for this thread yet.
          </p>

          {/* Tone selector */}
          <div className="w-full max-w-[220px]">
            <label className="block text-xs font-medium text-gray-500 mb-1.5 text-left">
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
      <div className="bg-white flex flex-col h-full">
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
            <p className="text-sm text-gray-500 leading-relaxed whitespace-pre-wrap">
              {draft.body_text}
            </p>
          </div>
        </div>
        <div className="px-5 py-4 border-t border-gray-200 flex-shrink-0 space-y-3">
          {/* Tone selector before regenerate */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">Tone</label>
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
      <div className="bg-white flex flex-col h-full">
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
            <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">
              {draft.body_text}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── State B: Draft pending or edited (active editing) ─────────────────────
  const displayText = showOriginal
    ? (draft.original_body_text ?? draft.body_text)
    : editedText;

  return (
    <div className="bg-white flex flex-col h-full">
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
            "flex-1 w-full resize-none border-0 focus-visible:ring-0 focus-visible:ring-offset-0 text-sm text-gray-700 leading-relaxed p-0 min-h-[200px]",
            draft.status === "approved" && "bg-gray-50"
          )}
          placeholder="Draft content will appear here..."
        />
        {autoSaveLabel && !showOriginal && (
          <p className="text-[10px] text-gray-400 mt-1">{autoSaveLabel}</p>
        )}
      </div>

      {/* Version/meta bar */}
      {draft.original_body_text && draft.original_body_text !== draft.body_text && (
        <div className="px-5 py-2 bg-gray-50 border-t border-gray-100 flex items-center justify-between flex-shrink-0">
          <span className="text-xs text-gray-400">
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
          <label className="block text-xs font-medium text-gray-500 mb-1">Tone override</label>
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
      <div className="px-5 py-4 border-t border-gray-200 flex items-center gap-2 flex-shrink-0">
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
          </>
        )}

        {draft.status === "approved" && (
          <Button
            onClick={() => setShowSendConfirm(true)}
            disabled={sending || undoCountdown !== null}
            className="bg-brand-500 hover:bg-brand-600 text-white"
          >
            <Send className="w-4 h-4 mr-1.5" />
            {undoCountdown !== null
              ? `Sending in ${undoCountdown}s…`
              : sending
              ? "Sending..."
              : "Send"}
          </Button>
        )}
      </div>

      <RejectionDialog
        open={showRejectionDialog}
        onOpenChange={setShowRejectionDialog}
        onReject={handleReject}
        loading={rejecting}
      />

      <ConfirmDialog
        open={showSendConfirm}
        onOpenChange={setShowSendConfirm}
        title="Send this email?"
        description={`Send this email to ${thread.client_email}? You'll have 10 seconds to undo.`}
        confirmLabel="Send"
        confirmVariant="default"
        onConfirm={handleSendWithUndo}
        loading={sending}
      />
    </div>
  );
}
