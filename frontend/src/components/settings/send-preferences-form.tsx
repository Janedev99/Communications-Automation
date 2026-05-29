"use client";

import { Switch } from "@/components/ui/switch";
import { useSendCountdownEnabled } from "@/lib/preferences";

/**
 * Personal sending preferences. Browser-local (per user, per browser) — these
 * tune how the send flow behaves for the person at this machine and never
 * touch the server, so every staff member controls their own without admin
 * involvement.
 */
export function SendPreferencesForm() {
  const [countdownEnabled, setCountdownEnabled] = useSendCountdownEnabled();

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <label
            htmlFor="send-countdown"
            className="block text-sm font-medium text-foreground"
          >
            10-second undo countdown
          </label>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            After you confirm <span className="font-medium">Send</span>, the email
            is held for 10 seconds so you can still cancel. Turn this off to send
            immediately. Saved in this browser.
          </p>
        </div>
        <Switch
          id="send-countdown"
          checked={countdownEnabled}
          onCheckedChange={setCountdownEnabled}
          aria-label="Toggle the 10-second undo countdown before sending"
          className="mt-0.5 shrink-0"
        />
      </div>
    </div>
  );
}
