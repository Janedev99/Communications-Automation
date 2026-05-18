"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { EmailCategory } from "@/lib/types";

/**
 * Response shape for GET /api/v1/feedback/preview.
 * Mirrors backend `FeedbackPreviewResponse`.
 */
export interface FeedbackExample {
  source: "approved" | "saved";
  body: string;
  occurred_at: string;
}

export interface FeedbackNegative {
  reason: string;
  occurred_at: string;
}

export interface FeedbackPreview {
  category: EmailCategory;
  positive: FeedbackExample[];
  curated: FeedbackExample[];
  negative: FeedbackNegative[];
  counts: {
    positive: number;
    curated: number;
    negative: number;
  };
}

/**
 * Fetches the feedback context the AI would see for a given category.
 *
 * Pass `null` to defer the request (e.g. when the draft hasn't loaded yet).
 * Same data shape powers both the draft-card indicator (call with the
 * thread's category) and the admin debug page (call with the operator's
 * selection).
 */
export function useFeedbackPreview(category: EmailCategory | null) {
  const { data, error, isLoading, mutate } = useSWR<FeedbackPreview>(
    category ? `/api/v1/feedback/preview?category=${category}` : null,
    swrFetcher,
    {
      shouldRetryOnError: false,
      // Feedback data shifts when staff approves/rejects elsewhere in the
      // app; ~60s keeps the side panel reasonably fresh without thrash.
      refreshInterval: 60_000,
    }
  );

  return {
    preview: data,
    isLoading,
    isError: !!error,
    mutate,
  };
}
