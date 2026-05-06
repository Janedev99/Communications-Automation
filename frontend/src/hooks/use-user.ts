"use client";

import useSWR, { mutate as globalMutate } from "swr";
import { useRouter } from "next/navigation";
import { api, clearCsrfToken, swrFetcher } from "@/lib/api";
import type { MeResponse } from "@/lib/types";

const ME_KEY = "/api/v1/auth/me";

export function useUser() {
  const router = useRouter();
  const { data, error, isLoading, mutate } = useSWR<MeResponse>(
    ME_KEY,
    swrFetcher,
    {
      // Don't retry on 401
      shouldRetryOnError: false,
      onError: (err) => {
        if (err?.status === 401) {
          router.push("/login");
        }
      },
    }
  );

  const logout = async () => {
    try {
      // Use the api wrapper so the X-CSRF-Token header is sent automatically.
      // Without it the backend's require_csrf dependency returns 403 and the
      // server-side session is never invalidated.
      await api.post("/api/v1/auth/logout");
    } catch {
      // Ignore errors — redirect to login regardless so client state is cleared.
    }
    // Clear the stored CSRF token so the next login can replace it cleanly.
    clearCsrfToken();
    // Clear the SWR cache
    await globalMutate(ME_KEY, undefined, false);
    router.push("/login");
  };

  return {
    user: data,
    isLoading,
    isError: !!error,
    isAdmin: data?.role === "admin",
    mutate,
    logout,
  };
}
