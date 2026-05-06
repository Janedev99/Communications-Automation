"use client";

import useSWR from "swr";
import { api, swrFetcher } from "@/lib/api";
import type {
  BulkActionRequest,
  BulkActionResponse,
  EmailThread,
  EmailThreadListItem,
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

export function bulkAction(body: BulkActionRequest): Promise<BulkActionResponse> {
  return api.post<BulkActionResponse>("/api/v1/emails/bulk", body);
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
