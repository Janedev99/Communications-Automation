"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { Users } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { ROLE_BADGE_CLASSES, ROLE_LABELS } from "@/lib/constants";
import { api } from "@/lib/api";
import { cn, formatDateShort } from "@/lib/utils";
import type { User } from "@/lib/types";

interface UserListProps {
  users: User[];
  currentUserId: string;
  onRefresh: () => void;
}

export function UserList({ users, currentUserId, onRefresh }: UserListProps) {
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const handleToggleActive = async (user: User) => {
    setTogglingId(user.id);
    try {
      await api.put(`/api/v1/auth/users/${user.id}`, {
        is_active: !user.is_active,
      });
      toast.success(`User ${user.is_active ? "deactivated" : "activated"}.`);
      onRefresh();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to update user.");
    } finally {
      setTogglingId(null);
    }
  };

  if (users.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <EmptyState
          icon={Users}
          title="No users found"
          description="Create the first team member"
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
              Name
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[220px]">
              Email
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[100px]">
              Role
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[80px]">
              Active
            </TableHead>
            <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[120px]">
              Created
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map((user) => (
            <TableRow
              key={user.id}
              className="border-b border-gray-100 hover:bg-gray-50/60 transition-colors"
            >
              <TableCell className="px-4 py-3">
                <span className="text-sm font-medium text-gray-800">{user.name}</span>
                {user.id === currentUserId && (
                  <span className="ml-2 text-[10px] text-gray-400">(you)</span>
                )}
              </TableCell>
              <TableCell className="px-4 py-3 w-[220px]">
                <span className="text-sm text-gray-600">{user.email}</span>
              </TableCell>
              <TableCell className="px-4 py-3 w-[100px]">
                <span
                  className={cn(
                    "rounded-full px-2.5 py-0.5 text-xs font-medium",
                    ROLE_BADGE_CLASSES[user.role]
                  )}
                >
                  {ROLE_LABELS[user.role]}
                </span>
              </TableCell>
              <TableCell className="px-4 py-3 w-[80px]">
                <Switch
                  checked={user.is_active}
                  onCheckedChange={() => handleToggleActive(user)}
                  disabled={togglingId === user.id || user.id === currentUserId}
                  aria-label={`Toggle active status for ${user.name}`}
                />
              </TableCell>
              <TableCell className="px-4 py-3 w-[120px]">
                <span className="text-xs text-gray-400">
                  {formatDateShort(user.created_at)}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
