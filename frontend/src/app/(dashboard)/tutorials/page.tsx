"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  Inbox,
  Keyboard,
  Mail,
  MessageSquare,
  Settings,
  ShieldCheck,
  Sliders,
  Sparkles,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { ConfidenceMeter } from "@/components/ui/confidence-meter";
import { SourcePill } from "@/components/ui/source-pill";
import { TierBadge } from "@/components/ui/tier-badge";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "jane_tutorial_viewed_steps";

interface Step {
  id: string;
  title: string;
  icon: LucideIcon;
  description: string;
  visual?: () => JSX.Element;
  link?: { label: string; href: string };
}

// ──────────────────────────────────────────────────────────────────────────────
// Visual mockups — small, real-component renders so users see what's described.
// ──────────────────────────────────────────────────────────────────────────────

function InboxRowDemo() {
  const rows = [
    { tier: "t1_auto" as const, sender: "Maria K.", subject: "Got the docs—thanks!", confidence: 0.94, source: "claude" as const },
    { tier: "t2_review" as const, sender: "John P.", subject: "Can you send my W-2 again?", confidence: 0.74, source: "claude" as const },
    { tier: "t3_escalate" as const, sender: "Anna Y.", subject: "I'm extremely frustrated", confidence: 0.91, source: "claude" as const },
  ];
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden divide-y divide-border/60">
      {rows.map((r) => (
        <div
          key={r.subject}
          className={cn(
            "flex items-center gap-3 px-4 py-3 border-l-4",
            r.tier === "t1_auto" && "border-l-emerald-500",
            r.tier === "t2_review" && "border-l-transparent",
            r.tier === "t3_escalate" && "border-l-red-500",
          )}
        >
          <TierBadge tier={r.tier} variant="glyph" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-foreground truncate">{r.subject}</div>
            <div className="text-xs text-muted-foreground">{r.sender}</div>
          </div>
          <ConfidenceMeter value={r.confidence} compact className="w-32" />
        </div>
      ))}
    </div>
  );
}

function DraftPanelDemo() {
  return (
    <div className="bg-card border border-border rounded-lg p-5 space-y-4">
      <div className="flex items-center gap-2">
        <SourcePill source="claude" />
        <span className="text-xs text-muted-foreground">·</span>
        <ConfidenceMeter value={0.87} compact className="w-40" />
      </div>
      <div className="rounded-md bg-muted/60 border border-border p-3 text-sm text-foreground leading-relaxed">
        Hi Maria,
        <br />
        <br />
        Glad you received the documents. Let us know once you&apos;ve had a chance to review,
        and we&apos;ll get the next round started.
        <br />
        <br />
        Best,
        <br />
        Schiller CPA
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Tone:</span>
        <span className="px-2 py-0.5 rounded ring-1 ring-border text-foreground">Professional</span>
      </div>
      <div className="flex items-center gap-2">
        <button className="text-xs px-3 h-7 rounded ring-1 ring-border text-muted-foreground" disabled>
          Reject
        </button>
        <button className="text-xs px-3 h-7 rounded bg-primary text-primary-foreground" disabled>
          Approve & send →
        </button>
      </div>
    </div>
  );
}

function TierExplainer() {
  const tiers = [
    {
      tier: "t1_auto" as const,
      desc: "High-confidence, allowlisted categories. AI may auto-send (when admin enables it).",
    },
    {
      tier: "t2_review" as const,
      desc: "AI drafts a reply; staff reviews, edits, and approves before send.",
    },
    {
      tier: "t3_escalate" as const,
      desc: "Sensitive content (IRS audit, complaints, legal). Routes to firm owner.",
    },
  ];
  return (
    <div className="space-y-3">
      {tiers.map((t) => (
        <div key={t.tier} className="flex items-start gap-3 p-3 bg-card border border-border rounded-md">
          <TierBadge tier={t.tier} variant="pill" />
          <p className="text-sm text-muted-foreground flex-1">{t.desc}</p>
        </div>
      ))}
    </div>
  );
}

