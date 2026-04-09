"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { Escalation } from "@/lib/types";

/**
 * Fetches the latest active (non-resolved) escalation for a thread.
 * Returns null if the thread has no active escalation.
 * Backend returns null (not 404) when no escalation exists.
 */
export function useThreadEscalation(threadId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<Escalation | null>(
    threadId ? `/api/v1/emails/${threadId}/escalation` : null,
    swrFetcher,
    { refreshInterval: 15_000, shouldRetryOnError: false }
  );

  return {
    escalation: data ?? null,
    isLoading,
    isError: !!error && error?.status !== 404,
    mutate,
  };
}
