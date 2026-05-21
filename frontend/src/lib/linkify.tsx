import type { ReactNode } from "react";

/**
 * Inline rich-text renderer for email body text.
 *
 * The backend converts inbound HTML to text via ``html2text``
 * (``email_provider.py:54-63``), which:
 *
 *   - Emits links as ``[text](url)`` markdown
 *   - Emits ``<strong>`` / ``<b>`` as ``**text**``
 *   - Emits ``<em>`` / ``<i>`` as ``_text_``
 *   - Escapes markdown-special punctuation with backslashes — so
 *     ``(979) 575-7272`` arrives as ``\(979\) 575-7272`` and ``much!``
 *     arrives as ``much\!``. These escapes serve markdown-parser safety
 *     but visually pollute the bubble.
 *
 * Without this renderer, every one of those constructs ships to the UI
 * as literal characters — the user sees ``**Schiller CPA Team**`` and
 * ``\(979\) 575-7272`` instead of formatted text.
 *
 * ``renderInline`` reverses all four transforms in one pass:
 *
 *   1. Unescape backslash-escaped punctuation (text-level transform)
 *   2. Tokenize for markdown links (most structured, lowest false-positive)
 *   3. Tokenize for bare http(s) / mailto URLs in the remaining text
 *   4. Tokenize for ``**bold**``
 *   5. Tokenize for ``_italic_`` at word boundaries (so ``snake_case_words``
 *      survive intact — real CPA emails rarely contain markdown italic
 *      mid-word, but rare enough false-positives are visually loud)
 *
 * Security guards on links:
 *   - Only ``http``/``https``/``mailto`` schemes are made clickable —
 *     ``javascript:``, ``data:``, etc. are rendered as plain text.
 *   - ``target="_blank" rel="noopener noreferrer"`` — opens in a new tab
 *     AND prevents the opened page from navigating the opener via
 *     ``window.opener`` (tab-hijacking defence).
 *   - ``title`` exposes the real href when display text differs, so a
 *     deceptive ``[google.com](https://evil.com)`` is visible on hover.
 *   - Trailing punctuation is stripped from bare URLs.
 *
 * Returns ``ReactNode[]`` for drop-in use inside JSX children.
 */

type Token =
  | { kind: "text"; value: string }
  | { kind: "link"; href: string; display: string }
  | { kind: "bold"; value: string }
  | { kind: "italic"; value: string };

