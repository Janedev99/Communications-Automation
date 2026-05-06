"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowLeft, Lock, Loader2, Pause, Play } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { api, swrFetcher } from "@/lib/api";
import { useUser } from "@/hooks/use-user";
import { ApiError } from "@/lib/types";
import { cn, relativeTime } from "@/lib/utils";
import type { EmailCategory, SystemSetting, TierRule, TierRuleUpdate } from "@/lib/types";

const ENDPOINT = "/api/v1/tier-rules";

// Hard safety rail mirrored on the backend (api/tier_rules.py).
// These categories cannot be enabled for T1 auto-send under any circumstance.
const T1_LOCKED_CATEGORIES: ReadonlySet<EmailCategory> = new Set<EmailCategory>([
  "complaint",
  "urgent",
  "uncategorized",
]);

const CATEGORY_LABELS: Record<EmailCategory, string> = {
  status_update: "Status update",
  document_request: "Document request",
  appointment: "Appointment",
  clarification: "Clarification",
  general_inquiry: "General inquiry",
  complaint: "Complaint",
  urgent: "Urgent",
  uncategorized: "Uncategorized",
};

const CATEGORY_DESCRIPTIONS: Record<EmailCategory, string> = {
  status_update: "Common acknowledgments and progress check-ins.",
  document_request: "Requests to provide or confirm receipt of documents.",
  appointment: "Scheduling, rescheduling, or cancelling a meeting.",
  clarification: "Client asking to clarify something about their taxes or actions.",
  general_inquiry: "General questions about services, pricing, or processes.",
  complaint: "Client expressing dissatisfaction. Always requires staff review.",
  urgent: "Time-sensitive matter (deadlines, audit notices). Always staff-reviewed.",
  uncategorized: "Cannot be classified by the AI. Always staff-reviewed.",
};

interface RuleCardProps {
  rule: TierRule;
  onUpdate: (category: EmailCategory, body: TierRuleUpdate) => Promise<void>;
}

