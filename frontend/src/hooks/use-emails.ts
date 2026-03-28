"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { EmailThreadListItem, PaginatedResponse } from "@/lib/types";

interface UseEmailsParams {
  status?: string;
  category?: string;
  client_email?: string;
  page?: number;
  page_size?: number;
}

export function useEmails(params: UseEmailsParams = {}) {
  const { page = 1, page_size = 25, status, category, client_email } = params;

  const searchParams = new URLSearchParams();
  searchParams.set("page", String(page));
  searchParams.set("page_size", String(page_size));
  if (status) searchParams.set("status", status);
  if (category) searchParams.set("category", category);
  if (client_email) searchParams.set("client_email", client_email);

  const key = `/api/v1/emails?${searchParams.toString()}`;

  const { data, error, isLoading, mutate } =
    useSWR<PaginatedResponse<EmailThreadListItem>>(key, swrFetcher);

  return {
    data,
    threads: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError: !!error,
    mutate,
  };
}