// Reverses the punctuation escapes that html2text emits. The character
// class deliberately omits letters / digits — we only unescape characters
// that ARE markdown-special (so `\n` in the wild stays as `\n`).
const ESCAPED_PUNCT_RE = /\\([!()[\]*_#+\-,.\\`])/g;

const MARKDOWN_LINK_RE =
  /\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g;
const BARE_URL_RE = /https?:\/\/[^\s<>"'`)\]]+/g;
const BOLD_RE = /\*\*([^*\n]+?)\*\*/g;
// Italic anchored at boundaries: ``_text_`` must be preceded by start/whitespace/
// punctuation AND followed by end/whitespace/punctuation. This is what stops
// ``snake_case_word`` from incorrectly italicising ``_case_`` mid-token.
const ITALIC_RE = /(^|[\s.,;:!?])_([^_\n]+?)_(?=$|[\s.,;:!?])/g;
const TRAILING_PUNCT_RE = /[.,;:!?)\]]+$/;

function isSafeHref(href: string): boolean {
  const lower = href.trim().toLowerCase();
  return (
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    lower.startsWith("mailto:")
  );
}

function stripTrailingPunct(url: string): { url: string; trailing: string } {
  const m = url.match(TRAILING_PUNCT_RE);
  if (!m) return { url, trailing: "" };
  return { url: url.slice(0, -m[0].length), trailing: m[0] };
}

// Apply a per-segment splitter to every `text`-kind token in `tokens`,
// leaving structured tokens (links / bold / italic from earlier passes)
// untouched. This is how the pipeline composes — each pass refines text
// segments without redoing structure earlier passes already established.
function expandTextTokens(
  tokens: Token[],
  splitter: (text: string) => Token[],
): Token[] {
  const result: Token[] = [];
  for (const t of tokens) {
    if (t.kind === "text") {
      result.push(...splitter(t.value));
    } else {
      result.push(t);
    }
  }
  return result;
}

function splitMarkdownLinks(text: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;
  for (const m of Array.from(text.matchAll(MARKDOWN_LINK_RE))) {
    const full = m[0];
    const label = m[1];
    const href = m[2];
    const idx = m.index ?? 0;
    if (idx > cursor) tokens.push({ kind: "text", value: text.slice(cursor, idx) });
    if (isSafeHref(href)) {
      tokens.push({ kind: "link", href, display: label });
    } else {
      // Unsafe scheme — emit the raw markdown source rather than silently
      // hiding the brackets. Better the user sees ``[click](javascript:…)``
      // and decides than that we hide a suspicious link entirely.
      tokens.push({ kind: "text", value: full });
    }
    cursor = idx + full.length;
  }
  if (cursor < text.length) tokens.push({ kind: "text", value: text.slice(cursor) });
  return tokens;
}

function splitBareUrls(text: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;
  for (const m of Array.from(text.matchAll(BARE_URL_RE))) {
    const full = m[0];
    const idx = m.index ?? 0;
    if (idx > cursor) tokens.push({ kind: "text", value: text.slice(cursor, idx) });
    const { url, trailing } = stripTrailingPunct(full);
    if (isSafeHref(url)) {
      tokens.push({ kind: "link", href: url, display: url });
      if (trailing) tokens.push({ kind: "text", value: trailing });
    } else {
      tokens.push({ kind: "text", value: full });
    }
    cursor = idx + full.length;
  }
  if (cursor < text.length) tokens.push({ kind: "text", value: text.slice(cursor) });
  return tokens;
}

function splitBold(text: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;
  for (const m of Array.from(text.matchAll(BOLD_RE))) {
    const full = m[0];
    const inner = m[1];
    const idx = m.index ?? 0;
    if (idx > cursor) tokens.push({ kind: "text", value: text.slice(cursor, idx) });
    tokens.push({ kind: "bold", value: inner });
    cursor = idx + full.length;
  }
  if (cursor < text.length) tokens.push({ kind: "text", value: text.slice(cursor) });
  return tokens;
}

function splitItalic(text: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;
  for (const m of Array.from(text.matchAll(ITALIC_RE))) {
    const full = m[0];
    const lead = m[1]; // boundary char (whitespace/punct) that anchored the match
    const inner = m[2];
    const idx = m.index ?? 0;
    if (idx > cursor) tokens.push({ kind: "text", value: text.slice(cursor, idx) });
    // The leading boundary character is captured (so the regex can require
    // it without trying to use a variable-width lookbehind). Re-emit it as
    // text so it isn't dropped. Empty `lead` means we matched at start-of-
    // string, where there's no preceding char to preserve.
    if (lead) tokens.push({ kind: "text", value: lead });
    tokens.push({ kind: "italic", value: inner });
    cursor = idx + full.length;
  }
  if (cursor < text.length) tokens.push({ kind: "text", value: text.slice(cursor) });
  return tokens;
}

export function renderInline(text: string): ReactNode[] {
  // Pre-pass: undo the markdown-escape backslashes html2text inserts.
  // Done as a flat string replace — escapes are local and don't interact
  // with the structural patterns the tokenizers look for.
  const cleaned = text.replace(ESCAPED_PUNCT_RE, "$1");

  // Tokenization pipeline. Markdown links first (their brackets are the
  // most explicit author intent), then bare URLs in the remainder, then
  // bold, then italic. Each pass only refines `text`-kind tokens — earlier
  // structural decisions survive untouched.
  let tokens: Token[] = [{ kind: "text", value: cleaned }];
  tokens = expandTextTokens(tokens, splitMarkdownLinks);
  tokens = expandTextTokens(tokens, splitBareUrls);
  tokens = expandTextTokens(tokens, splitBold);
  tokens = expandTextTokens(tokens, splitItalic);

  return tokens.map((t, i) => {
    switch (t.kind) {
      case "text":
        return <span key={i}>{t.value}</span>;
      case "link": {
        const showTitle = t.display !== t.href;
        return (
          <a
            key={i}
            href={t.href}
            target="_blank"
            rel="noopener noreferrer"
            title={showTitle ? t.href : undefined}
            className="underline underline-offset-2 hover:opacity-80 break-words"
          >
            {t.display}
          </a>
        );
      }
      case "bold":
        // font-semibold rather than browser-default bold (font-bold = 700).
        // 600 reads less aggressive on the small body font size used in
        // the bubble — and matches how shadcn typography handles emphasis.
        return (
          <strong key={i} className="font-semibold">
            {t.value}
          </strong>
        );
      case "italic":
        return (
          <em key={i} className="italic">
            {t.value}
          </em>
        );
    }
  });
}
