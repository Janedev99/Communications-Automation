"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { api, swrFetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { SystemSetting } from "@/lib/types";

const SETTINGS_ENDPOINT = "/api/v1/system-settings";
const SIGNATURE_KEY = "company_signature";

const PLACEHOLDER = `Schilmoeller & Schoenfield, PC
3131 Eastside Street, Suite 430
Houston, Texas  77098

Office:  (713) 527-9281 Ext 1`;

/**
 * Admin editor for the firm-level COMPANY signature. It is appended to:
 *   - T1 auto-sent emails (no human sender), and
 *   - emails sent by any user who hasn't set a personal signature.
 * Reads/writes the `company_signature` system setting.
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
      toast.success("Company signature saved.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Could not save signature.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-3">
      <div>
        <label htmlFor="company-signature" className="block text-sm font-medium text-foreground">
          Company signature
        </label>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          The firm-level block — used on automatically sent (Tier&nbsp;1) emails and as
          the fallback for anyone who hasn&apos;t set a personal signature in
          &ldquo;My Signature&rdquo;.
        </p>
      </div>
      <Textarea
        id="company-signature"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          setDirty(true);
        }}
        rows={8}
        placeholder={PLACEHOLDER}
        className="resize-y font-mono text-xs leading-relaxed whitespace-pre"
      />
      <div className="flex items-center justify-end gap-3">
        {dirty && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
        <Button onClick={handleSave} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save company signature"}
        </Button>
      </div>
    </div>
  );
}
