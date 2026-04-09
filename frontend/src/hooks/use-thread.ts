"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { EmailThread } from "@/lib/types";

export function useThread(threadId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<EmailThread>(
    threadId ? `/api/v1/emails/${threadId}` : null,
    swrFetcher,
    { refreshInterval: 15_000 }
  );

  return {
    thread: data,
    isLoading,
    isError: !!error,
    mutate,
  };
}
