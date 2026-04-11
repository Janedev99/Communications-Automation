"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/page-header";
import { UserList } from "@/components/settings/user-list";
import { CreateUserDialog } from "@/components/settings/create-user-dialog";
import { ChangePasswordForm } from "@/components/settings/change-password-form";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { useUser } from "@/hooks/use-user";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { User } from "@/lib/types";

export default function SettingsPage() {
  const { user, isAdmin } = useUser();
  const [createOpen, setCreateOpen] = useState(false);

  // Redirect non-admins to their own profile settings only (no user management)
  // (We keep the page accessible to staff for the password change section)

  const { data: users, isLoading, error: usersError, mutate } = useSWR<User[]>(
    isAdmin ? "/api/v1/auth/users" : null,
    swrFetcher
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title="Settings"
        subtitle={isAdmin ? "Manage team access and account settings" : "Account settings"}
        actions={
          isAdmin ? (
            <Button
              className="bg-brand-500 hover:bg-brand-600 text-white"
              onClick={() => setCreateOpen(true)}
            >
              <Plus className="w-4 h-4 mr-1.5" />
              Create User
            </Button>
          ) : undefined
        }
      />

      {/* Password change — available to all users */}
      <section>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Account</h2>
        <ChangePasswordForm />
      </section>

      {/* User management — admin only */}
      {isAdmin && (
        <section>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Team Members</h2>
          {usersError ? (
            <ErrorState
              title="Failed to load users"
              description="Could not retrieve team members. Please try again."
              onRetry={mutate}
            />
          ) : isLoading ? (
            <TableSkeleton rows={5} />
          ) : (
            <UserList
              users={users ?? []}
              currentUserId={user?.id ?? ""}
              onRefresh={mutate}
            />
          )}
        </section>
      )}

      {isAdmin && (
        <CreateUserDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={mutate}
        />
      )}
    </div>
  );
}
