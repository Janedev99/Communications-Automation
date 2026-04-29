import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        // Base — matches Input + Select trigger
        "flex field-sizing-content min-h-20 w-full rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors outline-none",
        // placeholder
        "placeholder:text-muted-foreground",
        // hover
        "hover:border-foreground/20",
        // focus
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
        // disabled
        "disabled:cursor-not-allowed disabled:bg-muted/40 disabled:opacity-60",
        // invalid
        "aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/30",
        className,
      )}
      {...props}
    />
  )
}

export { Textarea }
