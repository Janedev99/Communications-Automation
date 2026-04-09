"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { DraftResponse } from "@/lib/types";

/**
 * Fetches the latest draft for a thread.
 *
 * Backend returns a LIST at GET /emails/{thread_id}/drafts (all drafts,
 * newest first).  We pick the first element as the "current" draft.
 * When no drafts exist the backend returns an empty array, not 404.
 */
export function useThreadDraft(threadId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<DraftResponse[]>(
    threadId ? `/api/v1/emails/${threadId}/drafts` : null,
    swrFetcher,
    { shouldRetryOnError: false, refreshInterval: 15_000 }
  );

  // Backend returns newest-first; pick index 0 as the active draft
  const draft = data && data.length > 0 ? data[0] : undefined;

  return {
    draft,
    isLoading,
    // 404 means thread itself not found — a genuine error
    isError: !!error && error?.status !== 404,
    hasDraft: !!draft,
    mutate,
  };
}
