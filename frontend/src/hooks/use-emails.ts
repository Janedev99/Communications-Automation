"use client";

import useSWR from "swr";
import { api, swrFetcher } from "@/lib/api";
import type {
  BulkActionRequest,
  BulkActionResponse,
  EmailThread,
  EmailThreadListItem,
  OutlookFolder,
  PaginatedResponse,
  SavedFolder,
  SavedMessageItem,
} from "@/lib/types";

/** Sort axes accepted by GET /api/v1/emails. Keep in sync with backend. */
export type ThreadSort =
  | "updated_desc"
  | "updated_asc"
  | "subject_asc"
  | "subject_desc"
  | "client_asc"
  | "client_desc";

/** Sort axes accepted by GET /api/v1/emails/saved/messages. */
export type SavedMessageSort =
  | "saved_desc"
  | "saved_asc"
  | "subject_asc"
  | "subject_desc"
  | "client_asc"
  | "client_desc";

interface UseEmailsParams {
  status?: string;
  category?: string;
  /** Phase 3: filter by triage tier */
  tier?: string;
  client_email?: string;
  assigned_to?: string;
  /** When true, only saved threads. When false, only un-saved. Omit for both. */
  saved?: boolean;
  /** When true, only threads containing a sent (outbound) message — the Sent folder. */
  sentOnly?: boolean;
  /** Filter by saved folder. Empty string targets the unfiled bucket. */
  folder?: string;
  /** Sort axis. Defaults to most-recently-updated first server-side. */
  sort?: ThreadSort;
  search?: string;
  page?: number;
  page_size?: number;
}

export function useEmails(params: UseEmailsParams = {}) {
  const {
    page = 1,
    page_size = 25,
    status,
    category,
    tier,
    client_email,
    assigned_to,
    saved,
    sentOnly,
    folder,
    sort,
    search,
  } = params;

  const searchParams = new URLSearchParams();
  searchParams.set("page", String(page));
  searchParams.set("page_size", String(page_size));

  // When a search term is present, use the dedicated /search endpoint
  const isSearching = !!search?.trim();

  if (isSearching) {
    searchParams.set("q", search!.trim());
  } else {
    if (status) searchParams.set("status", status);
    if (category) searchParams.set("category", category);
    if (tier) searchParams.set("tier", tier);
    if (client_email) searchParams.set("client_email", client_email);
    if (assigned_to) searchParams.set("assigned_to", assigned_to);
    if (saved !== undefined) searchParams.set("saved", String(saved));
    if (sentOnly) searchParams.set("sent_only", "true");
    if (folder !== undefined) searchParams.set("folder", folder);
    if (sort) searchParams.set("sort", sort);
  }

  const base = isSearching ? "/api/v1/emails/search" : "/api/v1/emails";
  const key = `${base}?${searchParams.toString()}`;

  const { data, error, isLoading, mutate } =
    useSWR<PaginatedResponse<EmailThreadListItem>>(key, swrFetcher, {
      refreshInterval: isSearching ? 0 : 15_000, // no auto-refresh during search
    });

  return {
    data,
    threads: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError: !!error,
    mutate,
  };
}

// ── Mutation helpers ──────────────────────────────────────────────────────────

export function assignThread(threadId: string, userId: string | null): Promise<EmailThread> {
  return api.put<EmailThread>(`/api/v1/emails/${threadId}/assign`, { user_id: userId });
}

export function changeThreadStatus(threadId: string, newStatus: string): Promise<EmailThread> {
  return api.put<EmailThread>(`/api/v1/emails/${threadId}/status`, { status: newStatus });
}

/**
 * Move every inbound message in the thread to Outlook's Deleted Items
 * folder via Microsoft Graph, and park the local thread in
 * `EmailStatus.deleted`. Outbound (sent) messages are NOT moved.
 *
 * Recoverable: the messages stay in Deleted Items until Outlook itself
 * purges them. Idempotent — calling on an already-deleted thread is a
 * no-op (server returns the thread as-is).
 */
export function trashThread(threadId: string): Promise<EmailThread> {
  return api.post<EmailThread>(`/api/v1/emails/${threadId}/trash`, {});
}

/**
 * Move every inbound message to Outlook's Junk Email folder and park the
 * thread in `EmailStatus.spam`. Outlook's junk filter learns from this,
 * so future emails from the same sender are auto-routed to junk and
 * never reach this app's poller.
 */
export function markThreadSpam(threadId: string): Promise<EmailThread> {
  return api.post<EmailThread>(`/api/v1/emails/${threadId}/spam`, {});
}

export interface AddThreadToKbBody {
  /** Optional title override (default: thread subject with Re:/Fwd: stripped). */
  title?: string;
  /** Optional category override (default: thread.category value). */
  category?: string;
  /** Optional tags override (default: ["from_email", "<thread category>"]). */
  tags?: string[];
}

export interface KnowledgeEntryRef {
  id: string;
  title: string;
  category: string | null;
}

