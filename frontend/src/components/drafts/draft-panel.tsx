"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Check, X, Send, FileEdit, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { RejectionDialog } from "./rejection-dialog";
import { DRAFT_STATUS_BADGE_CLASSES, DRAFT_STATUS_LABELS } from "@/lib/constants";
import { api } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import type { DraftResponse, EmailThread } from "@/lib/types";

interface DraftPanelProps {
  thread: EmailThread;
  draft: DraftResponse | undefined;
  onDraftChange: () => void;
}

type AutoSaveState = "saved" | "saving" | "unsaved" | "idle";

export function DraftPanel({ thread, draft, onDraftChange }: DraftPanelProps) {
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState(false);
  const [sending, setSending] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [showRejectionDialog, setShowRejectionDialog] = useState(false);
  const [editedText, setEditedText] = useState(draft?.body_text ?? "");
  const [showOriginal, setShowOriginal] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle");
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync editedText when draft changes
  useEffect(() => {
    setEditedText(draft?.body_text ?? "");
    setAutoSaveState("idle");
  }, [draft?.id, draft?.body_text]);

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
      await api.post(`/api/v1/emails/${thread.id}/generate-draft`);
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
      await api.post(`/api/v1/emails/${thread.id}/drafts/${draft.id}/reject`, { rejection_reason: reason });
      setShowRejectionDialog(false);
      onDraftChange();
      toast.success("Draft rejected.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to reject draft.");
    } finally {
      setRejecting(false);
    }
  };

  const handleSend = async () => {
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
      <div className="border-l border-gray-200 bg-white flex flex-col h-full">
        {panelHeader}
        <div className="flex flex-col items-center justify-center flex-1 px-6 text-center">
          <FileEdit className="w-10 h-10 text-gray-300 mb-3" strokeWidth={1.5} />
          <p className="text-sm text-gray-500 mb-4">
            No draft has been generated for this thread yet.
          </p>
          <Button
            className="bg-brand-500 hover:bg-brand-600 text-white"
            onClick={handleGenerate}
            disabled={generating}
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
        </div>
      </div>
    );
  }

  // ── State C: Draft rejected ────────────────────────────────────────────────
  if (draft.status === "rejected") {
    return (
      <div className="border-l border-gray-200 bg-white flex flex-col h-full">
        {panelHeader}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-5 mt-4 px-4 py-3 rounded-md bg-red-50 border border-red-200">
            <p className="text-xs font-medium text-red-600 uppercase tracking-wide">Rejected</p>
            <p className="text-sm text-red-700 mt-1">{draft.rejection_reason}</p>
            {draft.reviewed_at && (
              <p className="text-xs text-red-400 mt-2">
                {formatDate(draft.reviewed_at)}
              </p>
            )}
          </div>
          <div className="px-5 py-4">
            <p className="text-sm text-gray-500 leading-relaxed whitespace-pre-wrap">
              {draft.body_text}
            </p>
          </div>
        </div>
        <div className="px-5 py-4 border-t border-gray-200 flex-shrink-0">
          <Button
            className="bg-brand-500 hover:bg-brand-600 text-white w-full"
            onClick={handleGenerate}
            disabled={generating}
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
        </div>
      </div>
    );
  }

  // ── State D: Draft sent ────────────────────────────────────────────────────
  if (draft.status === "sent") {
    return (
      <div className="border-l border-gray-200 bg-white flex flex-col h-full">
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
    <div className="border-l border-gray-200 bg-white flex flex-col h-full">
      {panelHeader}

      {/* Editor */}
      <div className="flex-1 px-5 py-4 overflow-hidden flex flex-col">
        <Textarea
          value={displayText}
          onChange={(e) => !showOriginal && handleTextChange(e.target.value)}
          readOnly={showOriginal || draft.status === "approved"}
          className="flex-1 w-full resize-none border-0 focus-visible:ring-0 focus-visible:ring-offset-0 text-sm text-gray-700 leading-relaxed p-0 min-h-[200px]"
          placeholder="Draft content will appear here..."
        />
        {autoSaveLabel && !showOriginal && (
          <p className="text-[10px] text-gray-300 mt-1">{autoSaveLabel}</p>
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

      {/* Action buttons */}
      <div className="px-5 py-4 border-t border-gray-200 flex items-center gap-2 flex-shrink-0">
        {draft.status !== "approved" && (
          <>
            <button
              onClick={handleApprove}
              disabled={approving}
              className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-emerald-600 hover:bg-emerald-700 text-white transition-colors disabled:opacity-50"
            >
              <Check className="w-4 h-4" />
              {approving ? "Approving..." : "Approve"}
            </button>
            <button
              onClick={() => setShowRejectionDialog(true)}
              disabled={rejecting}
              className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-white border border-red-300 text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              <X className="w-4 h-4" />
              Reject
            </button>
          </>
        )}

        {draft.status === "approved" && (
          <button
            onClick={handleSend}
            disabled={sending}
            className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition-colors disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
            {sending ? "Sending..." : "Send"}
          </button>
        )}
      </div>

      <RejectionDialog
        open={showRejectionDialog}
        onOpenChange={setShowRejectionDialog}
        onReject={handleReject}
        loading={rejecting}
      />
    </div>
  );
}
