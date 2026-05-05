"use client"

import * as React from "react"
import { Select as SelectPrimitive } from "@base-ui/react/select"

import { cn } from "@/lib/utils"
import { ChevronDownIcon, CheckIcon, ChevronUpIcon } from "lucide-react"

// Base UI's <Select.Value/> resolves the displayed label from the `items` prop on
// <Select.Root/>. Without it, the trigger renders the raw value (e.g. "__all__"
// or "auth.login") instead of the human-readable label that lives inside
// <SelectItem>'s children. To keep call sites idiomatic ("just write the items
// inline") we walk the React children at render time and build a value→label
// map in a context that <SelectValue/> can read.
type SelectLabelMap = ReadonlyMap<unknown, React.ReactNode>

const SelectItemsContext = React.createContext<SelectLabelMap | null>(null)

function collectItemLabels(
  children: React.ReactNode,
  map: Map<unknown, React.ReactNode>,
): void {
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return
    const props = child.props as { value?: unknown; children?: React.ReactNode }
    // Any child that owns a `value` prop is treated as a leaf SelectItem.
    // Wrappers (SelectGroup, fragments, conditionals) just delegate to their
    // own children, so recursion handles arbitrary nesting.
    if ("value" in props && props.value !== undefined) {
      map.set(props.value, props.children)
    }
    if (props.children !== undefined) {
      collectItemLabels(props.children, map)
    }
  })
}

function Select<Value, Multiple extends boolean | undefined = false>({
  children,
  ...props
}: SelectPrimitive.Root.Props<Value, Multiple>) {
  const labelMap = React.useMemo(() => {
    const map = new Map<unknown, React.ReactNode>()
    collectItemLabels(children, map)
    return map
  }, [children])

  return (
    <SelectItemsContext.Provider value={labelMap}>
      <SelectPrimitive.Root {...props}>{children}</SelectPrimitive.Root>
    </SelectItemsContext.Provider>
  )
}

function SelectGroup({ className, ...props }: SelectPrimitive.Group.Props) {
  return (
    <SelectPrimitive.Group
      data-slot="select-group"
      className={cn("scroll-my-1", className)}
      {...props}
    />
  )
}

function SelectValue({
  className,
  placeholder,
  children: childrenProp,
  ...props
}: SelectPrimitive.Value.Props) {
  const labelMap = React.useContext(SelectItemsContext)

  // If the call site provided its own children (string, node, or render fn),
  // honor it — the wrapper's auto-resolution is purely a default.
  if (childrenProp !== undefined) {
    return (
      <SelectPrimitive.Value
        data-slot="select-value"
        className={cn("flex flex-1 text-left", className)}
        placeholder={placeholder}
        {...props}
      >
        {childrenProp}
      </SelectPrimitive.Value>
    )
  }

  return (
    <SelectPrimitive.Value
      data-slot="select-value"
      className={cn("flex flex-1 text-left", className)}
      placeholder={placeholder}
      {...props}
    >
      {(value: unknown) => {
        // No selection yet → defer to Base UI's built-in placeholder rendering.
        if (value == null || value === "") return placeholder
        if (labelMap?.has(value)) {
          const label = labelMap.get(value)
          // Empty/null label → fall back to the value so the trigger isn't blank.
          return label != null && label !== "" ? label : String(value)
        }
        return String(value)
      }}
    </SelectPrimitive.Value>
  )
}

function SelectTrigger({
  className,
  size = "default",
  children,
  ...props
}: SelectPrimitive.Trigger.Props & {
  size?: "sm" | "default"
}) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      data-size={size}
      className={cn(
        // Base shape
        "flex w-fit items-center justify-between gap-2 rounded-md border border-border bg-card text-sm whitespace-nowrap transition-colors outline-none select-none",
        // Sizing
        "data-[size=default]:h-9 data-[size=default]:px-3 data-[size=sm]:h-8 data-[size=sm]:px-2.5 data-[size=sm]:text-[13px]",
        // Hover / focus / open
        "hover:bg-accent/40 hover:border-foreground/20",
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
        "data-[popup-open]:bg-accent/40 data-[popup-open]:border-foreground/25",
        // Disabled
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-card disabled:hover:border-border",
        // Invalid
        "aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20",
        // Placeholder
        "data-[placeholder]:text-muted-foreground",
        // SelectValue line clamp
        "*:data-[slot=select-value]:line-clamp-1 *:data-[slot=select-value]:flex *:data-[slot=select-value]:items-center *:data-[slot=select-value]:gap-1.5",
        // Icons
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon
        render={
          <ChevronDownIcon
            className="pointer-events-none size-3.5 text-muted-foreground transition-transform group-data-[popup-open]:rotate-180"
            strokeWidth={1.75}
          />
        }
      />
    </SelectPrimitive.Trigger>
  )
}

