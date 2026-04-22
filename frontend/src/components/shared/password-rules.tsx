"use client";

import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PasswordRule {
  label: string;
  test: (value: string) => boolean;
}

export const PASSWORD_RULES: PasswordRule[] = [
  { label: "At least 8 characters", test: (v) => v.length >= 8 },
  { label: "At least one uppercase letter (A–Z)", test: (v) => /[A-Z]/.test(v) },
  { label: "At least one lowercase letter (a–z)", test: (v) => /[a-z]/.test(v) },
  { label: "At least one digit (0–9)", test: (v) => /[0-9]/.test(v) },
];

/**
 * Returns true only when every password rule passes for the given value.
 */
export function isPasswordValid(value: string): boolean {
  return PASSWORD_RULES.every((r) => r.test(value));
}

interface PasswordRulesProps {
  value: string;
  /** The HTML id to use for the list element (for aria-describedby linking) */
  id?: string;
}

/**
 * Live-validated password rules list.
 * - Each rule shows a green check when satisfied, red X when not.
 * - Renders nothing when value is empty.
 */
export function PasswordRules({ value, id = "password-rules" }: PasswordRulesProps) {
  if (!value) return null;

  return (
    <ul
      id={id}
      aria-live="polite"
      aria-label="Password requirements"
      className="mt-2 space-y-1"
    >
      {PASSWORD_RULES.map((rule) => {
        const passing = rule.test(value);
        return (
          <li key={rule.label} className="flex items-center gap-1.5">
            {passing ? (
              <Check className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" aria-hidden="true" />
            ) : (
              <X className="w-3.5 h-3.5 text-red-500 flex-shrink-0" aria-hidden="true" />
            )}
            <span
              className={cn(
                "text-xs",
                passing ? "text-emerald-700" : "text-red-600"
              )}
            >
              {rule.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
