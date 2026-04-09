"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
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
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
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
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-gray-50/80 hover:bg-gray-50/80">
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-8" />
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                Thread
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[220px]">
                Reason
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[100px]">
                Severity
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[120px]">
                Status
              </TableHead>
              <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 w-[120px]">
                Created
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {escalations.map((esc) => (
              <React.Fragment key={esc.id}>
                <TableRow
                  className={cn(
                    "hover:bg-gray-50/60 cursor-pointer transition-colors border-b border-gray-100 border-l-4",
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
                  <TableCell className="px-3 py-3 w-8 text-gray-400">
                    {expandedId === esc.id ? (
                      <ChevronDown className="w-4 h-4" />
                    ) : (
                      <ChevronRight className="w-4 h-4" />
                    )}
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <div className="max-w-[260px]">
                      <span className="text-sm font-medium text-gray-800 truncate block">
                        {esc.thread_subject ?? `Thread ${esc.thread_id.slice(0, 8)}…`}
                      </span>
                      {esc.thread_client_email && (
                        <span className="text-xs text-gray-400 truncate block">
                          {esc.thread_client_email}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="px-4 py-3 w-[220px]">
                    <span className="text-sm text-gray-600 truncate block max-w-[200px]">
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
                    <span className="text-xs text-gray-400">
                      {relativeTime(esc.created_at)}
                    </span>
                  </TableCell>
                </TableRow>

                {/* Expanded detail row */}
                {expandedId === esc.id && (
                  <TableRow key={`${esc.id}-expanded`} className="bg-gray-50 border-b border-gray-200">
                    <TableCell colSpan={6} className="px-6 py-4">
                      <div className="space-y-3">
                        <p className="text-sm text-gray-600 leading-relaxed">{esc.reason}</p>

                        <div className="flex items-center gap-3">
                          <Link
                            href={`/emails/${esc.thread_id}`}
                            className="inline-flex items-center gap-1 text-sm text-brand-500 hover:text-brand-600"
                            onClick={(e) => e.stopPropagation()}
                          >
                            View Thread
                            <ExternalLink className="w-3.5 h-3.5" />
                          </Link>
                        </div>

                        {/* Action buttons based on status */}
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

                        {esc.status === "resolved" && esc.resolution_notes && (
                          <div className="bg-emerald-50 rounded-md px-3 py-2 border border-emerald-200">
                            <p className="text-xs font-medium text-emerald-700 mb-1">Resolution Notes</p>
                            <p className="text-sm text-emerald-700">{esc.resolution_notes}</p>
                            {esc.resolved_at && (
                              <p className="text-xs text-emerald-500 mt-1">
                                Resolved {formatDate(esc.resolved_at)}
                              </p>
                            )}
                          </div>
                        )}
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
