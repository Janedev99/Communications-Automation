"use client";

import useSWR, { mutate as globalMutate } from "swr";
import { useRouter } from "next/navigation";
import { swrFetcher } from "@/lib/api";
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
      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/auth/logout`,
        { method: "POST", credentials: "include" }
      );
    } catch {
      // ignore errors — we'll redirect regardless
    }
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
