/** @type {import('next').NextConfig} */

// Single canonical env var for the backend API base URL.
// NEXT_PUBLIC_API_BASE_URL was a legacy alias — it has been removed.
// All consumers (api.ts, middleware, CSP) now read NEXT_PUBLIC_API_URL.
const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

const nextConfig = {
  output: "standalone",

  async headers() {
    const csp = [
      "default-src 'self'",
      `connect-src 'self' ${apiBaseUrl}`,
      "img-src 'self' data: blob:",
      "style-src 'self' 'unsafe-inline'",
      // 'unsafe-eval' required by Next.js dev mode; acceptable for SPA apps
      "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
      "font-src 'self' data:",
      // Modern replacement for X-Frame-Options: DENY
      "frame-ancestors 'none'",
    ].join("; ");

    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          {
            key: "Content-Security-Policy",
            value: csp,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
