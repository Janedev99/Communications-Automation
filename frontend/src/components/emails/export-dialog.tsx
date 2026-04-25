"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const getBaseUrl = () =>
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

/** Read a named cookie value from document.cookie, or null if not found. */
function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

interface ExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ExportDialog({ open, onOpenChange }: ExportDialogProps) {
  const [clientEmail, setClientEmail] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [loading, setLoading] = useState(false);

  const handleExport = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (clientEmail.trim()) params.set("client_email", clientEmail.trim());
      if (fromDate) params.set("from", fromDate);
      if (toDate) params.set("to", toDate);

      // The export endpoint returns NDJSON (application/x-ndjson), not a JSON array.
      // We must read it as text, split on newlines, and parse each line individually.
      const url = `${getBaseUrl()}/api/v1/emails/export?${params.toString()}`;
      const csrfToken = getCookie("csrf_token");
      const res = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
      });

      if (res.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (!res.ok) {
        let message = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail) message = body.detail;
        } catch { /* ignore */ }
        throw new Error(message);
      }

      const text = await res.text();
      const lines = text.split("\n").filter((l) => l.trim().length > 0);
      const records = lines.map((line) => JSON.parse(line) as unknown);

      if (records.length === 0) {
        toast.info("No threads found matching the selected filters.");
        return;
      }

      // Trigger browser download as a pretty-printed JSON file
      const blob = new Blob([JSON.stringify(records, null, 2)], {
        type: "application/json",
      });
      const downloadUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = `email-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(downloadUrl);

      toast.success(
        `Exported ${records.length} thread${records.length !== 1 ? "s" : ""}.`
      );
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Export Compliance Report</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Export threads with all messages, drafts, and escalations as a JSON file.
            Leave filters blank to export all threads (up to 500).
          </p>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">
              Client email <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <Input
              type="email"
              value={clientEmail}
              onChange={(e) => setClientEmail(e.target.value)}
              placeholder="client@example.com"
              disabled={loading}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">
                From date
              </label>
              <Input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                disabled={loading}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">
                To date
              </label>
              <Input
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                disabled={loading}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">Times are in UTC.</p>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            className="bg-brand-500 hover:bg-brand-600 text-white"
            onClick={handleExport}
            disabled={loading}
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <Download className="w-4 h-4 mr-2" />
                Export JSON
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
