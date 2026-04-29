import { Skeleton } from "@/components/ui/skeleton";

export function StatCardSkeleton() {
  return (
    <div className="bg-card rounded-xl border border-border p-5">
      <Skeleton className="h-3 w-24 mb-3" />
      <Skeleton className="h-8 w-16 mb-2" />
      <Skeleton className="h-2.5 w-20" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <div className="px-4 py-3 bg-muted/80 border-b border-border">
        <Skeleton className="h-3 w-full" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-4 py-3 border-b border-border/60 last:border-b-0 flex items-center gap-4">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function ThreadDetailSkeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] h-full">
      {/* Left panel */}
      <div className="p-6 space-y-4">
        <div className="space-y-2 pb-4 border-b border-border">
          <Skeleton className="h-5 w-3/4" />
          <div className="flex gap-2 mt-2">
            <Skeleton className="h-5 w-24 rounded-full" />
            <Skeleton className="h-5 w-24 rounded-full" />
          </div>
        </div>
        <div className="space-y-4">
          <Skeleton className="h-24 w-3/4 rounded-xl" />
          <Skeleton className="h-20 w-3/4 rounded-xl ml-auto" />
          <Skeleton className="h-28 w-3/4 rounded-xl" />
        </div>
      </div>
      {/* Right panel */}
      <div className="border-l border-border p-5 space-y-3">
        <Skeleton className="h-4 w-32 mb-4" />
        <Skeleton className="h-48 w-full rounded-md" />
        <div className="flex gap-2 pt-4">
          <Skeleton className="h-9 w-24 rounded-md" />
          <Skeleton className="h-9 w-20 rounded-md" />
        </div>
      </div>
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <StatCardSkeleton key={i} />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TableSkeleton rows={5} />
        <TableSkeleton rows={5} />
      </div>
    </div>
  );
}
