"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { api, swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { SystemSetting } from "@/lib/types";

const SETTINGS_ENDPOINT = "/api/v1/system-settings";
const SIGNATURE_KEY = "draft_signature";

const PLACEHOLDER = `Thanks so much,

Jane

Jane M. Schilmoeller, CPA
Business Growth and Profitability Advisor

Schilmoeller & Schoenfield, PC`;

/**
 * Admin editor for the signature the AI appends verbatim to every draft.
 * Reads/writes the `draft_signature` system setting. Leaving it blank lets the
 * AI sign off on its own (content-driven branding rule).
 */
export function SignatureForm() {
  const { data, mutate } = useSWR<SystemSetting[]>(SETTINGS_ENDPOINT, swrFetcher);
  const [value, setValue] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const serverValue =
    data?.find((s) => s.key === SIGNATURE_KEY)?.value ?? "";

  // Sync the textarea to the server value until the user starts editing.
  useEffect(() => {
    if (!dirty) setValue(serverValue);
  }, [serverValue, dirty]);

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await api.patch<SystemSetting>(`${SETTINGS_ENDPOINT}/${SIGNATURE_KEY}`, {
        value,
      });
      await mutate();
      setDirty(false);
      toast.success("Signature saved — new AI drafts will use it.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not save signature.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-3">
      <div>
        <label htmlFor="draft-signature" className="block text-sm font-medium text-foreground">
          Signature appended to AI drafts
        </label>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          The AI ends every draft with this exact block. Leave it blank to let the AI
          sign off on its own.
        </p>
      </div>
      <Textarea
        id="draft-signature"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          setDirty(true);
        }}
        rows={12}
        placeholder={PLACEHOLDER}
        className="resize-y font-mono text-xs leading-relaxed whitespace-pre"
      />
      <div className="flex items-center justify-end gap-3">
        {dirty && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
        <Button onClick={handleSave} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save signature"}
        </Button>
      </div>
    </div>
  );
}
