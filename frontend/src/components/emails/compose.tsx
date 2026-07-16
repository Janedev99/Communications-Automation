"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import {
  Loader2,
  Maximize2,
  Minimize2,
  Minus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SignaturePreview } from "@/components/emails/signature-preview";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { cn } from "@/lib/utils";
import { composeEmail } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { composeDraft } from "@/hooks/use-emails";
import { useCompose } from "@/components/emails/compose-context";
import {
  AttachButton,
  AttachmentChips,
  AttachmentInput,
  useAttachments,
} from "@/components/emails/attachments";

type ComposeMode = "manual" | "ai";

/**
 * The New Email composer. One component, three view modes (full / docked /
 * minimized) driven by ComposeContext — the same instance re-renders into a
 * different shell, so the in-progress email is preserved when Jane shrinks it to
 * the corner to read other mail and expands it again. Supports writing manually
 * or asking the AI to draft from an instruction, plus attachments (25 MB
 * client-side guard mirroring the server cap).
 */
export function Compose() {
  const { viewMode, setViewMode, close } = useCompose();
  const { mutate } = useSWRConfig();

  const [mode, setMode] = useState<ComposeMode>("manual");

  const [to, setTo] = useState("");
  const [showCc, setShowCc] = useState(false);
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const [instruction, setInstruction] = useState("");
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);

  const {
    attachments,
    addFiles,
    removeAttachment,
    totalBytes,
    overSizeLimit,
    inputRef,
    openPicker,
  } = useAttachments();

  const hasContent =
    to.trim().length > 0 ||
    cc.trim().length > 0 ||
    subject.trim().length > 0 ||
    body.trim().length > 0 ||
    attachments.length > 0;

  const canSend =
    !sending &&
    to.trim().length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    !overSizeLimit;

  const isFull = viewMode === "full";
  const isMinimized = viewMode === "minimized";

  const requestClose = () => {
    if (hasContent) setShowDiscardConfirm(true);
    else close();
  };

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
      close();
    } catch (err: unknown) {
      const message =
        err instanceof ApiError ? err.message : "Could not send the email.";
      toast.error(message);
    } finally {
      setSending(false);
    }
  };

  // Outer shell positioning per mode. Full covers the content column (absolute
  // within the layout's relative content area); docked/minimized float in the
  // bottom-right corner (fixed to the viewport, so they escape the content
  // column's overflow and stay reachable on any page).
  const shellClass = isFull
    ? "absolute inset-0 z-40 p-4 lg:p-6"
    : cn(
        "fixed bottom-0 right-4 sm:right-6 z-50",
        isMinimized
          ? "w-[min(22rem,calc(100vw-2rem))]"
          : "w-[min(34rem,calc(100vw-2rem))] h-[min(40rem,calc(100dvh-3.5rem))]",
      );

  return (
    <div className={shellClass} role="dialog" aria-label="New email">
      <div
        className={cn(
          "flex flex-col min-h-0 bg-card border border-border overflow-hidden",
          isFull
            ? "h-full rounded-xl shadow-lg shadow-foreground/5"
            : "rounded-t-xl shadow-2xl shadow-foreground/20",
          !isFull && !isMinimized && "h-full",
        )}
      >
        {/* Title bar — click (when not full) toggles minimize/restore, Gmail-style */}
        <div
          className={cn(
            "flex items-center justify-between gap-2 px-4 flex-shrink-0",
            isFull
              ? "h-14 border-b border-border"
              : "h-11 bg-foreground text-background cursor-pointer select-none",
          )}
          onClick={
            isFull
              ? undefined
              : () => setViewMode(isMinimized ? "docked" : "minimized")
          }
        >
          <div className="flex items-center gap-3 min-w-0">
            <span className={cn("font-medium truncate", isFull ? "text-base" : "text-sm")}>
              {isFull ? "New Email" : subject.trim() || "New message"}
            </span>
            {/* Mode toggle lives in the title bar only in full mode; the docked
                window is tight, so it sits in the body there. */}
            {isFull && <ModeToggle mode={mode} onChange={setMode} />}
          </div>

          <div className="flex items-center gap-1">
            {isFull ? (
              <>
                <TitleBarButton
                  onClick={() => setViewMode("docked")}
                  label="Shrink to corner"
                  subtle
                >
                  <Minimize2 className="w-4 h-4" aria-hidden="true" />
                </TitleBarButton>
                <TitleBarButton
                  onClick={() => setViewMode("minimized")}
                  label="Minimize"
                  subtle
                >
                  <Minus className="w-4 h-4" aria-hidden="true" />
                </TitleBarButton>
              </>
            ) : (
              <>
                <TitleBarButton
                  onClick={(e) => {
                    e.stopPropagation();
                    setViewMode("full");
                  }}
                  label="Expand to full page"
                >
                  <Maximize2 className="w-4 h-4" aria-hidden="true" />
                </TitleBarButton>
                {!isMinimized && (
                  <TitleBarButton
                    onClick={(e) => {
                      e.stopPropagation();
                      setViewMode("minimized");
                    }}
                    label="Minimize"
                  >
                    <Minus className="w-4 h-4" aria-hidden="true" />
                  </TitleBarButton>
                )}
              </>
            )}
            <TitleBarButton
              onClick={(e) => {
                e.stopPropagation();
                requestClose();
              }}
              label="Close"
              subtle={isFull}
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </TitleBarButton>
          </div>
        </div>

        {/* Body — hidden (not unmounted) when minimized so the draft is kept. */}
        <div className={cn("flex flex-col flex-1 min-h-0", isMinimized && "hidden")}>
          <div className="flex flex-col flex-1 min-h-0 overflow-y-auto">
            <div className={cn("flex flex-col gap-3 flex-1 min-h-0", isFull ? "p-5" : "p-4")}>
              {/* Mode toggle for the docked window (full-mode toggle is in the bar) */}
              {!isFull && (
                <ModeToggle mode={mode} onChange={setMode} className="self-start" />
              )}

              {/* Recipients */}
              <div className="flex items-center gap-2 border-b border-border pb-2">
                <label htmlFor="compose-to" className="text-xs text-muted-foreground w-14 shrink-0">
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
                  <label htmlFor="compose-cc" className="text-xs text-muted-foreground w-14 shrink-0">
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
                <label htmlFor="compose-subject" className="text-xs text-muted-foreground w-14 shrink-0">
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
                    className="textarea-autogrow resize-y shrink-0 min-h-[4.5rem] max-h-[40vh] text-sm bg-card"
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

              {/* Body — grows to fill the available height in every mode. */}
              <Textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Write your message…"
                className={cn(
                  "flex-1 resize-none text-sm leading-relaxed",
                  isFull ? "min-h-[16rem]" : "min-h-[8rem]",
                )}
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
            </div>
          </div>

          {/* Footer — pinned so Send is always reachable regardless of body length. */}
          <div className="flex items-center gap-2 px-4 py-3 border-t border-border flex-shrink-0">
            <Button type="button" onClick={handleSend} disabled={!canSend} className="gap-1.5">
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
      </div>

      <ConfirmDialog
        open={showDiscardConfirm}
        onOpenChange={setShowDiscardConfirm}
        title="Discard this email?"
        description="Your unsent message and any attachments will be lost."
        confirmLabel="Discard"
        confirmVariant="destructive"
        onConfirm={() => {
          setShowDiscardConfirm(false);
          close();
        }}
      />
    </div>
  );
}

// ── Small pieces ──────────────────────────────────────────────────────────────

function ModeToggle({
  mode,
  onChange,
  className,
}: {
  mode: ComposeMode;
  onChange: (m: ComposeMode) => void;
  className?: string;
}) {
  return (
    <div className={cn("inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/60", className)}>
      {(
        [
          { id: "manual" as const, label: "Write myself" },
          { id: "ai" as const, label: "Draft with AI" },
        ]
      ).map((m) => (
        <button
          key={m.id}
          type="button"
          onClick={() => onChange(m.id)}
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
  );
}

function TitleBarButton({
  onClick,
  label,
  subtle,
  children,
}: {
  onClick: (e: React.MouseEvent) => void;
  label: string;
  /** subtle = muted-foreground styling (full mode, light bar); otherwise the
      dark docked bar's translucent-hover treatment. */
  subtle?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        "p-1 rounded transition-colors",
        subtle
          ? "text-muted-foreground hover:text-foreground hover:bg-accent"
          : "hover:bg-background/20",
      )}
    >
      {children}
    </button>
  );
}
