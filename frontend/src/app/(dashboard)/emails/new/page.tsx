"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { ComposeWorkspace } from "@/components/emails/compose-workspace";

/**
 * Full-page "New Email" compose. Replaces the old bottom-right floating dock so
 * composing happens in the same big workspace as replying (2026-07-10 ask).
 * Fills the content height (mirrors the thread-detail page's fill pattern) so
 * the body editor gets real room.
 */
export default function NewEmailPage() {
  const router = useRouter();

  const goToEmails = () => router.push("/emails");

  return (
    <div className="-m-4 lg:-m-6 p-4 lg:p-6 h-[calc(100dvh-56px)] flex flex-col">
      <div className="flex-shrink-0 mb-3">
        <Link
          href="/emails"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          Emails
        </Link>
      </div>
      <div className="flex-1 min-h-0">
        <ComposeWorkspace onSent={goToEmails} onCancel={goToEmails} />
      </div>
    </div>
  );
}
