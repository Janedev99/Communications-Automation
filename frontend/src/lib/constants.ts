import type {
  EmailCategory,
  EmailStatus,
  DraftStatus,
  EscalationSeverity,
  EscalationStatus,
  EntryType,
  UserRole,
} from "./types";

// Badge color recipe (consistent across the app):
//   light: bg-{c}-50          text-{c}-700        ring-1 ring-inset ring-{c}-200
//   dark : dark:bg-{c}-500/15 dark:text-{c}-300                       dark:ring-{c}-500/30
//
// Subtle (gray) badges use semantic tokens (bg-muted, text-muted-foreground, border)
// so they adapt automatically.

// ── Email Status ──────────────────────────────────────────────────────────────

export const STATUS_LABELS: Record<EmailStatus, string> = {
  new: "New",
  categorized: "Categorized",
  draft_ready: "Draft Ready",
  pending_review: "Pending Review",
  sent: "Sent",
  escalated: "Escalated",
  closed: "Closed",
};

export const STATUS_BADGE_CLASSES: Record<EmailStatus, string> = {
  new:            "bg-blue-50    text-blue-700    ring-1 ring-inset ring-blue-200    dark:bg-blue-500/15    dark:text-blue-300    dark:ring-blue-500/30",
  categorized:    "bg-violet-50  text-violet-700  ring-1 ring-inset ring-violet-200  dark:bg-violet-500/15  dark:text-violet-300  dark:ring-violet-500/30",
  draft_ready:    "bg-amber-50   text-amber-700   ring-1 ring-inset ring-amber-200   dark:bg-amber-500/15   dark:text-amber-300   dark:ring-amber-500/30",
  pending_review: "bg-orange-50  text-orange-700  ring-1 ring-inset ring-orange-200  dark:bg-orange-500/15  dark:text-orange-300  dark:ring-orange-500/30",
  sent:           "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
  escalated:      "bg-red-50     text-red-700     ring-1 ring-inset ring-red-200     dark:bg-red-500/15     dark:text-red-300     dark:ring-red-500/30",
  closed:         "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
};

// ── Email Category ─────────────────────────────────────────────────────────────

export const CATEGORY_LABELS: Record<EmailCategory, string> = {
  status_update: "Status Update",
  document_request: "Document Request",
  appointment: "Appointment",
  clarification: "Clarification",
  general_inquiry: "General Inquiry",
  complaint: "Complaint",
  urgent: "Urgent",
  uncategorized: "Uncategorized",
};

export const CATEGORY_BADGE_CLASSES: Record<EmailCategory, string> = {
  status_update:    "bg-blue-50    text-blue-700    ring-1 ring-inset ring-blue-200    dark:bg-blue-500/15    dark:text-blue-300    dark:ring-blue-500/30",
  document_request: "bg-violet-50  text-violet-700  ring-1 ring-inset ring-violet-200  dark:bg-violet-500/15  dark:text-violet-300  dark:ring-violet-500/30",
  appointment:      "bg-teal-50    text-teal-700    ring-1 ring-inset ring-teal-200    dark:bg-teal-500/15    dark:text-teal-300    dark:ring-teal-500/30",
  clarification:    "bg-indigo-50  text-indigo-700  ring-1 ring-inset ring-indigo-200  dark:bg-indigo-500/15  dark:text-indigo-300  dark:ring-indigo-500/30",
  general_inquiry:  "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
  complaint:        "bg-orange-50  text-orange-700  ring-1 ring-inset ring-orange-200  dark:bg-orange-500/15  dark:text-orange-300  dark:ring-orange-500/30",
  urgent:           "bg-red-50     text-red-700     ring-1 ring-inset ring-red-200     dark:bg-red-500/15     dark:text-red-300     dark:ring-red-500/30",
  uncategorized:    "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
};

// ── Draft Status ──────────────────────────────────────────────────────────────

export const DRAFT_STATUS_LABELS: Record<DraftStatus, string> = {
  pending: "Pending Review",
  edited: "Edited",
  approved: "Approved",
  rejected: "Rejected",
  sent: "Sent",
  send_failed: "Send Failed",
};

