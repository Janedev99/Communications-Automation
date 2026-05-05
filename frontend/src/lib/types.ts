// ── Enums ─────────────────────────────────────────────────────────────────────
export type EmailStatus =
  | "new"
  | "categorized"
  | "draft_ready"
  | "pending_review"
  | "sent"
  | "escalated"
  | "closed";

export type EmailCategory =
  | "status_update"
  | "document_request"
  | "appointment"
  | "clarification"
  | "general_inquiry"
  | "complaint"
  | "urgent"
  | "uncategorized";

export type DraftStatus = "pending" | "edited" | "approved" | "rejected" | "sent" | "send_failed";
export type EscalationSeverity = "low" | "medium" | "high" | "critical";
export type EscalationStatus = "pending" | "acknowledged" | "resolved";
export type UserRole = "staff" | "admin";
export type EntryType = "response_template" | "policy" | "snippet";

// Phase 3 — tier-based triage
export type ThreadTier = "t1_auto" | "t2_review" | "t3_escalate";
export type CategorizationSource = "claude" | "rules_fallback" | "manual";

// ── Auth ──────────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface MeResponse {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  is_active: boolean;
}

export interface LoginResponse {
  user: User;
  session_id: string;
  expires_at: string;
}

// ── Email ─────────────────────────────────────────────────────────────────────
export interface AttachmentInfo {
  filename: string;
  size: number | null;
  content_type: string | null;
}

export interface EmailMessage {
  id: string;
  thread_id: string;
  message_id_header: string;
  sender: string;
  recipient: string | null;
  body_text: string | null;
  received_at: string;
  direction: "inbound" | "outbound";
  is_processed: boolean;
  attachments: AttachmentInfo[] | null;
}

export interface EmailThread {
  id: string;
  subject: string;
  client_email: string;
  client_name: string | null;
  status: EmailStatus;
  category: EmailCategory;
  category_confidence: number | null;
  ai_summary: string | null;
  suggested_reply_tone: string | null;
  assigned_to_id: string | null;
  assigned_to_name: string | null;
  created_at: string;
  updated_at: string;
  messages: EmailMessage[];
  /** True when the last AI draft generation attempt failed for this thread */
  draft_generation_failed: boolean;
  /** ISO timestamp of the failed generation attempt, or null */
  draft_generation_failed_at: string | null;
  /** Phase 3: triage tier (t1_auto / t2_review / t3_escalate). Defaults to t2_review server-side. */
  tier: ThreadTier;
  /** Phase 3: ISO timestamp when the tier was last assigned. */
  tier_set_at: string | null;
  /** Phase 3: who set the tier — "system" for the intake pipeline, or a user's email. */
  tier_set_by: string | null;
  /** Phase 3: which engine produced the categorization. */
  categorization_source: CategorizationSource;
  /** Phase 3: ISO timestamp when this thread was auto-sent (T1 only), or null. */
  auto_sent_at: string | null;
  /** Save-to-folder state */
  is_saved: boolean;
  saved_folder: string | null;
  saved_note: string | null;
  saved_at: string | null;
  saved_by_id: string | null;
  saved_by_name: string | null;
}

export interface SavedFolder {
  /** Folder name. Null indicates the unsorted/unfiled saved bucket. */
  name: string | null;
  count: number;
}

export interface EmailThreadListItem {
  id: string;
  subject: string;
  client_email: string;
  client_name: string | null;
  status: EmailStatus;
  category: EmailCategory;
  category_confidence: number | null;
  ai_summary: string | null;
  suggested_reply_tone: string | null;
  assigned_to_id: string | null;
  assigned_to_name: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  /** True when the last AI draft generation attempt failed for this thread */
  draft_generation_failed: boolean;
  /** Phase 3: triage tier */
  tier: ThreadTier;
  /** Phase 3: which engine produced the categorization. */
  categorization_source: CategorizationSource;
  /** Phase 3: ISO timestamp when this thread was auto-sent (T1 only), or null. */
  auto_sent_at: string | null;
  /** Save-to-folder state */
  is_saved: boolean;
  saved_folder: string | null;
}

