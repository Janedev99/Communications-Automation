"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/page-header";
import { UserList } from "@/components/settings/user-list";
import { CreateUserDialog } from "@/components/settings/create-user-dialog";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { useUser } from "@/hooks/use-user";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { User } from "@/lib/types";

export default function SettingsPage() {
  const router = useRouter();
  const { user, isAdmin } = useUser();
  const [createOpen, setCreateOpen] = useState(false);

  // Redirect non-admins
  useEffect(() => {
    if (user && !isAdmin) {
      router.replace("/");
    }
  }, [user, isAdmin, router]);

  const { data: users, isLoading, mutate } = useSWR<User[]>(
    isAdmin ? "/api/v1/auth/users" : null,
    swrFetcher
  );

  if (!isAdmin) return null;

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Manage team access"
        actions={
          <Button
            className="bg-brand-500 hover:bg-brand-600 text-white"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Create User
          </Button>
        }
      />

      {isLoading ? (
        <TableSkeleton rows={5} />
      ) : (
        <UserList
          users={users ?? []}
          currentUserId={user?.id ?? ""}
          onRefresh={mutate}
        />
      )}

      <CreateUserDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={mutate}
      />
    </div>
  );
}
