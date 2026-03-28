"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { Escalation, PaginatedResponse } from "@/lib/types";

interface UseEscalationsParams {
  status?: string;
  severity?: string;
  page?: number;
  page_size?: number;
}

export function useEscalations(params: UseEscalationsParams = {}) {
  const { page = 1, page_size = 25, status, severity } = params;

  const searchParams = new URLSearchParams();
  searchParams.set("page", String(page));
  searchParams.set("page_size", String(page_size));
  if (status) searchParams.set("status", status);
  if (severity) searchParams.set("severity", severity);

  const key = `/api/v1/escalations?${searchParams.toString()}`;

  const { data, error, isLoading, mutate } =
    useSWR<PaginatedResponse<Escalation>>(key, swrFetcher);

  return {
    data,
    escalations: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError: !!error,
    mutate,
  };
}
