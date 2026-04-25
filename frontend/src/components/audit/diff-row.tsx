"use client";

import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface DiffRowProps {
  details: Record<string, unknown> | null | undefined;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function formatValue(v: unknown): string {
  if (v === null) return "null";
  if (v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/**
 * Compact diff/details renderer for an audit-log entry's `details` payload.
 *
 * Two modes:
 * 1. **Diff mode** — when `details.before` and `details.after` are both objects.
 *    Renders one row per changed field with strikethrough before / arrow / after.
 * 2. **Flat mode** — for everything else. Renders details as a key/value list,
 *    skipping noisy keys like `message_id` that aren't useful to humans.
 */
export function DiffRow({ details }: DiffRowProps) {
  if (!details || Object.keys(details).length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">No additional details.</p>
    );
  }

  const before = details.before;
  const after = details.after;

  if (isPlainObject(before) && isPlainObject(after)) {
    // Diff view — show only fields that changed
    const allKeys = Array.from(
      new Set([...Object.keys(before), ...Object.keys(after)])
    );
    const changes = allKeys.filter(
      (k) => formatValue(before[k]) !== formatValue(after[k])
    );

    if (changes.length === 0) {
      return (
        <p className="text-xs text-muted-foreground italic">No changes recorded.</p>
      );
    }

    // Surrounding context (e.g., the entity the change applies to)
    const contextKeys = Object.keys(details).filter(
      (k) => k !== "before" && k !== "after"
    );

    return (
      <div className="space-y-2">
        {contextKeys.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {contextKeys.map((k) => (
              <span key={k}>
                <span className="font-mono">{k}</span>
                <span className="opacity-60">: </span>
                <span className="text-foreground">{formatValue(details[k])}</span>
              </span>
            ))}
          </div>
        )}
        <div className="rounded-md ring-1 ring-border overflow-hidden">
          <table className="w-full text-xs">
            <tbody className="divide-y divide-border/60">
              {changes.map((key) => (
                <tr key={key} className="bg-muted/40">
                  <td className="px-3 py-2 font-mono text-muted-foreground w-1/4 align-top">
                    {key}
                  </td>
                  <td className="px-3 py-2 align-top">
                    <span className="text-red-600 dark:text-red-400 line-through break-all">
                      {formatValue(before[key])}
                    </span>
                  </td>
                  <td className="px-2 py-2 align-top w-6 text-muted-foreground">
                    <ArrowRight className="w-3.5 h-3.5" />
                  </td>
                  <td className="px-3 py-2 align-top">
                    <span className="text-emerald-700 dark:text-emerald-400 break-all">
                      {formatValue(after[key])}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Flat view — skip super-noisy keys
  const SKIP_KEYS = new Set(["message_id"]);
  const entries = Object.entries(details).filter(([k]) => !SKIP_KEYS.has(k));
  if (entries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">No additional details.</p>
    );
  }

  return (
    <div className="rounded-md ring-1 ring-border overflow-hidden">
      <table className="w-full text-xs">
        <tbody className="divide-y divide-border/60">
          {entries.map(([key, value]) => (
            <tr key={key} className="bg-muted/40">
              <td className="px-3 py-2 font-mono text-muted-foreground w-1/3 align-top">
                {key}
              </td>
              <td
                className={cn(
                  "px-3 py-2 align-top text-foreground break-all",
                  isPlainObject(value) || Array.isArray(value)
                    ? "font-mono whitespace-pre-wrap"
                    : ""
                )}
              >
                {isPlainObject(value) || Array.isArray(value)
                  ? JSON.stringify(value, null, 2)
                  : formatValue(value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
