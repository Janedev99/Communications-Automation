"use client";

import { useEffect, useMemo, useState } from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  Info,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  INTEGRATION_GUIDES,
  type GuideStep,
  type IntegrationGuide,
  type IntegrationGuideId,
} from "@/lib/integration-guides";

interface Props {
  guideId: IntegrationGuideId | null;
  defaultPathId?: string;
  onClose: () => void;
}

export function SetupGuideDialog({ guideId, defaultPathId, onClose }: Props) {
  const guide = guideId ? INTEGRATION_GUIDES[guideId] : null;

  return (
    <DialogPrimitive.Root open={guideId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className={cn(
            "fixed inset-0 z-50 bg-black/30 backdrop-blur-sm",
            "data-open:animate-in data-open:fade-in-0",
            "data-closed:animate-out data-closed:fade-out-0",
          )}
        />
        <DialogPrimitive.Popup
          className={cn(
            "fixed top-0 right-0 bottom-0 z-50 flex w-full flex-col bg-card text-foreground shadow-xl outline-none ring-1 ring-border",
            "sm:max-w-[560px]",
            "data-open:animate-in data-open:slide-in-from-right data-open:duration-200",
            "data-closed:animate-out data-closed:slide-out-to-right data-closed:duration-150",
          )}
        >
          {guide && <GuideBody guide={guide} defaultPathId={defaultPathId} />}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function GuideBody({
  guide,
  defaultPathId,
}: {
  guide: IntegrationGuide;
  defaultPathId?: string;
}) {
  const initialPath = useMemo(() => {
    if (!guide.paths) return null;
    return (
      guide.paths.find((p) => p.id === defaultPathId)?.id ?? guide.paths[0].id
    );
  }, [guide, defaultPathId]);

  const [activePath, setActivePath] = useState<string | null>(initialPath);

  useEffect(() => {
    setActivePath(initialPath);
  }, [initialPath]);

  const activePathSteps =
    guide.paths?.find((p) => p.id === activePath)?.steps ?? guide.steps ?? [];

  return (
    <>
      {/* Header */}
      <div className="flex items-start justify-between gap-3 border-b border-border px-6 py-5">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Setup guide
          </p>
          <DialogPrimitive.Title className="mt-1 text-lg font-semibold leading-tight">
            {guide.title}
          </DialogPrimitive.Title>
        </div>
        <DialogPrimitive.Close
          render={
            <Button variant="ghost" size="icon-sm" aria-label="Close setup guide" />
          }
        >
          <X className="h-4 w-4" />
        </DialogPrimitive.Close>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <DialogPrimitive.Description className="text-sm leading-relaxed text-foreground/80">
          {guide.intro}
        </DialogPrimitive.Description>

        {guide.whoSetsThisUp && (
          <div className="mt-4 flex gap-2.5 rounded-md border border-border bg-muted/40 p-3">
            <Info
              className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
              strokeWidth={1.75}
            />
            <p className="text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground">Who sets this up: </span>
              {guide.whoSetsThisUp}
            </p>
          </div>
        )}

        {/* Path tabs (email provider only) */}
        {guide.paths && activePath && (
          <Tabs
            value={activePath}
            onValueChange={(v) => setActivePath(v as string)}
            className="mt-6"
          >
            <TabsList className="w-full">
              {guide.paths.map((p) => (
                <TabsTrigger key={p.id} value={p.id}>
                  {p.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {guide.paths.map((p) => (
              <TabsContent key={p.id} value={p.id} className="pt-4">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {p.description}
                </p>
              </TabsContent>
            ))}
          </Tabs>
        )}

        {/* Steps */}
        <ol className="mt-6 space-y-5">
          {activePathSteps.map((step, idx) => (
            <StepRow key={`${activePath ?? "single"}-${idx}`} step={step} index={idx} />
          ))}
        </ol>

        {/* Verify */}
        <div className="mt-8 flex gap-2.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3">
          <CheckCircle2
            className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
            strokeWidth={1.75}
          />
          <div className="text-xs leading-relaxed text-foreground">
            <p className="font-medium text-emerald-700 dark:text-emerald-300">
              How to verify it&rsquo;s working
            </p>
            <p className="mt-1 text-foreground/80">{guide.verify}</p>
          </div>
        </div>

        {/* Common issues */}
        {guide.commonIssues.length > 0 && (
          <div className="mt-8">
            <h3 className="text-sm font-semibold text-foreground">Common issues</h3>
            <ul className="mt-3 space-y-3">
              {guide.commonIssues.map((issue, idx) => (
                <li
                  key={idx}
                  className="rounded-md border border-border bg-muted/30 p-3"
                >
                  <div className="flex items-start gap-2">
                    <AlertCircle
                      className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
                      strokeWidth={1.75}
                    />
                    <div className="text-xs leading-relaxed">
                      <p className="font-medium text-foreground">{issue.problem}</p>
                      <p className="mt-1 text-muted-foreground">{issue.fix}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

      </div>
    </>
  );
}

function StepRow({ step, index }: { step: GuideStep; index: number }) {
  return (
    <li className="flex gap-4">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
        {index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <h4 className="text-sm font-semibold leading-snug text-foreground">
          {step.title}
        </h4>
        <p className="mt-1 text-sm leading-relaxed text-foreground/80">{step.body}</p>

        {step.envVar && (
          <CopyEnvRow name={step.envVar} example={step.envExample} />
        )}
        {step.code && <CodeBlock code={step.code} />}
        {step.link && (
          <a
            href={step.link.href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
          >
            {step.link.label}
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
        {step.note && (
          <p className="mt-3 text-xs italic text-muted-foreground">{step.note}</p>
        )}
      </div>
    </li>
  );
}

function CopyEnvRow({ name, example }: { name: string; example?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(name);
      setCopied(true);
      toast.success(`Copied ${name}`);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — copy it manually.");
    }
  };

  return (
    <div className="mt-3 rounded-md border border-border bg-muted/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <code className="font-mono text-xs font-semibold text-foreground">
          {name}
        </code>
        <Button
          variant="ghost"
          size="xs"
          onClick={handleCopy}
          aria-label={`Copy ${name}`}
        >
          {copied ? (
            <Check className="h-3 w-3" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      {example && (
        <p className="mt-1.5 truncate font-mono text-[11px] text-muted-foreground">
          Example: {example}
        </p>
      )}
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success("Copied configuration block");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — copy it manually.");
    }
  };

  return (
    <div className="mt-3 overflow-hidden rounded-md border border-border bg-muted/60">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
        <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Environment variables
        </span>
        <Button variant="ghost" size="xs" onClick={handleCopy} aria-label="Copy block">
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[11px] leading-relaxed text-foreground">
        {code}
      </pre>
    </div>
  );
}