function SelectContent({
  className,
  children,
  side = "bottom",
  sideOffset = 6,
  align = "center",
  alignOffset = 0,
  alignItemWithTrigger = true,
  ...props
}: SelectPrimitive.Popup.Props &
  Pick<
    SelectPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset" | "alignItemWithTrigger"
  >) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Positioner
        side={side}
        sideOffset={sideOffset}
        align={align}
        alignOffset={alignOffset}
        alignItemWithTrigger={alignItemWithTrigger}
        className="isolate z-50"
      >
        <SelectPrimitive.Popup
          data-slot="select-content"
          data-align-trigger={alignItemWithTrigger}
          className={cn(
            "relative isolate z-50 max-h-(--available-height) w-(--anchor-width) min-w-40 origin-(--transform-origin)",
            "overflow-x-hidden overflow-y-auto rounded-lg bg-popover p-1 text-popover-foreground shadow-lg ring-1 ring-border duration-100",
            // Animations
            "data-[align-trigger=true]:animate-none",
            "data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2",
            "data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2",
            "data-[side=inline-end]:slide-in-from-left-2 data-[side=inline-start]:slide-in-from-right-2",
            "data-[open]:animate-in data-[open]:fade-in-0 data-[open]:zoom-in-95",
            "data-[closed]:animate-out data-[closed]:fade-out-0 data-[closed]:zoom-out-95",
            className,
          )}
          {...props}
        >
          <SelectScrollUpButton />
          <SelectPrimitive.List>{children}</SelectPrimitive.List>
          <SelectScrollDownButton />
        </SelectPrimitive.Popup>
      </SelectPrimitive.Positioner>
    </SelectPrimitive.Portal>
  )
}

function SelectLabel({
  className,
  ...props
}: SelectPrimitive.GroupLabel.Props) {
  return (
    <SelectPrimitive.GroupLabel
      data-slot="select-label"
      className={cn(
        "px-2 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
        className,
      )}
      {...props}
    />
  )
}

function SelectItem({
  className,
  children,
  ...props
}: SelectPrimitive.Item.Props) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "relative flex w-full cursor-default items-center gap-2 rounded-md py-1.5 pl-2 pr-8 text-sm outline-none select-none transition-colors",
        "focus:bg-accent focus:text-accent-foreground",
        "data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
        "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        "*:[span]:last:flex *:[span]:last:items-center *:[span]:last:gap-2",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText className="flex flex-1 shrink-0 items-center gap-2 whitespace-nowrap">
        {children}
      </SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator
        render={
          <span className="pointer-events-none absolute right-2 flex size-4 items-center justify-center text-primary" />
        }
      >
        <CheckIcon strokeWidth={2.5} />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  )
}

function SelectSeparator({
  className,
  ...props
}: SelectPrimitive.Separator.Props) {
  return (
    <SelectPrimitive.Separator
      data-slot="select-separator"
      className={cn("pointer-events-none -mx-1 my-1 h-px bg-border/60", className)}
      {...props}
    />
  )
}

function SelectScrollUpButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>) {
  return (
    <SelectPrimitive.ScrollUpArrow
      data-slot="select-scroll-up-button"
      className={cn(
        "top-0 z-10 flex w-full cursor-default items-center justify-center bg-popover py-1 text-muted-foreground [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    >
      <ChevronUpIcon />
    </SelectPrimitive.ScrollUpArrow>
  )
}

function SelectScrollDownButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>) {
  return (
    <SelectPrimitive.ScrollDownArrow
      data-slot="select-scroll-down-button"
      className={cn(
        "bottom-0 z-10 flex w-full cursor-default items-center justify-center bg-popover py-1 text-muted-foreground [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    >
      <ChevronDownIcon />
    </SelectPrimitive.ScrollDownArrow>
  )
}

export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
}
