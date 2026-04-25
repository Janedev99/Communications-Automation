"use client";

import useSWR from "swr";
import { api, swrFetcher } from "@/lib/api";
import type {
  BulkActionRequest,
  BulkActionResponse,
  EmailThread,
  EmailThreadListItem,
  PaginatedResponse,
} from "@/lib/types";

interface UseEmailsParams {
  status?: string;
  category?: string;
  /** Phase 3: filter by triage tier */
  tier?: string;
  client_email?: string;
  assigned_to?: string;
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
