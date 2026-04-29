"use client"

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn(
        "group/tabs flex gap-2 data-[orientation=horizontal]:flex-col",
        className,
      )}
      {...props}
    />
  )
}

const tabsListVariants = cva(
  "group/tabs-list inline-flex items-center gap-0.5 rounded-lg p-1 text-muted-foreground group-data-[orientation=horizontal]/tabs:h-9 group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col data-[variant=line]:rounded-none data-[variant=line]:p-0 data-[variant=line]:gap-0",
  {
    variants: {
      variant: {
        default: "bg-muted/60 ring-1 ring-border",
        line: "border-b border-border bg-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

function TabsList({
  className,
  variant = "default",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        // Base
        "relative inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-3 py-1 text-sm font-medium whitespace-nowrap transition-all outline-none select-none",
        "text-muted-foreground hover:text-foreground",
        "focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-1 focus-visible:ring-offset-background",
        "disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50",
        // Vertical orientation tweaks
        "group-data-[orientation=vertical]/tabs:w-full group-data-[orientation=vertical]/tabs:justify-start",
        // Default variant: pill with bg + soft shadow on active
        "group-data-[variant=default]/tabs-list:data-[active]:bg-card group-data-[variant=default]/tabs-list:data-[active]:text-foreground group-data-[variant=default]/tabs-list:data-[active]:shadow-sm group-data-[variant=default]/tabs-list:data-[active]:ring-1 group-data-[variant=default]/tabs-list:data-[active]:ring-border",
        // Line variant: underline indicator on active
        "group-data-[variant=line]/tabs-list:rounded-none group-data-[variant=line]/tabs-list:px-3 group-data-[variant=line]/tabs-list:py-2.5 group-data-[variant=line]/tabs-list:data-[active]:text-foreground",
        // Icons
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        // Bottom underline indicator (line variant)
        "after:absolute after:bg-primary after:opacity-0 after:transition-opacity",
        "group-data-[orientation=horizontal]/tabs:after:inset-x-3 group-data-[orientation=horizontal]/tabs:after:bottom-0 group-data-[orientation=horizontal]/tabs:after:h-0.5",
        "group-data-[orientation=vertical]/tabs:after:inset-y-1.5 group-data-[orientation=vertical]/tabs:after:right-0 group-data-[orientation=vertical]/tabs:after:w-0.5",
        "group-data-[variant=line]/tabs-list:data-[active]:after:opacity-100",
        className,
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("flex-1 text-sm outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
