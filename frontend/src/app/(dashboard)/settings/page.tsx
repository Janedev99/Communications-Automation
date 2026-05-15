"use client";

import { useState } from "react";
import Link from "next/link";
import { Activity, ChevronRight, Plus, Server, Sliders } from "lucide-react";
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
        subtitle={isAdmin ? "Manage team access, AI behavior, and account settings." : "Account settings."}
        actions={
          isAdmin ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="w-4 h-4 mr-1.5" aria-hidden="true" />
              Create user
            </Button>
          ) : undefined
        }
      />

      {/* Password change — available to all users */}
      <section>
        <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">Account</h2>
        <ChangePasswordForm />
      </section>

      {/* AI / triage configuration — admin only */}
      {isAdmin && (
        <section>
          <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">AI &amp; Triage</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Link
              href="/settings/triage-rules"
              className="group flex items-start gap-3 p-4 bg-card border border-border rounded-xl hover:border-foreground/15 hover:shadow-sm transition-all duration-150"
            >
              <span className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0">
                <Sliders className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
              </span>
              <span className="flex-1 min-w-0">
                <span className="flex items-center justify-between gap-2">
                  <span className="block text-sm font-semibold text-foreground">Triage Rules</span>
                  <ChevronRight
                    className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-foreground transition-colors"
                    aria-hidden="true"
                  />
                </span>
                <span className="block text-xs text-muted-foreground mt-1 leading-relaxed">
                  Decide which email categories may be auto-handled by AI (T1) and at what confidence.
                </span>
              </span>
            </Link>
            <Link
              href="/settings/integrations"
              className="group flex items-start gap-3 p-4 bg-card border border-border rounded-xl hover:border-foreground/15 hover:shadow-sm transition-all duration-150"
            >
              <span className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0">
                <Activity className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
              </span>
              <span className="flex-1 min-w-0">
                <span className="flex items-center justify-between gap-2">
                  <span className="block text-sm font-semibold text-foreground">Integrations &amp; Health</span>
                  <ChevronRight
                    className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-foreground transition-colors"
                    aria-hidden="true"
                  />
                </span>
                <span className="block text-xs text-muted-foreground mt-1 leading-relaxed">
                  Live status of database, Anthropic, email provider, and notifications.
                </span>
              </span>
            </Link>
            <Link
              href="/settings/runpod"
              className="group flex items-start gap-3 p-4 bg-card border border-border rounded-xl hover:border-foreground/15 hover:shadow-sm transition-all duration-150"
            >
              <span className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0">
                <Server className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
              </span>
              <span className="flex-1 min-w-0">
                <span className="flex items-center justify-between gap-2">
                  <span className="block text-sm font-semibold text-foreground">RunPod</span>
                  <ChevronRight
                    className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-foreground transition-colors"
                    aria-hidden="true"
                  />
                </span>
                <span className="block text-xs text-muted-foreground mt-1 leading-relaxed">
                  GPU pod state, uptime, cost so far, and manual stop / wake controls.
                </span>
              </span>
            </Link>
          </div>
        </section>
      )}

      {/* User management — admin only */}
      {isAdmin && (
        <section>
          <h2 className="text-sm font-semibold text-foreground mb-3 tracking-tight">Team Members</h2>
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
