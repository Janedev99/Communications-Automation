"use client";

import useSWR from "swr";
import { api, swrFetcher } from "@/lib/api";
import type { LatestUnreadResponse } from "@/lib/types";

const KEY = "/api/v1/releases/latest-unread";

export function useWhatsNew() {
  const { data, error, isLoading, mutate } = useSWR<LatestUnreadResponse | null>(
    KEY,
    swrFetcher,
    {
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    },
  );

  const dismiss = async (releaseId: string, dontShowAgain: boolean) => {
    await api.put(`/api/v1/releases/${releaseId}/dismissal`, {
      dont_show_again: dontShowAgain,
    });
    await mutate(null, false);
  };

  const setHideForever = async (hide: boolean) => {
    await api.patch("/api/v1/auth/me/preferences", {
      hide_releases_forever: hide,
    });
    await mutate(null, false);
  };

  return {
    release: data ?? null,
    isLoading,
    isError: !!error,
    dismiss,
    setHideForever,
  };
}
