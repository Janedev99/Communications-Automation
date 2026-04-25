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
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {SHORTCUTS.map((section) => (
            <div key={section.category}>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                {section.category}
              </p>
              <div className="space-y-1.5">
                {section.items.map((item) => (
                  <div key={item.description} className="flex items-center justify-between gap-4">
                    <span className="text-sm text-muted-foreground">{item.description}</span>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {item.keys.map((key) => (
                        <kbd
                          key={key}
                          className="px-2 py-0.5 text-xs font-mono bg-muted border border-border rounded text-foreground"
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
