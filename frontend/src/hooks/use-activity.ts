"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { ActivityItem } from "@/lib/types";

export function useActivity(limit = 20) {
  const { data, error, isLoading, mutate } = useSWR<ActivityItem[]>(
    `/api/v1/dashboard/activity?limit=${limit}`,
    swrFetcher,
    { refreshInterval: 30_000 }
  );

  return {
    items: data ?? [],
    isLoading,
    isError: !!error,
    mutate,
  };
}
