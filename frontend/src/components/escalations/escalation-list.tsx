"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink, Sparkles } from "lucide-react";
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { AlertTriangle } from "lucide-react";
import { ResolveDialog } from "./resolve-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import {
  SEVERITY_BADGE_CLASSES,
  SEVERITY_LABELS,
  SEVERITY_ROW_BORDER,
  ESCALATION_STATUS_BADGE_CLASSES,
  ESCALATION_STATUS_LABELS,
} from "@/lib/constants";
import { api } from "@/lib/api";
import { cn, relativeTime, formatDate } from "@/lib/utils";
import type { Escalation } from "@/lib/types";

interface EscalationListProps {
  escalations: Escalation[];
  onRefresh: () => void;
}

export function EscalationList({ escalations, onRefresh }: EscalationListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [resolveEscalation, setResolveEscalation] = useState<Escalation | null>(null);
  const [acknowledging, setAcknowledging] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  const toggleExpanded = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const handleAcknowledge = async (escalation: Escalation) => {
    setAcknowledging(escalation.id);
    try {
      await api.put(`/api/v1/escalations/${escalation.id}/acknowledge`, {});
      toast.success("Escalation acknowledged.");
      onRefresh();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to acknowledge escalation.");
    } finally {
      setAcknowledging(null);
    }
  };

  const handleResolve = async (notes: string) => {
    if (!resolveEscalation) return;
    setResolving(true);
    try {
      await api.put(`/api/v1/escalations/${resolveEscalation.id}/resolve`, {
        resolution_notes: notes,
      });
      toast.success("Escalation resolved.");
      setResolveEscalation(null);
      onRefresh();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to resolve escalation.");
    } finally {
      setResolving(false);
    }
  };

  if (escalations.length === 0) {
    return (
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <EmptyState
          icon={AlertTriangle}
          title="No escalations found"
          description="Try adjusting your filters"
        />
      </div>
    );
  }

  return (
    <>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/80 hover:bg-accent/80">
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-8" />
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Thread
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[220px]">
                Reason
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[100px]">
                Severity
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[120px]">
                Status
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[120px]">
                Created
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {escalations.map((esc) => (
              <React.Fragment key={esc.id}>
                <TableRow
                  className={cn(
                    "hover:bg-accent/60 cursor-pointer transition-colors border-b border-border/60 border-l-4",
                    SEVERITY_ROW_BORDER[esc.severity]
                  )}
                  tabIndex={0}
                  onClick={() => toggleExpanded(esc.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleExpanded(esc.id);
                    }
                  }}
                >
                  <TableCell className="px-3 py-3 w-8 text-muted-foreground">
                    {expandedId === esc.id ? (
                      <ChevronDown className="w-4 h-4" />
                    ) : (
                      <ChevronRight className="w-4 h-4" />
                    )}
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <div className="max-w-[260px]">
                      <span className="text-sm font-medium text-foreground truncate block">
                        {esc.thread_subject ?? `Thread ${esc.thread_id.slice(0, 8)}…`}
                      </span>
                      {esc.thread_client_email && (
                        <span className="text-xs text-muted-foreground truncate block">
                          {esc.thread_client_email}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="px-4 py-3 w-[220px]">
                    <span className="text-sm text-muted-foreground truncate block max-w-[200px]">
                      {esc.reason}
                    </span>
                  </TableCell>
                  <TableCell className="px-4 py-3 w-[100px]">
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-xs font-medium",
                        SEVERITY_BADGE_CLASSES[esc.severity]
                      )}
                    >
                      {SEVERITY_LABELS[esc.severity]}
                    </span>
                  </TableCell>
                  <TableCell className="px-4 py-3 w-[120px]">
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-xs font-medium",
                        ESCALATION_STATUS_BADGE_CLASSES[esc.status]
                      )}
                    >
                      {ESCALATION_STATUS_LABELS[esc.status]}
                    </span>
                  </TableCell>
                  <TableCell className="px-4 py-3 w-[120px]">
                    <span className="text-xs text-muted-foreground">
                      {relativeTime(esc.created_at)}
                    </span>
                  </TableCell>
                </TableRow>

                {/* Expanded detail row */}
                {expandedId === esc.id && (
                  <TableRow key={`${esc.id}-expanded`} className="bg-muted/40 border-b border-border hover:bg-muted/40">
                    <TableCell
                      colSpan={6}
                      className="px-6 py-5 whitespace-normal break-words align-top"
                    >
                      <div className="max-w-3xl space-y-4">
                        {/* AI summary card */}
                        <div className="rounded-md border border-border bg-card p-3.5">
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <Sparkles
                              className="w-3.5 h-3.5 text-muted-foreground"
                              strokeWidth={1.75}
                            />
                            <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                              AI summary
                            </span>
                          </div>
                          <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap break-words">
                            {esc.reason}
                          </p>
                        </div>

                        {/* Resolution notes (resolved only) */}
                        {esc.status === "resolved" && esc.resolution_notes && (
                          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3.5">
                            <p className="text-[11px] font-medium uppercase tracking-wider text-emerald-700 dark:text-emerald-300 mb-1.5">
                              Resolution notes
                            </p>
                            <p className="text-sm text-emerald-700 dark:text-emerald-300 leading-relaxed whitespace-pre-wrap break-words">
                              {esc.resolution_notes}
                            </p>
                            {esc.resolved_at && (
                              <p className="text-xs text-emerald-600/80 dark:text-emerald-400/80 mt-2">
                                Resolved {formatDate(esc.resolved_at)}
                              </p>
                            )}
                          </div>
                        )}

                        {/* Actions */}
                        <div className="flex items-center gap-3 flex-wrap">
                          <Link
                            href={`/emails/${esc.thread_id}`}
                            className="inline-flex items-center gap-1 text-sm text-brand-500 hover:text-brand-600"
                            onClick={(e) => e.stopPropagation()}
                          >
                            View thread
                            <ExternalLink className="w-3.5 h-3.5" />
                          </Link>

                          {esc.status === "pending" && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAcknowledge(esc);
                              }}
                              disabled={acknowledging === esc.id}
                            >
                              {acknowledging === esc.id ? "Acknowledging..." : "Acknowledge"}
                            </Button>
                          )}

                          {esc.status === "acknowledged" && (
                            <Button
                              size="sm"
                              className="bg-brand-500 hover:bg-brand-600 text-white"
                              onClick={(e) => {
                                e.stopPropagation();
                                setResolveEscalation(esc);
                              }}
                            >
                              Resolve
                            </Button>
                          )}
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
      </div>

      <ResolveDialog
        open={!!resolveEscalation}
        onOpenChange={(v) => !v && setResolveEscalation(null)}
        onResolve={handleResolve}
        loading={resolving}
      />
    </>
  );
}
