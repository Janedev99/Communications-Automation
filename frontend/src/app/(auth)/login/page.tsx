"use client";

import { useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlphaBadge } from "@/components/ui/alpha-badge";
import { api, setCsrfToken } from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await api.post<LoginResponse>("/api/v1/auth/login", {
        email,
        password,
      });
      // Cross-origin SPAs cannot read the csrf_token cookie via document.cookie
      // (different domain). Persist the token from the response body so it can
      // be echoed back as X-CSRF-Token on subsequent state-changing requests.
      setCsrfToken(res.csrf_token);
      router.push("/");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Invalid email or password.";
      setError(message === "Unauthorized" ? "Invalid email or password." : message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4 relative overflow-hidden">
      {/* Subtle radial accent */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/[0.07] via-transparent to-transparent"
      />

      <div className="relative w-full max-w-sm">
        {/* Brand mark — Point Profit logo (white-bg JPG; wrapper keeps it on
            white in both light and dark mode for a consistent presentation) */}
        <div className="flex flex-col items-center mb-6">
          <div className="bg-white rounded-lg px-4 py-3 shadow-sm ring-1 ring-black/5 dark:ring-white/10">
            <Image
              src="/pointprofit-logo.jpg"
              alt="Point Profit"
              width={280}
              height={70}
              priority
              className="h-auto w-[240px]"
            />
          </div>
          <div className="flex items-center gap-2 mt-4">
            <p className="text-sm text-muted-foreground">Staff Portal</p>
            <AlphaBadge />
          </div>
        </div>

        <div className="bg-card rounded-xl border border-border shadow-sm p-7">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Email address
              </label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@schilcpa.com"
                className="h-10"
                disabled={loading}
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Password
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-10"
                disabled={loading}
              />
            </div>

            <Button
              type="submit"
              size="lg"
              className="w-full mt-2"
              disabled={loading}
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                  Signing in...
                </>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>

          {error && (
            <div
              role="alert"
              className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2"
            >
              <p className="text-sm text-destructive text-center">{error}</p>
            </div>
          )}
        </div>

        <p className="text-xs text-muted-foreground text-center mt-6">
          Internal use only · {new Date().getFullYear()} Point Profit
        </p>
      </div>
    </div>
  );
}
