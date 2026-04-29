import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        // Base shape — matches the Select trigger so form controls feel like one family
        "h-9 w-full min-w-0 rounded-md border border-border bg-card px-3 py-1 text-sm transition-colors outline-none",
        // file inputs
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
        // placeholder
        "placeholder:text-muted-foreground",
        // hover
        "hover:border-foreground/20",
        // focus
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
        // disabled
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-muted/40 disabled:opacity-60",
        // invalid
        "aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/30",
        className,
      )}
      {...props}
    />
  )
}

export { Input }
