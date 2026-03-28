"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { DashboardStats } from "@/lib/types";

export function useDashboard() {
  const { data, error, isLoading, mutate } = useSWR<DashboardStats>(
    "/api/v1/dashboard/stats",
    swrFetcher,
    { refreshInterval: 30_000 }
  );

  return {
    stats: data,
    isLoading,
    isError: !!error,
    mutate,
  };
}
