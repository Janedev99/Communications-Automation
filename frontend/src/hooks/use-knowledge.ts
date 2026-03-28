"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { KnowledgeEntry, PaginatedResponse } from "@/lib/types";

interface UseKnowledgeParams {
  category?: string;
  entry_type?: string;
  is_active?: boolean;
  page?: number;
  page_size?: number;
}

export function useKnowledge(params: UseKnowledgeParams = {}) {
  const { page = 1, page_size = 25, category, entry_type, is_active } = params;

  const searchParams = new URLSearchParams();
  searchParams.set("page", String(page));
  searchParams.set("page_size", String(page_size));
  if (category) searchParams.set("category", category);
  if (entry_type) searchParams.set("entry_type", entry_type);
  if (is_active !== undefined) searchParams.set("is_active", String(is_active));

  const key = `/api/v1/knowledge?${searchParams.toString()}`;

  const { data, error, isLoading, mutate } =
    useSWR<PaginatedResponse<KnowledgeEntry>>(key, swrFetcher);

  return {
    data,
    entries: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError: !!error,
    mutate,
  };
}
