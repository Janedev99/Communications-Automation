"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

const SEQUENCE = ["light", "dark", "system"] as const;
type Theme = (typeof SEQUENCE)[number];

const META: Record<Theme, { icon: typeof Sun; label: string }> = {
  light: { icon: Sun, label: "Light" },
  dark: { icon: Moon, label: "Dark" },
  system: { icon: Monitor, label: "System" },
};

interface ThemeToggleProps {
  collapsed?: boolean;
}

export function ThemeToggle({ collapsed }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // Reserve layout space until mount to avoid hydration mismatch
  if (!mounted) {
    return (
      <div
        aria-hidden
        className={cn(
          "h-7",
          collapsed ? "w-7 mx-auto" : "w-full"
        )}
      />
    );
  }

  const current = (SEQUENCE as readonly string[]).includes(theme ?? "")
    ? (theme as Theme)
    : "system";
  const { icon: Icon, label } = META[current];

  const next = () => {
    const idx = SEQUENCE.indexOf(current);
    setTheme(SEQUENCE[(idx + 1) % SEQUENCE.length]);
  };

  return (
    <button
      type="button"
      onClick={next}
      title={`Theme: ${label} (click to cycle)`}
      aria-label={`Switch theme. Current: ${label}`}
      className={cn(
        "flex items-center rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors duration-150 w-full",
        collapsed ? "justify-center py-1.5 px-0" : "gap-1.5 px-3 py-1.5"
      )}
    >
      <Icon className="w-4 h-4" strokeWidth={1.75} />
      {!collapsed && <span>{label}</span>}
    </button>
  );
}
