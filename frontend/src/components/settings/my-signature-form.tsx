"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useUser } from "@/hooks/use-user";
import type { MeResponse } from "@/lib/types";

const PLACEHOLDER = `Thanks,

Your Name
Schilmoeller & Schoenfield, PC`;

/**
 * Per-user signature editor — every staff member edits their own. The
 * signature is appended automatically when THIS user sends an email (AI
 * draft replies and composed emails alike). Leaving it blank falls back to
 * the company signature, shown beneath as the effective preview.
 */
export function MySignatureForm() {
  const { user, mutate } = useUser();
  const [value, setValue] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const serverValue = user?.signature ?? "";
  const usingFallback = !serverValue.trim();

  // Sync the textarea to the server value until the user starts editing.
  useEffect(() => {
    if (!dirty) setValue(serverValue);
  }, [serverValue, dirty]);

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await api.patch<MeResponse>("/api/v1/auth/me/signature", {
        signature: value,
      });
      await mutate();
      setDirty(false);
      toast.success(
        value.trim()
          ? "Your signature is saved — emails you send will end with it."
          : "Signature cleared — your emails will use the company signature."
      );
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not save signature.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-3">
      <div>
        <label htmlFor="my-signature" className="block text-sm font-medium text-foreground">
          My signature
        </label>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          Added to the end of every email <span className="font-medium text-foreground">you</span> send
          — AI draft replies and new emails alike. Leave it blank to use the company signature.
        </p>
      </div>
      <Textarea
        id="my-signature"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          setDirty(true);
        }}
        rows={8}
        placeholder={PLACEHOLDER}
        className="resize-y font-mono text-xs leading-relaxed whitespace-pre"
      />
      {usingFallback && !dirty && user?.effective_signature && (
        <div className="rounded-lg bg-muted/60 border border-border px-3 py-2">
          <p className="text-[11px] font-medium text-muted-foreground mb-1">
            Currently using the company signature:
          </p>
          <pre className="text-xs text-muted-foreground font-mono whitespace-pre-wrap leading-relaxed">
            {user.effective_signature}
          </pre>
        </div>
      )}
      <div className="flex items-center justify-end gap-3">
        {dirty && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
        <Button onClick={handleSave} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save my signature"}
        </Button>
      </div>
    </div>
  );
}
