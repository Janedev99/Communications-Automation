"use client";

import Link from "next/link";
import useSWRInfinite from "swr/infinite";
import { ArrowLeft, Sparkles } from "lucide-react";
import { swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { ReleaseNoteCard } from "@/components/whats-new/release-note-card";
import type { ReleaseArchiveResponse } from "@/lib/types";

const PAGE_SIZE = 20;

/** Build the key for page `index` given the previous page's data.
 *  Cursor pagination: page N+1 fetches with ?cursor=<page N's next_cursor>. */
function getKey(
  index: number,
  previousPageData: ReleaseArchiveResponse | null,
): string | null {
  // First page — no cursor.
  if (index === 0) return `/api/v1/releases/archive?limit=${PAGE_SIZE}`;
  // No more pages.
  if (!previousPageData?.next_cursor) return null;
  return `/api/v1/releases/archive?limit=${PAGE_SIZE}&cursor=${previousPageData.next_cursor}`;
}

export default function WhatsNewArchivePage() {
  const { data, error, size, setSize, isLoading, mutate, isValidating } =
    useSWRInfinite<ReleaseArchiveResponse>(getKey, swrFetcher, {
      revalidateOnFocus: false,
      revalidateFirstPage: false,
    });

  if (error) {
    return (
      <ErrorState
        title="Failed to load release archive"
        description="Could not retrieve release notes."
        onRetry={mutate}
      />
    );
  }

  const pages = data ?? [];
  const items = pages.flatMap((p) => p.items);
  const lastPage = pages[pages.length - 1];
  const hasMore = !!lastPage?.next_cursor;
  const isLoadingMore = isValidating && pages.length === size;
  const showFirstPageSkeleton = isLoading && items.length === 0;
  const showEmpty = !isLoading && items.length === 0;

  return (
    <div className="space-y-6">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Dashboard
      </Link>

      <PageHeader
        title="What's New"
        subtitle="A reverse-chronological archive of every release announcement."
      />

      {showFirstPageSkeleton && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-48 bg-muted animate-pulse rounded-2xl" />
          ))}
        </div>
      )}

      {showEmpty && (
        <div className="bg-card border border-border rounded-2xl p-12 text-center">
          <Sparkles
            className="w-10 h-10 text-muted-foreground mx-auto mb-3"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <h2 className="text-lg font-semibold text-foreground">
            No release notes yet
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            New releases will appear here as they ship.
          </p>
        </div>
      )}

      {items.length > 0 && (
        <div className="space-y-4">
          {items.map((release) => (
            <ReleaseNoteCard
              key={release.id}
              title={release.title}
              summary={release.summary}
              highlights={release.highlights}
              body={release.body}
              publishedAt={release.published_at}
            />
          ))}
        </div>
      )}

      {hasMore && (
        <div className="flex justify-center pt-2">
          <Button
            variant="outline"
            onClick={() => setSize(size + 1)}
            disabled={isLoadingMore}
          >
            {isLoadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}
