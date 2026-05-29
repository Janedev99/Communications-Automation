"use client";

/**
 * Per-user, browser-local preferences.
 *
 * These are deliberately client-only (localStorage) — they tune UI behaviour
 * for the person at this browser and never need to reach the server. Keys use
 * the app-wide `jane_` prefix (see e.g. `jane_sidebar_last_seen`).
 */
import { useCallback, useEffect, useState } from "react";

const SEND_COUNTDOWN_KEY = "jane_send_countdown_enabled";

// Same-tab change signal. The native `storage` event only fires in OTHER tabs,
// so we dispatch this to keep components in the current tab in sync too.
const PREF_CHANGED_EVENT = "jane:pref-changed";

/**
 * Whether the 10-second undo countdown runs after the user confirms Send.
 * Defaults to ON (true) when unset — the safe default keeps the undo window.
 */
export function getSendCountdownEnabled(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(SEND_COUNTDOWN_KEY) !== "false";
}

function writeSendCountdownEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SEND_COUNTDOWN_KEY, enabled ? "true" : "false");
  window.dispatchEvent(new Event(PREF_CHANGED_EVENT));
}

/**
 * React binding for the send-countdown preference. Returns the current value
 * and a setter, kept in sync across components in this tab (custom event) and
 * across other tabs (the native `storage` event).
 *
 * Initial render returns the safe default (true); the stored value is read
 * after mount to avoid an SSR/client hydration mismatch.
 */
export function useSendCountdownEnabled(): readonly [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabledState] = useState<boolean>(true);

  useEffect(() => {
    const sync = () => setEnabledState(getSendCountdownEnabled());
    sync(); // hydrate from storage on mount
    window.addEventListener(PREF_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PREF_CHANGED_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const setEnabled = useCallback((next: boolean) => {
    writeSendCountdownEnabled(next);
    setEnabledState(next);
  }, []);

  return [enabled, setEnabled] as const;
}