/**
 * Create a KnowledgeEntry from this thread's latest Q&A exchange. The
 * server derives sensible defaults (title from subject, content from
 * latest inbound + outbound bodies, category from thread.category); the
 * UI can override any of those via the body. Returns the new entry so
 * the caller can deep-link to it.
 */
export function addThreadToKnowledgeBase(
  threadId: string,
  body: AddThreadToKbBody = {},
): Promise<KnowledgeEntryRef> {
  return api.post<KnowledgeEntryRef>(
    `/api/v1/emails/${threadId}/add-to-knowledge-base`,
    body,
  );
}

export function bulkAction(body: BulkActionRequest): Promise<BulkActionResponse> {
  return api.post<BulkActionResponse>("/api/v1/emails/bulk", body);
}

// ── Compose: AI "write this email for me" ──────────────────────────────────────

export interface ComposeDraftRequest {
  /** Plain-language instruction for what the email should say. */
  instruction: string;
  /** Optional recipient address, used as greeting context. */
  recipient?: string;
  /** Optional subject the AI should refine or use as a starting point. */
  subject_hint?: string;
}

export interface ComposeDraftResult {
  subject: string;
  body: string;
}

/**
 * Ask the AI to draft a brand-new outbound email from a free-text instruction.
 * Returns an editable subject + body — nothing is sent. The signature is NOT
 * included (the send path appends it). Surfaces the backend's 409 message
 * verbatim (e.g. provider unconfigured / budget exceeded) via ApiError.
 */
export function composeDraft(body: ComposeDraftRequest): Promise<ComposeDraftResult> {
  return api.post<ComposeDraftResult>("/api/v1/emails/compose/draft", body);
}

// ── Save / unsave thread ──────────────────────────────────────────────────────

export interface SaveThreadBody {
  folder?: string | null;
  note?: string | null;
}

export function saveThread(threadId: string, body: SaveThreadBody): Promise<EmailThread> {
  return api.post<EmailThread>(`/api/v1/emails/${threadId}/save`, body);
}

export function unsaveThread(threadId: string): Promise<EmailThread> {
  return api.post<EmailThread>(`/api/v1/emails/${threadId}/unsave`, {});
}

/** One level of Outlook folders. Omit parentId for the top level; pass a
 *  folder id to fetch its children (lazy expand). `custom` hides Outlook's
 *  built-in system folders and surfaces Jane's own folder tree. */
export function useOutlookFolders(parentId?: string, custom = false) {
  const sp = new URLSearchParams();
  if (parentId) sp.set("parent", parentId);
  if (custom) sp.set("custom", "true");
  const qs = sp.toString();
  const key = qs ? `/api/v1/mailbox/folders?${qs}` : "/api/v1/mailbox/folders";
  const { data, error, isLoading } = useSWR<{ folders: OutlookFolder[] }>(
    key,
    swrFetcher,
  );
  return { folders: data?.folders ?? [], isLoading, isError: !!error };
}

export function useSavedFolders() {
  const { data, error, isLoading, mutate } = useSWR<SavedFolder[]>(
    "/api/v1/emails/saved/folders",
    swrFetcher,
    { refreshInterval: 30_000 },
  );
  return {
    folders: data ?? [],
    isLoading,
    isError: !!error,
    mutate,
  };
}

// ── Save / unsave individual message ──────────────────────────────────────────

export function saveMessage(
  threadId: string,
  messageId: string,
  body: SaveThreadBody,
): Promise<EmailThread> {
  return api.post<EmailThread>(
    `/api/v1/emails/${threadId}/messages/${messageId}/save`,
    body,
  );
}

export function unsaveMessage(threadId: string, messageId: string): Promise<EmailThread> {
  return api.post<EmailThread>(
    `/api/v1/emails/${threadId}/messages/${messageId}/unsave`,
    {},
  );
}

interface UseSavedMessagesParams {
  /** Filter by folder. Empty string = unfiled bucket. Undefined = all. */
  folder?: string;
  /** Sort axis. Defaults to most-recently-saved first server-side. */
  sort?: SavedMessageSort;
}

export function useSavedMessages(params: UseSavedMessagesParams = {}) {
  const sp = new URLSearchParams();
  if (params.folder !== undefined) sp.set("folder", params.folder);
  if (params.sort) sp.set("sort", params.sort);
  const qs = sp.toString();
  const key = `/api/v1/emails/saved/messages${qs ? `?${qs}` : ""}`;
  const { data, error, isLoading, mutate } = useSWR<SavedMessageItem[]>(
    key,
    swrFetcher,
    { refreshInterval: 30_000 },
  );
  return {
    messages: data ?? [],
    isLoading,
    isError: !!error,
    mutate,
  };
}

/**
 * Delete a saved folder. Backend refuses with 409 if the folder still
 * has any saved threads or messages — caller should surface the error
 * message to the user as a "move items first" prompt.
 */
export function deleteSavedFolder(folder: string): Promise<void> {
  return api.delete<void>(
    `/api/v1/emails/saved/folders/${encodeURIComponent(folder)}`,
  );
}
