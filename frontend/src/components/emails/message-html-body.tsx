"use client";

import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import { ImageOff } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

interface MessageHtmlBodyProps {
  html: string;
  threadId: string;
  messageId: string;
}

/**
 * Renders an email's HTML body the way Outlook does — inline images and all —
 * with two safety layers:
 *   1. DOMPurify strips scripts, event handlers, and dangerous tags (XSS).
 *   2. Remote images are blocked by default (tracking-pixel defense); inline
 *      cid: images are rewritten to our authenticated on-demand endpoint and
 *      shown immediately since they're safe.
 *
 * Plain-text emails never reach here — MessageBubble mounts this only when a
 * body_html exists, and only for inbound messages (which carry client images);
 * otherwise the plain-text renderer with quote folding is used. Sanitizing runs
 * in an effect because DOMPurify needs the DOM (no-op during SSR).
 */
export function MessageHtmlBody({ html, threadId, messageId }: MessageHtmlBodyProps) {
  const [showRemote, setShowRemote] = useState(false);
  const [blockedRemote, setBlockedRemote] = useState(0);
  const [clean, setClean] = useState("");

  const inlineBase = useMemo(
    () => `${API_BASE}/api/v1/emails/${threadId}/messages/${messageId}/inline/`,
    [threadId, messageId],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    let blocked = 0;

    const hook = (node: Element) => {
      if (node.tagName === "IMG") {
        const src = node.getAttribute("src") || "";
        const lower = src.toLowerCase();
        if (lower.startsWith("cid:")) {
          // Embedded image → our authenticated, on-demand inline endpoint.
          node.setAttribute("src", inlineBase + encodeURIComponent(src.slice(4)));
          node.setAttribute("loading", "lazy");
        } else if (/^https?:/i.test(src)) {
          if (showRemote) {
            node.setAttribute("loading", "lazy");
          } else {
            // Tracking-pixel defense: drop the src until the user opts in.
            blocked += 1;
            node.removeAttribute("src");
            node.setAttribute("data-remote-blocked", "1");
          }
        } else if (!lower.startsWith("data:")) {
          // Unknown scheme (file:, etc.) — strip.
          node.removeAttribute("src");
        }
      } else if (node.tagName === "A") {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer nofollow");
      }
    };

    DOMPurify.addHook("afterSanitizeAttributes", hook);
    const sanitized = DOMPurify.sanitize(html, {
      // Inline style attributes stay (email formatting); embedded <style>,
      // frames, forms and metadata tags are stripped so a mail can't restyle
      // the app or smuggle interactive/exfil surfaces.
      FORBID_TAGS: [
        "style",
        "iframe",
        "form",
        "input",
        "button",
        "textarea",
        "select",
        "meta",
        "link",
        "base",
      ],
    });
    DOMPurify.removeHook("afterSanitizeAttributes");

    setClean(sanitized);
    setBlockedRemote(blocked);
  }, [html, showRemote, inlineBase]);

  return (
    <div className="min-w-0">
      {!showRemote && blockedRemote > 0 && (
        <button
          type="button"
          onClick={() => setShowRemote(true)}
          className="mb-2 inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground ring-1 ring-border hover:bg-accent hover:text-foreground transition-colors"
          title="Remote images are blocked by default — loading them can tell the sender when you opened the email."
        >
          <ImageOff className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
          Show {blockedRemote} blocked image{blockedRemote === 1 ? "" : "s"}
        </button>
      )}
      {/* Sanitized above with DOMPurify — scripts, event handlers, and
          dangerous tags are removed before this is set as innerHTML. */}
      <div
        className="text-sm leading-relaxed text-foreground break-words overflow-x-auto [&_img]:max-w-full [&_img]:h-auto [&_table]:max-w-full [&_a]:text-brand-600 [&_a]:underline"
        dangerouslySetInnerHTML={{ __html: clean }}
      />
    </div>
  );
}
