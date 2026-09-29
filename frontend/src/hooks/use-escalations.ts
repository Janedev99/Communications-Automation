"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { Escalation, PaginatedResponse } from "@/lib/types";

interface UseEscalationsParams {
  status?: string;
  severity?: string;
  /** Server-side "open" view: pending + acknowledged, minus anything the
   *  to-do reset ("Start clean") cleared. */
  active?: boolean;
  /** With `active`, also include escalations hidden by the reset. */
  includeHidden?: boolean;
  page?: number;
  page_size?: number;
}

export function useEscalations(params: UseEscalationsParams = {}) {
  const { page = 1, page_size = 25, status, severity, active, includeHidden } = params;

  const searchParams = new URLSearchParams();
  searchParams.set("page", String(page));
  searchParams.set("page_size", String(page_size));
  if (status) searchParams.set("status", status);
  if (severity) searchParams.set("severity", severity);
  if (active) searchParams.set("active", "true");
  if (active && includeHidden) searchParams.set("include_hidden", "true");

  const key = `/api/v1/escalations?${searchParams.toString()}`;

  const { data, error, isLoading, mutate } =
    useSWR<PaginatedResponse<Escalation>>(key, swrFetcher, {
      refreshInterval: 15_000,
    });

  return {
    data,
    escalations: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError: !!error,
    mutate,
  };
}
