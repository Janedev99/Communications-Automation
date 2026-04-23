import type {
  EmailCategory,
  EmailStatus,
  DraftStatus,
  EscalationSeverity,
  EscalationStatus,
  EntryType,
  UserRole,
} from "./types";

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

/** Badge classes: bg-{color}-50 text-{color}-700 ring-1 ring-inset ring-{color}-200 */
export const STATUS_BADGE_CLASSES: Record<EmailStatus, string> = {
  new: "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200",
  categorized: "bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200",
  draft_ready: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200",
  pending_review: "bg-orange-50 text-orange-700 ring-1 ring-inset ring-orange-200",
  sent: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
  escalated: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
  closed: "bg-gray-100 text-gray-600 ring-1 ring-inset ring-gray-200",
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
  status_update: "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200",
  document_request: "bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200",
  appointment: "bg-teal-50 text-teal-700 ring-1 ring-inset ring-teal-200",
  clarification: "bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200",
  general_inquiry: "bg-gray-100 text-gray-600 ring-1 ring-inset ring-gray-200",
  complaint: "bg-orange-50 text-orange-700 ring-1 ring-inset ring-orange-200",
  urgent: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
  uncategorized: "bg-gray-100 text-gray-500 ring-1 ring-inset ring-gray-200",
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
  pending: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200",
  edited: "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200",
  approved: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
  rejected: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
  sent: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
  send_failed: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
};

// ── Escalation ────────────────────────────────────────────────────────────────

export const SEVERITY_LABELS: Record<EscalationSeverity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const SEVERITY_BADGE_CLASSES: Record<EscalationSeverity, string> = {
  low: "bg-slate-50 text-slate-700 ring-1 ring-inset ring-slate-200",
  medium: "bg-yellow-50 text-yellow-700 ring-1 ring-inset ring-yellow-200",
  high: "bg-orange-50 text-orange-700 ring-1 ring-inset ring-orange-200",
  critical: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
};

export const SEVERITY_ROW_BORDER: Record<EscalationSeverity, string> = {
  low: "border-l-slate-400",
  medium: "border-l-yellow-400",
  high: "border-l-orange-400",
  critical: "border-l-red-400",
};

export const ESCALATION_STATUS_LABELS: Record<EscalationStatus, string> = {
  pending: "Pending",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

export const ESCALATION_STATUS_BADGE_CLASSES: Record<EscalationStatus, string> = {
  pending: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200",
  acknowledged: "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200",
  resolved: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
};

// ── Knowledge ─────────────────────────────────────────────────────────────────

export const ENTRY_TYPE_LABELS: Record<EntryType, string> = {
  response_template: "Response Template",
  policy: "Policy",
  snippet: "Snippet",
};

export const ENTRY_TYPE_BADGE_CLASSES: Record<EntryType, string> = {
  response_template: "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200",
  policy: "bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200",
  snippet: "bg-teal-50 text-teal-700 ring-1 ring-inset ring-teal-200",
};

// ── Role ─────────────────────────────────────────────────────────────────────

export const ROLE_LABELS: Record<UserRole, string> = {
  staff: "Staff",
  admin: "Admin",
};

export const ROLE_BADGE_CLASSES: Record<UserRole, string> = {
  staff: "bg-gray-100 text-gray-600 ring-1 ring-inset ring-gray-200",
  admin: "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-100",
};

