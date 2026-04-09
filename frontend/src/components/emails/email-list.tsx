"use client";

import { useRouter } from "next/navigation";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Mail } from "lucide-react";
import { ThreadStatusBadge } from "./thread-status-badge";
import { CategoryBadge } from "./category-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { relativeTime } from "@/lib/utils";
import type { EmailThreadListItem } from "@/lib/types";

interface EmailListProps {
  threads: EmailThreadListItem[];
}

export function EmailList({ threads }: EmailListProps) {
  const router = useRouter();

  if (threads.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <EmptyState
          icon={Mail}
          title="No threads found"
          description="Try adjusting your filters"
        />
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-gray-50/80 hover:bg-gray-50/80">
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              Subject
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[180px]">
              Client
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[140px]">
              Category
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[140px]">
              Status
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[80px] text-center">
              Msgs
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[120px]">
              Updated
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {threads.map((thread) => (
            <TableRow
              key={thread.id}
              className="hover:bg-gray-50/60 cursor-pointer transition-colors border-b border-gray-100"
              tabIndex={0}
              onClick={() => router.push(`/emails/${thread.id}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  router.push(`/emails/${thread.id}`);
                }
              }}
            >
              <TableCell className="px-4 py-3">
                <span className="text-sm font-medium text-gray-800 truncate block max-w-[300px]">
                  {thread.subject}
                </span>
              </TableCell>
              <TableCell className="px-4 py-3 w-[180px]">
                <span className="text-sm text-gray-600 truncate block">
                  {thread.client_name ?? thread.client_email}
                </span>
              </TableCell>
              <TableCell className="px-4 py-3 w-[140px]">
                <CategoryBadge category={thread.category} />
              </TableCell>
              <TableCell className="px-4 py-3 w-[140px]">
                <ThreadStatusBadge status={thread.status} />
              </TableCell>
              <TableCell className="px-4 py-3 w-[80px] text-center text-sm text-gray-500">
                {thread.message_count}
              </TableCell>
              <TableCell className="px-4 py-3 w-[120px]">
                <span className="text-xs text-gray-400">
                  {relativeTime(thread.updated_at)}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