function ConfidenceLegend() {
  return (
    <div className="space-y-3 bg-card border border-border rounded-lg p-4">
      <div className="flex items-center gap-3">
        <ConfidenceMeter value={0.94} className="flex-1" />
      </div>
      <div className="flex items-center gap-3">
        <ConfidenceMeter value={0.72} className="flex-1" />
      </div>
      <div className="flex items-center gap-3">
        <ConfidenceMeter value={0.41} className="flex-1" />
      </div>
      <p className="text-xs text-muted-foreground pt-1">
        85%+ is &ldquo;trust the draft&rdquo;. 60–84% is &ldquo;review carefully&rdquo;. Below 60% means
        the AI is unsure — you may want to rewrite or escalate.
      </p>
    </div>
  );
}

function SourceExplainer() {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3 p-3 bg-card border border-border rounded-md">
        <SourcePill source="claude" />
        <p className="text-sm text-muted-foreground flex-1">
          Default. Claude Sonnet read and classified the email with full context.
        </p>
      </div>
      <div className="flex items-start gap-3 p-3 bg-card border border-border rounded-md">
        <SourcePill source="rules_fallback" />
        <p className="text-sm text-muted-foreground flex-1">
          Claude was unavailable (no API key, budget hit, or network error). The system
          fell back to keyword matching. Confidence is capped at 50% so these never auto-send.
        </p>
      </div>
      <div className="flex items-start gap-3 p-3 bg-card border border-border rounded-md">
        <SourcePill source="manual" />
        <p className="text-sm text-muted-foreground flex-1">
          A staff member re-categorized the thread by hand.
        </p>
      </div>
    </div>
  );
}

