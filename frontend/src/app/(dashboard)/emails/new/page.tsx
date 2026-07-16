"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Compose is a global overlay (opened via the New Email button), not a route,
 * so `/emails/new` no longer renders anything. This page exists only so an old
 * bookmark or stale link to `/emails/new` redirects to the inbox instead of
 * falling through to the `/emails/[threadId]` dynamic route (which would try to
 * load a thread with id "new"). Redirect happens client-side because this app
 * gates auth and routes on the client — a server `redirect()` wouldn't fire.
 */
export default function EmailsNewRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/emails");
  }, [router]);
  return null;
}
