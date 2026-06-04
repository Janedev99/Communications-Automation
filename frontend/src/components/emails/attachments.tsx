"use client";

import { useCallback, useRef, useState } from "react";
import { Paperclip, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Shared outbound-attachment logic + UI, used by both the compose dock and the
 * draft-reply panel so the size guard, de-dupe, and chip list stay identical.
 *
 * MAX_TOTAL_ATTACHMENT_SIZE mirrors the backend's cap (25 MB) — recipient mail
 * servers commonly bounce anything larger, so we block before the round-trip.
 */
export const MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface UseAttachmentsResult {
  attachments: File[];
  addFiles: (files: FileList | null) => void;
  removeAttachment: (index: number) => void;
  clear: () => void;
  totalBytes: number;
  overSizeLimit: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
  openPicker: () => void;
}

/** State + handlers for an outbound attachment list. */
export function useAttachments(): UseAttachmentsResult {
  const [attachments, setAttachments] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const totalBytes = attachments.reduce((sum, f) => sum + f.size, 0);
  const overSizeLimit = totalBytes > MAX_TOTAL_ATTACHMENT_SIZE;

  // All handlers are memoized so consumers can safely use them as effect deps
  // (e.g. the draft panel clears attachments keyed on thread switch).
  const addFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    setAttachments((prev) => {
      // De-dupe by name+size so re-picking the same file doesn't double it.
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      const additions = Array.from(files).filter(
        (f) => !seen.has(`${f.name}:${f.size}`),
      );
      return [...prev, ...additions];
    });
    // Reset the input so picking the same file again re-fires onChange.
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const removeAttachment = useCallback(
    (index: number) =>
      setAttachments((prev) => prev.filter((_, i) => i !== index)),
    [],
  );

  // Bail out when already empty so a clear-on-mount effect doesn't trigger a
  // pointless extra render.
  const clear = useCallback(
    () => setAttachments((prev) => (prev.length === 0 ? prev : [])),
    [],
  );
  const openPicker = useCallback(() => inputRef.current?.click(), []);

  return {
    attachments,
    addFiles,
    removeAttachment,
    clear,
    totalBytes,
    overSizeLimit,
    inputRef,
    openPicker,
  };
}

/** A hidden multi-file input. Render once per attachment surface and trigger via
 * the hook's `openPicker()`. */
export function AttachmentInput({
  inputRef,
  onFiles,
}: {
  inputRef: React.RefObject<HTMLInputElement>;
  onFiles: (files: FileList | null) => void;
}) {
  return (
    <input
      ref={inputRef}
      type="file"
      multiple
      hidden
      onChange={(e) => onFiles(e.target.files)}
    />
  );
}

/** A paperclip button that opens the file picker. Pass `label` to show text
 * beside the icon (e.g. the draft panel); omit it for the icon-only compose dock. */
export function AttachButton({
  onClick,
  label,
}: {
  onClick: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors",
        label ? "gap-1.5 px-2.5 py-1.5 text-sm font-medium" : "p-2",
      )}
      aria-label={label ?? "Attach files"}
    >
      <Paperclip className="w-4 h-4 shrink-0" />
      {label && <span>{label}</span>}
    </button>
  );
}

/** The attached-files list + running size total (red when over the cap). */
export function AttachmentChips({
  attachments,
  onRemove,
  totalBytes,
  overSizeLimit,
}: {
  attachments: File[];
  onRemove: (index: number) => void;
  totalBytes: number;
  overSizeLimit: boolean;
}) {
  if (attachments.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {attachments.map((file, i) => (
        <div
          key={`${file.name}:${file.size}:${i}`}
          className="flex items-center gap-2 text-xs px-2.5 py-1.5 rounded-md bg-muted/60"
        >
          <Paperclip className="w-3.5 h-3.5 text-muted-foreground shrink-0" aria-hidden="true" />
          <span className="truncate flex-1">{file.name}</span>
          <span className="text-muted-foreground tabular-nums shrink-0">
            {formatBytes(file.size)}
          </span>
          <button
            type="button"
            onClick={() => onRemove(i)}
            className="text-muted-foreground hover:text-destructive shrink-0"
            aria-label={`Remove ${file.name}`}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
      <p
        className={cn(
          "text-[11px] tabular-nums",
          overSizeLimit ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {formatBytes(totalBytes)} of 25 MB
        {overSizeLimit && " — remove some files to send"}
      </p>
    </div>
  );
}