// ── Tier rules (admin) ────────────────────────────────────────────────────────
export interface TierRule {
  id: string;
  category: EmailCategory;
  t1_eligible: boolean;
  t1_min_confidence: number;
  updated_at: string;
  updated_by_id: string | null;
  updated_by_name: string | null;
}

export interface TierRuleUpdate {
  t1_eligible?: boolean;
  t1_min_confidence?: number;
}

export interface BulkActionParams {
  user_id?: string | null;
}

export interface BulkActionRequest {
  thread_ids: string[];
  action: "close" | "assign" | "recategorize";
  params?: BulkActionParams;
}

export interface BulkActionResponse {
  succeeded: number;
  failed: number;
  errors: string[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ── Draft ─────────────────────────────────────────────────────────────────────
export interface DraftResponse {
  id: string;
  thread_id: string;
  body_text: string;
  status: DraftStatus;
  reviewed_by_id: string | null;
  created_at: string;
  reviewed_at: string | null;
  version: number;
  original_body_text: string | null;
  ai_model: string | null;
  ai_prompt_tokens: number | null;
  ai_completion_tokens: number | null;
  knowledge_entry_ids: string[] | null;
  rejection_reason: string | null;
  /** Number of send attempts made for this draft (0 until first send attempt). */
  send_attempts: number;
  /** Server-assigned or client-supplied idempotency key for the last send attempt. */
  send_idempotency_key: string | null;
}

// ── System Status ─────────────────────────────────────────────────────────────
export interface SystemStatus {
  shadow_mode: boolean;
  last_successful_poll_at: string | null;
  poller_healthy: boolean;
  anthropic_reachable: boolean;
}

// ── Escalation ────────────────────────────────────────────────────────────────
export interface Escalation {
  id: string;
  thread_id: string;
  reason: string;
  severity: EscalationSeverity;
  status: EscalationStatus;
  assigned_to_id: string | null;
  created_at: string;
  resolved_at: string | null;
  resolved_by_id: string | null;
  resolution_notes: string | null;
  thread_subject: string | null;
  thread_client_email: string | null;
}

// ── Knowledge ─────────────────────────────────────────────────────────────────
export interface KnowledgeEntry {
  id: string;
  title: string;
  content: string;
  category: string | null;
  is_active: boolean;
  tags: string[] | null;
  entry_type: EntryType;
  usage_count: number;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export interface DashboardStats {
  totals: {
    threads: number;
    pending_escalations: number;
  };
  threads_by_status: Record<string, number>;
  threads_by_category: Record<string, number>;
  /** Phase 3: thread counts per triage tier. May be absent on older deployments. */
  threads_by_tier?: Record<string, number>;
  escalations_by_status: Record<string, number>;
  escalations_by_severity: Record<string, number>;
  last_24h: {
    new_threads: number;
    new_escalations: number;
  };
  drafts: {
    pending_review: number;
    sent_today: number;
  };
  knowledge_entries_active: number;
  ai_usage: {
    calls_this_month: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost_usd: number;
  };
  generated_at: string;
}

// ── Activity feed ─────────────────────────────────────────────────────────────
export interface ActivityItem {
  id: string;
  action: string;
  description: string;
  actor: string;
  entity_type: string;
  entity_id: string | null;
  created_at: string;
}

// ── Admin integrations ────────────────────────────────────────────────────────
export type IntegrationStatus = "healthy" | "degraded" | "down" | "not_configured";

export interface IntegrationItem {
  id: string;
  name: string;
  status: IntegrationStatus;
  latency_ms: number | null;
  last_success_at: string | null;
  last_error: string | null;
  config: Record<string, unknown>;
}

export interface IntegrationsResponse {
  overall_status: IntegrationStatus;
  shadow_mode: boolean;
  checked_at: string;
  items: IntegrationItem[];
}

// ── System settings (admin) ───────────────────────────────────────────────────
export interface SystemSetting {
  key: string;
  value: string;
  updated_at: string;
  updated_by_id: string | null;
  updated_by_name: string | null;
}

// ── Audit log ─────────────────────────────────────────────────────────────────
export interface AuditLogEntry {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown> | null;
  user_id: string | null;
  user_name: string | null;
  user_email: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface AuditLogResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
}

// ── API Error ─────────────────────────────────────────────────────────────────
export interface ApiErrorResponse {
  detail: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}
