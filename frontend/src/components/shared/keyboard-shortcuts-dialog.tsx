"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface KeyboardShortcutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SHORTCUTS = [
  {
    category: "Navigation",
    items: [
      { keys: ["?"], description: "Show keyboard shortcuts" },
    ],
  },
  {
    category: "Email List",
    items: [
      { keys: ["j"], description: "Move selection down" },
      { keys: ["k"], description: "Move selection up" },
      { keys: ["Enter"], description: "Open selected thread" },
    ],
  },
  {
    category: "Thread Detail",
    items: [
      { keys: ["a"], description: "Approve draft" },
      { keys: ["r"], description: "Reject draft" },
    ],
  },
];

export function KeyboardShortcutsDialog({
  open,
  onOpenChange,
}: KeyboardShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
        </DialogHeader>
        <div className="space-y-5 -mx-1">
          {SHORTCUTS.map((section) => (
            <div key={section.category}>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 px-1">
                {section.category}
              </p>
              <div className="rounded-md border border-border bg-card divide-y divide-border/60 overflow-hidden">
                {section.items.map((item) => (
                  <div
                    key={item.description}
                    className="flex items-center justify-between gap-4 px-3 py-2"
                  >
                    <span className="text-sm text-foreground/90">{item.description}</span>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {item.keys.map((key) => (
                        <kbd
                          key={key}
                          className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 text-[11px] font-mono font-medium bg-muted text-foreground rounded ring-1 ring-border"
                        >
                          {key}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