function ShortcutsList() {
  const shortcuts = [
    { keys: ["?"], desc: "Show all shortcuts" },
    { keys: ["j"], desc: "Next email in list" },
    { keys: ["k"], desc: "Previous email in list" },
    { keys: ["Enter"], desc: "Open the focused email" },
    { keys: ["a"], desc: "Approve draft (on thread page)" },
    { keys: ["r"], desc: "Reject draft (on thread page)" },
  ];
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden divide-y divide-border/60">
      {shortcuts.map((s) => (
        <div key={s.desc} className="flex items-center justify-between px-4 py-2.5">
          <span className="text-sm text-foreground">{s.desc}</span>
          <span className="flex items-center gap-1">
            {s.keys.map((k) => (
              <kbd
                key={k}
                className="px-2 py-0.5 text-xs font-mono bg-muted text-foreground rounded ring-1 ring-border"
              >
                {k}
              </kbd>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Tutorial steps
// ──────────────────────────────────────────────────────────────────────────────

const STEPS: Step[] = [
  {
    id: "welcome",
    title: "Welcome to Schiller CPA's Staff Portal",
    icon: GraduationCap,
    description:
      "This system reads incoming client email, categorizes each message, drafts a suggested reply using the firm's knowledge base, and lets staff review before anything is sent. Anything sensitive — IRS notices, complaints, legal matters — is escalated directly to Jane. The result: most routine emails handled in seconds, and zero client communication leaves the firm without human approval (unless you explicitly enable T1 auto-send).",
  },
  {
    id: "triage-queue",
    title: "The Email Triage Queue",
    icon: Inbox,
    description:
      "The Emails page is your inbox. Every minute, the system polls the firm's mailbox, pulls in new messages, and runs them through AI categorization. Each row shows the sender, subject preview, AI confidence, and a tier glyph (⚡ auto-handled, ✎ for review, ⚠ escalated). Click a row to open the full thread.",
    visual: InboxRowDemo,
    link: { label: "Open the email queue", href: "/emails" },
  },
  {
    id: "categorization",
    title: "AI Categorization & Confidence",
    icon: Sparkles,
    description:
      "Every email is classified into a category (status update, document request, appointment, complaint, …) along with a confidence score from 0% to 100%. Higher confidence = the AI is more sure. Watch the meter color: amber means low confidence — give that email extra scrutiny.",
    visual: ConfidenceLegend,
  },
  {
    id: "drafts",
    title: "Reviewing AI Drafts",
    icon: MessageSquare,
    description:
      "Open any non-escalated thread and you'll see an AI-drafted reply in the right panel. Edit it, switch tone, then click Approve & send. There's a 10-second undo countdown so a misclick doesn't ship a bad email. If the draft is off, click Reject to ask the AI to retry.",
    visual: DraftPanelDemo,
  },
  {
    id: "sources",
    title: "Where the AI's Decision Came From",
    icon: ShieldCheck,
    description:
      "Each draft and category shows a source pill telling you which engine produced the result. Trust Claude pills more than Rules pills — Claude has full reading comprehension; the rules engine only matches keywords and is used as a safety fallback.",
    visual: SourceExplainer,
  },
  {
    id: "tiers",
    title: "Tier-Based Triage: T1, T2, T3",
    icon: Zap,
    description:
      "Every email is assigned to one of three tiers based on category, confidence, and content. T1 is reserved for safe, high-confidence categories that an admin has explicitly opted in. T2 is the default — every draft sits in the review queue. T3 means the email needs Jane's eyes immediately.",
    visual: TierExplainer,
  },
  {
    id: "escalations",
    title: "Handling Escalations",
    icon: AlertTriangle,
    description:
      "The Escalations page shows every email flagged as T3, sorted by severity (low → critical). When you handle an escalation, click Acknowledge to mark it claimed, then Resolve with notes once the matter is closed. Escalations are color-coded so the dashboard pulses red when something critical is unattended.",
    link: { label: "View escalations", href: "/escalations" },
  },
  {
    id: "knowledge",
    title: "Teach the AI: Knowledge Base",
    icon: BookOpen,
    description:
      "The AI drafts replies using entries from the knowledge base. Add response templates (full draft examples), policies (firm rules to follow), or snippets (reusable phrases) — categorize and tag them, and the draft generator will pull the right context for each email's category.",
    link: { label: "Open knowledge base", href: "/knowledge" },
  },
  {
    id: "triage-rules",
    title: "Configure Triage Rules (admin)",
    icon: Sliders,
    description:
      "Admins can decide which categories are eligible for T1 auto-send and at what minimum confidence. By default, every category is OFF — staff reviews everything. Flip a category on only after you've watched its drafts in shadow mode for a few weeks and trust the output.",
    link: { label: "Configure rules", href: "/settings" },
  },
  {
    id: "shortcuts",
    title: "Keyboard Shortcuts",
    icon: Keyboard,
    description:
      "The portal is built for fast review. Use j/k to walk the inbox, Enter to open, a / r to approve or reject the active draft. Press ? anytime to see the full list. None of these fire while you're typing — safe for editors.",
    visual: ShortcutsList,
  },
];

// ──────────────────────────────────────────────────────────────────────────────
// localStorage helpers
// ──────────────────────────────────────────────────────────────────────────────

function loadViewed(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function saveViewed(viewed: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(viewed)));
  } catch {
    // ignore quota errors — non-critical
  }
}

// ──────────────────────────────────────────────────────────────────────────────

export default function TutorialsPage() {
  const [activeId, setActiveId] = useState<string>(STEPS[0].id);
  const [viewed, setViewed] = useState<Set<string>>(new Set());
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setViewed(loadViewed());
    setMounted(true);
  }, []);

  const activeIndex = useMemo(
    () => Math.max(0, STEPS.findIndex((s) => s.id === activeId)),
    [activeId]
  );
  const active = STEPS[activeIndex];

  const goTo = (id: string) => {
    setActiveId(id);
    setViewed((prev) => {
      const next = new Set(prev);
      next.add(id);
      saveViewed(next);
      return next;
    });
  };

  const goPrev = () => {
    if (activeIndex > 0) goTo(STEPS[activeIndex - 1].id);
  };
  const goNext = () => {
    if (activeIndex < STEPS.length - 1) goTo(STEPS[activeIndex + 1].id);
  };

  // Mark first step as viewed on mount
  useEffect(() => {
    if (mounted && !viewed.has(STEPS[0].id)) {
      const next = new Set(viewed);
      next.add(STEPS[0].id);
      setViewed(next);
      saveViewed(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  const progress = mounted ? (viewed.size / STEPS.length) * 100 : 0;
  const ActiveIcon = active.icon;
  const Visual = active.visual;

  return (
    <div>
      <PageHeader title="Tutorials" />

      {/* Hero / progress strip */}
      <div className="bg-card border border-border rounded-lg p-5 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Getting started
            </p>
            <h1 className="text-xl font-semibold text-foreground mt-1">
              Learn how to run the Staff Portal
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {STEPS.length} short walkthroughs. Pick anything below — your progress is saved automatically.
            </p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-xs text-muted-foreground">Progress</p>
            <p className="text-lg font-semibold text-foreground tabular-nums">
              {viewed.size}/{STEPS.length}
            </p>
          </div>
        </div>
        <div className="mt-4 h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Two-pane: step list + content */}
      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] lg:grid-cols-[260px_1fr] gap-6">
        {/* Step list */}
        <nav aria-label="Tutorial steps" className="space-y-1">
          {STEPS.map((step, idx) => {
            const Icon = step.icon;
            const isActive = step.id === activeId;
            const isViewed = mounted && viewed.has(step.id);
            return (
              <button
                key={step.id}
                onClick={() => goTo(step.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-colors duration-150",
                  isActive
                    ? "bg-card ring-1 ring-border text-foreground"
                    : "hover:bg-accent text-muted-foreground hover:text-foreground"
                )}
                aria-current={isActive ? "step" : undefined}
              >
                <span
                  className={cn(
                    "flex items-center justify-center w-7 h-7 rounded-full text-xs font-semibold shrink-0",
                    isViewed
                      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500/30"
                      : isActive
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground ring-1 ring-border"
                  )}
                >
                  {isViewed && !isActive ? <Check className="w-3.5 h-3.5" /> : idx + 1}
                </span>
                <Icon className="w-4 h-4 shrink-0" strokeWidth={1.75} aria-hidden />
                <span className="text-sm font-medium truncate">{step.title}</span>
              </button>
            );
          })}
        </nav>

        {/* Content */}
        <article className="bg-card border border-border rounded-lg p-6 lg:p-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10 text-primary">
              <ActiveIcon className="w-5 h-5" strokeWidth={1.75} />
            </span>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              Step {activeIndex + 1} of {STEPS.length}
            </p>
          </div>
          <h2 className="text-2xl font-semibold text-foreground leading-tight">
            {active.title}
          </h2>
          <p className="text-base text-foreground/90 leading-relaxed mt-3">
            {active.description}
          </p>

          {Visual && (
            <div className="mt-6">
              <Visual />
            </div>
          )}

          {active.link && (
            <div className="mt-6">
              <Link
                href={active.link.href}
                className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
              >
                {active.link.label}
                <ChevronRight className="w-4 h-4" />
              </Link>
            </div>
          )}

          {/* Prev / Next */}
          <div className="mt-8 pt-6 border-t border-border flex items-center justify-between gap-3">
            <button
              onClick={goPrev}
              disabled={activeIndex === 0}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-medium transition-colors",
                activeIndex === 0
                  ? "text-muted-foreground/50 cursor-not-allowed"
                  : "text-foreground hover:bg-accent"
              )}
            >
              <ChevronLeft className="w-4 h-4" />
              Previous
            </button>

            {activeIndex < STEPS.length - 1 ? (
              <button
                onClick={goNext}
                className="inline-flex items-center gap-1.5 px-4 h-9 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 px-4 h-9 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Finish · Back to dashboard
                <ChevronRight className="w-4 h-4" />
              </Link>
            )}
          </div>
        </article>
      </div>
    </div>
  );
}

// Suppress unused-import warnings for icons that aren't directly referenced
// (they're used by the STEPS array via the Step.icon field).
void [Mail, Settings];
