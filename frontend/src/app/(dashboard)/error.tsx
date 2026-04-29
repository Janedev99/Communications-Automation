"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function DashboardError({ error, reset }: ErrorProps) {
  useEffect(() => {
    // Log to an error reporting service in production
    console.error("Dashboard error boundary caught:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center py-24 px-6 text-center">
      <AlertTriangle
        className="w-10 h-10 text-destructive/70 mb-3"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <h2 className="text-sm font-semibold text-foreground">Something went wrong</h2>
      <p className="text-sm text-muted-foreground mt-1 max-w-sm">
        An unexpected error occurred. You can try refreshing the page or clicking the button below.
      </p>
      <Button variant="outline" className="mt-4" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
