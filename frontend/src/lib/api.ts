/**
 * Thin fetch wrapper with:
 * - credentials: "include" on every request (HttpOnly cookie auth)
 * - JSON serialization/deserialization
 * - Typed ApiError on non-OK responses
 * - 401 redirect to /login
 * - CSRF double-submit: reads csrf_token cookie and echoes as X-CSRF-Token on
 *   all state-changing requests (POST/PUT/PATCH/DELETE)
 */
import { ApiError } from "./types";

const getBaseUrl = () =>
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

/** Read a named cookie value from document.cookie, or null if not found. */
function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

const CSRF_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function request<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  const method = (init.method ?? "GET").toUpperCase();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };

  // Don't set Content-Type for requests without a body
  if (!init.body) {
    delete headers["Content-Type"];
  }

  // CSRF double-submit — echo the non-HttpOnly csrf_token cookie as a header
  if (CSRF_METHODS.has(method)) {
    const csrfToken = getCookie("csrf_token");
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  const res = await fetch(url, {
    ...init,
    headers,
    credentials: "include",
  });

  if (res.status === 401) {
    // Redirect to login — but not if we're already there (avoids loop)
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Unauthorized");
  }

  if (res.status === 403) {
    // Force-logout on CSRF token mismatch — stale tab or session rotation
    let isCsrfError = false;
    try {
      const body = await res.clone().json();
      if (typeof body?.detail === "string" && body.detail.toLowerCase().includes("csrf")) {
        isCsrfError = true;
      }
    } catch {
      // ignore parse errors — treat non-CSRF 403 as normal error below
    }
    if (isCsrfError && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
      throw new ApiError(403, "Session expired. Please log in again.");
    }
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, message);
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path, { method: "GET" });
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "PUT",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" });
  },
};

/** SWR fetcher — pass directly as the fetcher argument */
export const swrFetcher = <T>(path: string): Promise<T> => api.get<T>(path);
