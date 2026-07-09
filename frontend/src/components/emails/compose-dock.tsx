"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Loader2, Minus, Send, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SignaturePreview } from "@/components/emails/signature-preview";
import { cn } from "@/lib/utils";
import { composeEmail } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { composeDraft } from "@/hooks/use-emails";
import {
  AttachButton,
  AttachmentChips,
  AttachmentInput,
  useAttachments,
} from "@/components/emails/attachments";

export interface ComposePrefill {
  to?: string;
  subject?: string;
  body?: string;
}

interface ComposeDockProps {
  prefill?: ComposePrefill;
  onClose: () => void;
}

type ComposeMode = "manual" | "ai";

/**
 * Gmail-style docked compose window pinned to the bottom-right. Header bar
 * minimizes/closes; the body supports writing manually or asking the AI to
 * draft from an instruction, plus attachments (add/remove with a running total
 * and a 25 MB client-side guard mirroring the server cap). On send it refreshes
 * the email + dashboard SWR caches so the Inbox / Sent / counts update.
 */
export function ComposeDock({ prefill, onClose }: ComposeDockProps) {
  const { mutate } = useSWRConfig();

  const [minimized, setMinimized] = useState(false);
  const [mode, setMode] = useState<ComposeMode>("manual");

  const [to, setTo] = useState(prefill?.to ?? "");
  const [showCc, setShowCc] = useState(false);
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState(prefill?.subject ?? "");
  const [body, setBody] = useState(prefill?.body ?? "");

  const [instruction, setInstruction] = useState("");
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);

  const {
    attachments,
    addFiles,
    removeAttachment,
    totalBytes,
    overSizeLimit,
    inputRef,
    openPicker,
  } = useAttachments();

  const canSend =
    !sending &&
    to.trim().length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    !overSizeLimit;

  const handleGenerate = async () => {
    if (!instruction.trim() || generating) return;
    setGenerating(true);
    try {
      const result = await composeDraft({
        instruction: instruction.trim(),
        recipient: to.trim() || undefined,
        subject_hint: subject.trim() || undefined,
      });
      setSubject(result.subject);
      setBody(result.body);
      toast.success("Draft ready — review and edit before sending.");
    } catch (err: unknown) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Could not draft the email. Please try again.";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  };

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      await composeEmail({
        to: to.trim(),
        subject: subject.trim(),
        body,
        cc: cc.trim() || undefined,
        attachments,
      });
      toast.success("Email sent.");
      // Revalidate the email list + dashboard counts so Inbox / Sent update.
      mutate(
        (key) =>
          typeof key === "string" &&
          (key.startsWith("/api/v1/emails") || key.startsWith("/api/v1/dashboard")),
      );
      onClose();
    } catch (err: unknown) {
      const message =
        err instanceof ApiError ? err.message : "Could not send the email.";
      toast.error(message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className={cn(
        "fixed bottom-0 right-4 sm:right-6 z-50 flex flex-col",
        "w-[min(34rem,calc(100vw-2rem))] rounded-t-xl bg-card",
        "ring-1 ring-foreground/10 shadow-2xl shadow-foreground/10",
      )}
      role="dialog"
      aria-label="New email"
    >
      {/* Header bar — click to minimize / restore */}
      <div
        className="flex items-center justify-between gap-2 px-4 h-11 rounded-t-xl bg-foreground text-background cursor-pointer select-none"
        onClick={() => setMinimized((m) => !m)}
      >
        <span className="text-sm font-medium truncate">
          {subject.trim() || "New message"}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMinimized((m) => !m);
            }}
            className="p-1 rounded hover:bg-background/20 transition-colors"
            aria-label={minimized ? "Expand" : "Minimize"}
          >
            <Minus className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
            className="p-1 rounded hover:bg-background/20 transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {!minimized && (
        <div className="flex flex-col gap-3 p-4 max-h-[88vh] overflow-y-auto">
          {/* Mode toggle */}
          <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/60 self-start">
            {(
              [
                { id: "manual" as const, label: "Write myself" },
                { id: "ai" as const, label: "Draft with AI" },
              ]
            ).map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setMode(m.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 px-3 h-7 rounded-md text-xs font-medium transition-colors",
                  mode === m.id
                    ? "bg-card text-foreground ring-1 ring-border shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {m.id === "ai" && <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />}
                {m.label}
              </button>
            ))}
          </div>

          {/* Recipients */}
          <div className="flex items-center gap-2 border-b border-border pb-2">
            <label htmlFor="compose-to" className="text-xs text-muted-foreground w-10 shrink-0">
              To
            </label>
            <Input
              id="compose-to"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="name@example.com"
              className="h-7 border-0 shadow-none focus-visible:ring-0 px-0 text-sm"
            />
            {!showCc && (
              <button
                type="button"
                onClick={() => setShowCc(true)}
                className="text-xs text-muted-foreground hover:text-foreground shrink-0"
              >
                Cc
              </button>
            )}
          </div>

          {showCc && (
            <div className="flex items-center gap-2 border-b border-border pb-2">
              <label htmlFor="compose-cc" className="text-xs text-muted-foreground w-10 shrink-0">
                Cc
              </label>
              <Input
                id="compose-cc"
                value={cc}
                onChange={(e) => setCc(e.target.value)}
                placeholder="cc@example.com"
                className="h-7 border-0 shadow-none focus-visible:ring-0 px-0 text-sm"
              />
            </div>
          )}

          {/* Subject */}
          <div className="flex items-center gap-2 border-b border-border pb-2">
            <label htmlFor="compose-subject" className="text-xs text-muted-foreground w-10 shrink-0">
              Subject
            </label>
            <Input
              id="compose-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Subject"
              className="h-7 border-0 shadow-none focus-visible:ring-0 px-0 text-sm"
            />
          </div>

          {/* AI instruction box */}
          {mode === "ai" && (
            <div className="space-y-2 rounded-lg bg-primary/[0.06] border border-primary/20 p-2.5">
              <label htmlFor="compose-instruction" className="text-xs font-medium text-foreground flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                Tell the AI what to say
              </label>
              <Textarea
                id="compose-instruction"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="e.g. Ask the Johnsons to send their 2024 1099s by Friday."
                rows={3}
                maxLength={4000}
                className="resize-y min-h-[4.5rem] text-sm bg-card"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handleGenerate}
                disabled={!instruction.trim() || generating}
                className="h-7 text-xs gap-1.5"
              >
                {generating ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Drafting…
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" /> Generate draft
                  </>
                )}
              </Button>
            </div>
          )}

          {/* Body */}
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Write your message…"
            rows={12}
            className="resize-y min-h-[18rem] text-sm"
          />
          {/* Per-user signatures (018): show exactly what will be appended
              for the current sender (personal, or company fallback). */}
          <SignaturePreview />

          {/* Attachments list */}
          <AttachmentChips
            attachments={attachments}
            onRemove={removeAttachment}
            totalBytes={totalBytes}
            overSizeLimit={overSizeLimit}
          />

          {/* Footer */}
          <div className="flex items-center gap-2 pt-1">
            <Button
              type="button"
              onClick={handleSend}
              disabled={!canSend}
              className="gap-1.5"
            >
              {sending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Sending…
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" /> Send
                </>
              )}
            </Button>
            <AttachButton onClick={openPicker} />
            <AttachmentInput inputRef={inputRef} onFiles={addFiles} />
          </div>
        </div>
      )}
    </div>
  );
}