export const DRAFT_STATUS_BADGE_CLASSES: Record<DraftStatus, string> = {
  pending:     "bg-amber-50   text-amber-700   ring-1 ring-inset ring-amber-200   dark:bg-amber-500/15   dark:text-amber-300   dark:ring-amber-500/30",
  edited:      "bg-blue-50    text-blue-700    ring-1 ring-inset ring-blue-200    dark:bg-blue-500/15    dark:text-blue-300    dark:ring-blue-500/30",
  approved:    "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
  rejected:    "bg-red-50     text-red-700     ring-1 ring-inset ring-red-200     dark:bg-red-500/15     dark:text-red-300     dark:ring-red-500/30",
  sent:        "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
  send_failed: "bg-red-50     text-red-700     ring-1 ring-inset ring-red-200     dark:bg-red-500/15     dark:text-red-300     dark:ring-red-500/30",
};

// ── Escalation ────────────────────────────────────────────────────────────────

export const SEVERITY_LABELS: Record<EscalationSeverity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const SEVERITY_BADGE_CLASSES: Record<EscalationSeverity, string> = {
  low:      "bg-slate-50  text-slate-700  ring-1 ring-inset ring-slate-200  dark:bg-slate-500/15  dark:text-slate-300  dark:ring-slate-500/30",
  medium:   "bg-yellow-50 text-yellow-700 ring-1 ring-inset ring-yellow-200 dark:bg-yellow-500/15 dark:text-yellow-300 dark:ring-yellow-500/30",
  high:     "bg-orange-50 text-orange-700 ring-1 ring-inset ring-orange-200 dark:bg-orange-500/15 dark:text-orange-300 dark:ring-orange-500/30",
  critical: "bg-red-50    text-red-700    ring-1 ring-inset ring-red-200    dark:bg-red-500/15    dark:text-red-300    dark:ring-red-500/30",
};

// Row border colors — these are vibrant accents that read in both modes,
// so no dark variant needed.
export const SEVERITY_ROW_BORDER: Record<EscalationSeverity, string> = {
  low:      "border-l-slate-400",
  medium:   "border-l-yellow-400",
  high:     "border-l-orange-400",
  critical: "border-l-red-400",
};

export const ESCALATION_STATUS_LABELS: Record<EscalationStatus, string> = {
  pending: "Pending",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

export const ESCALATION_STATUS_BADGE_CLASSES: Record<EscalationStatus, string> = {
  pending:      "bg-amber-50   text-amber-700   ring-1 ring-inset ring-amber-200   dark:bg-amber-500/15   dark:text-amber-300   dark:ring-amber-500/30",
  acknowledged: "bg-blue-50    text-blue-700    ring-1 ring-inset ring-blue-200    dark:bg-blue-500/15    dark:text-blue-300    dark:ring-blue-500/30",
  resolved:     "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
};

// ── Knowledge ─────────────────────────────────────────────────────────────────

export const ENTRY_TYPE_LABELS: Record<EntryType, string> = {
  response_template: "Response Template",
  policy: "Policy",
  snippet: "Snippet",
};

export const ENTRY_TYPE_BADGE_CLASSES: Record<EntryType, string> = {
  response_template: "bg-blue-50   text-blue-700   ring-1 ring-inset ring-blue-200   dark:bg-blue-500/15   dark:text-blue-300   dark:ring-blue-500/30",
  policy:            "bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/30",
  snippet:           "bg-teal-50   text-teal-700   ring-1 ring-inset ring-teal-200   dark:bg-teal-500/15   dark:text-teal-300   dark:ring-teal-500/30",
};

// ── Role ─────────────────────────────────────────────────────────────────────

export const ROLE_LABELS: Record<UserRole, string> = {
  staff: "Staff",
  admin: "Admin",
};

export const ROLE_BADGE_CLASSES: Record<UserRole, string> = {
  staff: "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
  admin: "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-100 dark:bg-brand-500/15 dark:text-brand-300 dark:ring-brand-500/30",
};
