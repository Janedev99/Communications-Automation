import { cn } from "@/lib/utils";

interface AlphaBadgeProps {
  variant?: "pill" | "dot";
  className?: string;
}

export function AlphaBadge({ variant = "pill", className }: AlphaBadgeProps) {
  if (variant === "dot") {
    return (
      <span
        role="status"
        aria-label="Alpha — in development"
        title="Alpha — in development"
        className={cn(
          "absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-amber-500 ring-2 ring-background",
          className,
        )}
      />
    );
  }

  return (
    <span
      role="status"
      aria-label="Alpha — in development"
      title="Alpha — in development"
      className={cn(
        "inline-flex items-center px-1.5 py-px rounded text-[9px] font-semibold uppercase tracking-widest leading-none",
        "bg-amber-500/15 text-amber-700 dark:text-amber-400 ring-1 ring-amber-500/30",
        className,
      )}
    >
      Alpha
    </span>
  );
}
