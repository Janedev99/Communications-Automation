"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { SystemStatus } from "@/lib/types";

export function useSystemStatus() {
  const { data, error, isLoading, mutate } = useSWR<SystemStatus>(
    "/api/v1/dashboard/system-status",
    swrFetcher,
    { refreshInterval: 30_000 }
  );

  return {
    status: data,
    isLoading,
    isError: !!error,
    mutate,
  };
}