function RuleCard({ rule, onUpdate }: RuleCardProps) {
  const isLocked = T1_LOCKED_CATEGORIES.has(rule.category);
  const [pending, setPending] = useState<"toggle" | "threshold" | null>(null);
  const [draftThreshold, setDraftThreshold] = useState(rule.t1_min_confidence);

  // Keep slider in sync if rule changes from elsewhere
  useEffect(() => {
    setDraftThreshold(rule.t1_min_confidence);
  }, [rule.t1_min_confidence]);

  const handleToggle = async () => {
    if (isLocked || pending) return;
    setPending("toggle");
    try {
      await onUpdate(rule.category, { t1_eligible: !rule.t1_eligible });
      toast.success(
        rule.t1_eligible
          ? `${CATEGORY_LABELS[rule.category]} disabled for T1`
          : `${CATEGORY_LABELS[rule.category]} enabled for T1`
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Update failed";
      toast.error(msg);
    } finally {
      setPending(null);
    }
  };

  const handleThresholdCommit = async () => {
    if (pending || draftThreshold === rule.t1_min_confidence) return;
    setPending("threshold");
    try {
      await onUpdate(rule.category, { t1_min_confidence: draftThreshold });
      toast.success(
        `Threshold updated to ${(draftThreshold * 100).toFixed(0)}% for ${CATEGORY_LABELS[rule.category]}`
      );
    } catch (err) {
      // revert
      setDraftThreshold(rule.t1_min_confidence);
      const msg = err instanceof ApiError ? err.message : "Update failed";
      toast.error(msg);
    } finally {
      setPending(null);
    }
  };

  return (
    <div
      className={cn(
        "bg-card border border-border rounded-xl p-5 transition-colors",
        rule.t1_eligible && !isLocked && "border-emerald-500/30 ring-1 ring-emerald-500/10",
        isLocked && "opacity-90"
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-foreground">
              {CATEGORY_LABELS[rule.category]}
            </h3>
            {isLocked && (
              <span
                title="Locked off — these messages always require staff review"
                className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground px-2 py-0.5 rounded bg-muted ring-1 ring-border"
              >
                <Lock className="w-3 h-3" />
                Locked
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            {CATEGORY_DESCRIPTIONS[rule.category]}
          </p>
        </div>
        {/* Eligibility toggle */}
        <button
          role="switch"
          aria-checked={rule.t1_eligible}
          aria-label={`Toggle T1 auto-send for ${CATEGORY_LABELS[rule.category]}`}
          disabled={isLocked || pending !== null}
          onClick={handleToggle}
          className={cn(
            "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-150",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            rule.t1_eligible ? "bg-emerald-500" : "bg-muted ring-1 ring-border",
            (isLocked || pending) && "cursor-not-allowed opacity-60"
          )}
        >
          <span
            className={cn(
              "inline-block h-5 w-5 rounded-full bg-card shadow-sm transition-transform duration-150",
              rule.t1_eligible ? "translate-x-5" : "translate-x-0.5"
            )}
          />
        </button>
      </div>

      {/* Threshold slider — hidden when locked or T1 is off */}
      {!isLocked && rule.t1_eligible && (
        <div className="mt-4 pt-4 border-t border-border">
          <div className="flex items-center justify-between gap-4">
            <label
              htmlFor={`threshold-${rule.category}`}
              className="text-sm font-medium text-foreground"
            >
              Min. confidence to auto-send
            </label>
            <span className="text-sm font-semibold tabular-nums text-foreground">
              {(draftThreshold * 100).toFixed(0)}%
            </span>
          </div>
          <input
            id={`threshold-${rule.category}`}
            type="range"
            min={50}
            max={99}
            step={1}
            value={Math.round(draftThreshold * 100)}
            onChange={(e) => setDraftThreshold(parseInt(e.target.value, 10) / 100)}
            onMouseUp={handleThresholdCommit}
            onTouchEnd={handleThresholdCommit}
            onKeyUp={(e) => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
                handleThresholdCommit();
              }
            }}
            className="mt-2 w-full h-1.5 rounded-full bg-muted appearance-none cursor-pointer accent-primary disabled:opacity-50"
            disabled={pending !== null}
            aria-valuenow={Math.round(draftThreshold * 100)}
            aria-valuemin={50}
            aria-valuemax={99}
          />
          <p className="text-xs text-muted-foreground mt-2">
            Higher = more conservative. Below {(draftThreshold * 100).toFixed(0)}% the AI&apos;s
            output goes to staff review instead of auto-sending.
          </p>
        </div>
      )}

      {rule.updated_by_name && (
        <p className="text-[11px] text-muted-foreground mt-3">
          Last changed by {rule.updated_by_name} · {relativeTime(rule.updated_at)}
        </p>
      )}
    </div>
  );
}

const SETTINGS_ENDPOINT = "/api/v1/system-settings";

export default function TriageRulesPage() {
  const { isAdmin, isLoading: userLoading } = useUser();
  const { data, error, isLoading, mutate } = useSWR<TierRule[]>(
    isAdmin ? ENDPOINT : null,
    swrFetcher
  );

  const {
    data: settings,
    mutate: mutateSettings,
  } = useSWR<SystemSetting[]>(
    isAdmin ? SETTINGS_ENDPOINT : null,
    swrFetcher
  );

  const enabledCount = (data ?? []).filter((r) => r.t1_eligible).length;
  const autoSendSetting = settings?.find((s) => s.key === "auto_send_enabled");
  const autoSendEnabled = autoSendSetting?.value === "true";

  const [confirmEnableOpen, setConfirmEnableOpen] = useState(false);
  const [togglingMaster, setTogglingMaster] = useState(false);

  const handleMasterToggle = async (turnOn: boolean) => {
    setTogglingMaster(true);
    try {
      await api.patch<SystemSetting>(`${SETTINGS_ENDPOINT}/auto_send_enabled`, {
        value: turnOn ? "true" : "false",
      });
      await mutateSettings();
      toast.success(
        turnOn
          ? "Global auto-send enabled. T1-eligible threads may now be auto-handled."
          : "Global auto-send paused. All threads route to staff review."
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Update failed";
      toast.error(msg);
    } finally {
      setTogglingMaster(false);
      setConfirmEnableOpen(false);
    }
  };

  const handleUpdate = async (category: EmailCategory, body: TierRuleUpdate) => {
    // Optimistic update — flip the row, revert on error
    const optimistic = (current: TierRule[] | undefined) =>
      (current ?? []).map((r) =>
        r.category === category
          ? {
              ...r,
              t1_eligible: body.t1_eligible ?? r.t1_eligible,
              t1_min_confidence: body.t1_min_confidence ?? r.t1_min_confidence,
            }
          : r
      );

    await mutate(optimistic, { revalidate: false });
    try {
      const updated = await api.patch<TierRule>(
        `${ENDPOINT}/${category}`,
        body
      );
      await mutate(
        (current) =>
          (current ?? []).map((r) =>
            r.category === category ? { ...r, ...updated } : r
          ),
        { revalidate: false }
      );
    } catch (err) {
      // Revert on failure
      await mutate();
      throw err;
    }
  };

  if (userLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="bg-card border border-border rounded-lg p-8 text-center">
        <Lock className="w-10 h-10 text-muted-foreground mx-auto" strokeWidth={1.5} />
        <h2 className="text-lg font-semibold text-foreground mt-3">
          Admin access required
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Only admins can configure triage rules.
        </p>
        <Link
          href="/settings"
          className="inline-block mt-4 text-sm text-primary hover:underline"
        >
          Back to settings
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link
        href="/settings"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-3"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to settings
      </Link>

      <PageHeader
        title="Triage Rules"
        subtitle="Decide which categories the AI may auto-handle (T1) and the minimum confidence required."
      />

      {/* Master kill switch */}
      <div
        className={cn(
          "rounded-xl border p-5 mb-3 transition-colors",
          autoSendEnabled
            ? "bg-emerald-500/10 border-emerald-500/30"
            : "bg-amber-500/10 border-amber-500/30"
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <span
              className={cn(
                "flex items-center justify-center w-10 h-10 rounded-md shrink-0",
                autoSendEnabled
                  ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300"
                  : "bg-amber-500/20 text-amber-700 dark:text-amber-300"
              )}
            >
              {autoSendEnabled ? (
                <Play className="w-5 h-5" strokeWidth={2} />
              ) : (
                <Pause className="w-5 h-5" strokeWidth={2} />
              )}
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2
                  className={cn(
                    "text-base font-semibold",
                    autoSendEnabled
                      ? "text-emerald-800 dark:text-emerald-200"
                      : "text-amber-800 dark:text-amber-200"
                  )}
                >
                  Global auto-send is{" "}
                  {autoSendEnabled ? (
                    <span className="inline-flex items-center gap-1.5">
                      ENABLED
                      <span
                        className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse motion-reduce:animate-none"
                        aria-hidden
                      />
                    </span>
                  ) : (
                    "PAUSED"
                  )}
                </h2>
              </div>
              <p
                className={cn(
                  "text-sm mt-1",
                  autoSendEnabled
                    ? "text-emerald-700/90 dark:text-emerald-300/90"
                    : "text-amber-700/90 dark:text-amber-300/90"
                )}
              >
                {autoSendEnabled
                  ? `T1-eligible threads with sufficient confidence are sent automatically. ${
                      enabledCount === 0
                        ? "No categories are currently T1-eligible — enable one below."
                        : `${enabledCount} ${enabledCount === 1 ? "category is" : "categories are"} eligible.`
                    }`
                  : "Every email routes to staff review, regardless of category settings below."}
              </p>
              {autoSendSetting?.updated_by_name && (
                <p className="text-[11px] text-muted-foreground mt-2">
                  Last changed by {autoSendSetting.updated_by_name} ·{" "}
                  {relativeTime(autoSendSetting.updated_at)}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={() => {
              if (autoSendEnabled) {
                handleMasterToggle(false);
              } else {
                setConfirmEnableOpen(true);
              }
            }}
            disabled={togglingMaster || !autoSendSetting}
            className={cn(
              "shrink-0 inline-flex items-center gap-1.5 px-4 h-9 rounded-md text-sm font-semibold transition-colors",
              autoSendEnabled
                ? "bg-card text-foreground ring-1 ring-border hover:bg-accent"
                : "bg-emerald-600 text-white hover:bg-emerald-700",
              togglingMaster && "opacity-60 cursor-wait"
            )}
          >
            {togglingMaster ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : autoSendEnabled ? (
              <>
                <Pause className="w-4 h-4" />
                Pause auto-send
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Enable auto-send
              </>
            )}
          </button>
        </div>
      </div>

      {/* Sub-summary: how many categories are flipped on */}
      <div className="rounded-xl border border-border bg-card px-4 py-3 mb-6">
        <p className="text-sm text-muted-foreground">
          <strong className="text-foreground font-semibold tabular-nums">{enabledCount}</strong>{" "}
          {enabledCount === 1 ? "category is" : "categories are"} marked T1-eligible below.{" "}
          {!autoSendEnabled && (
            <span className="opacity-80">
              These have no effect while the master switch is paused.
            </span>
          )}
        </p>
      </div>

      {error ? (
        <ErrorState
          title="Failed to load tier rules"
          description="Could not retrieve triage rule configuration."
          onRetry={mutate}
        />
      ) : isLoading || !data ? (
        <TableSkeleton rows={4} />
      ) : (
        <div className="grid gap-3">
          {data.map((rule) => (
            <RuleCard key={rule.id} rule={rule} onUpdate={handleUpdate} />
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground mt-6">
        <strong className="text-foreground/80">Hard safety rail:</strong>{" "}
        Complaint, Urgent, and Uncategorized messages can never be enabled for T1
        auto-send. This is enforced at both the API and the database layer.
      </p>

      <ConfirmDialog
        open={confirmEnableOpen}
        onOpenChange={setConfirmEnableOpen}
        title="Enable global auto-send?"
        description={
          enabledCount === 0
            ? "No categories are currently T1-eligible, so nothing will be sent automatically. You can still flip the switch — it just won't take effect until you enable a category below."
            : `T1-eligible categories with sufficient confidence will be auto-handled by AI without staff review. ${enabledCount} ${
                enabledCount === 1 ? "category is" : "categories are"
              } eligible. Every auto-send is recorded in the audit log.`
        }
        confirmLabel="Enable auto-send"
        confirmVariant="default"
        onConfirm={() => handleMasterToggle(true)}
        loading={togglingMaster}
      />
    </div>
  );
}
