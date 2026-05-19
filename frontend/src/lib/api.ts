/**
 * Thin fetch wrapper with:
 * - credentials: "include" on every request (HttpOnly cookie auth)
 * - JSON serialization/deserialization
 * - Typed ApiError on non-OK responses
 * - 401 redirect to /login
 * - CSRF: reads csrf_token from localStorage (set at login) and echoes as
 *   X-CSRF-Token on all state-changing requests (POST/PUT/PATCH/DELETE).
 *   localStorage is required for cross-origin deploys (e.g., Railway) where
 *   the API cookie is on a different domain than the SPA, so document.cookie
 *   cannot read it. Falls back to the cookie for same-origin deploys.
 */
import { ApiError } from "./types";

const CSRF_STORAGE_KEY = "csrf_token";

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

/**
 * Get the CSRF token to echo on state-changing requests.
 * Cross-origin deploys must use localStorage (set by the login page) since
 * document.cookie can't read the API's csrf_token cookie. Same-origin deploys
 * fall back to the cookie automatically.
 */
function getCsrfToken(): string | null {
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem(CSRF_STORAGE_KEY);
    if (stored) return stored;
  }
  return getCookie("csrf_token");
}

/** Persist the CSRF token after login. Called by the login page. */
export function setCsrfToken(token: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(CSRF_STORAGE_KEY, token);
  }
}

/** Clear the stored CSRF token (called on logout / session expiry). */
export function clearCsrfToken(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(CSRF_STORAGE_KEY);
  }
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

  // CSRF — echo the token (from localStorage if set at login, else cookie) as a header
  if (CSRF_METHODS.has(method)) {
    const csrfToken = getCsrfToken();
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
    // Session is gone — clear the stored CSRF too so the next login can replace it.
    clearCsrfToken();
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
      clearCsrfToken();
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


/**
 * Fetch a binary response from the API and trigger a browser download.
 *
 * Uses the same credentials/CSRF/auth handling as `request()` but consumes
 * the body as a Blob and saves it via an <a href=URL.createObjectURL(...)>
 * click. Filename comes from the server's Content-Disposition header (RFC
 * 5987 UTF-8 encoded form is preferred when present); falls back to the
 * caller-supplied default. Throws ApiError on non-OK responses.
 */
export async function downloadBinary(
  path: string,
  fallbackFilename: string,
): Promise<void> {
  const url = `${getBaseUrl()}${path}`;
  const res = await fetch(url, {
    method: "GET",
    credentials: "include",
  });

  if (res.status === 401) {
    clearCsrfToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Unauthorized");
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // server didn't return JSON — keep generic message
    }
    throw new ApiError(res.status, message);
  }

  // Parse RFC 5987 filename*=UTF-8''<percent-encoded> first; fall back to
  // filename="..." then to the caller's default.
  const cd = res.headers.get("Content-Disposition") ?? "";
  let filename = fallbackFilename;
  const utf8Match = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      filename = decodeURIComponent(utf8Match[1]);
    } catch {
      // bad encoding — keep fallback
    }
  } else {
    const plainMatch = cd.match(/filename="([^"]+)"/i) ?? cd.match(/filename=([^;]+)/i);
    if (plainMatch) filename = plainMatch[1].trim();
  }

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Defer revoke so the click handler has time to dispatch the download
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}
