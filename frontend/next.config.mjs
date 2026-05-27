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
      // Images: own origin + data/blob, the API origin (inline cid: images are
      // streamed from there cross-origin), and any https host. The broad
      // `https:` is required so opt-in remote email images can load — the
      // tracking-pixel risk is gated in the app (remote images are blocked by
      // default behind a "Show images" toggle), not at the CSP layer. Images
      // are passive content (no script execution), so this stays low-risk.
      `img-src 'self' data: blob: https: ${apiBaseUrl}`,
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
