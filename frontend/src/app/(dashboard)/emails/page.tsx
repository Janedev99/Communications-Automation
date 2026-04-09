"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { EmailFilters } from "@/components/emails/email-filters";
import { EmailList } from "@/components/emails/email-list";
import { Pagination } from "@/components/shared/pagination";
import { TableSkeleton } from "@/components/shared/loading-skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { useEmails } from "@/hooks/use-emails";

export default function EmailsPage() {
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [page, setPage] = useState(1);

  const { threads, total, isLoading, isError, mutate } = useEmails({
    status: status || undefined,
    category: category || undefined,
    client_email: clientEmail || undefined,
    page,
    page_size: 25,
  });

  const handleClear = () => {
    setStatus("");
    setCategory("");
    setClientEmail("");
    setPage(1);
  };

  const handleFilterChange = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(1);
  };

  return (
    <div>
      <PageHeader
        title="Emails"
        subtitle="Manage email threads and responses"
      />

      <EmailFilters
        status={status}
        category={category}
        clientEmail={clientEmail}
        onStatusChange={handleFilterChange(setStatus)}
        onCategoryChange={handleFilterChange(setCategory)}
        onClientEmailChange={handleFilterChange(setClientEmail)}
        onClear={handleClear}
      />

      {isError ? (
        <ErrorState
          title="Failed to load emails"
          description="Could not retrieve email threads. Please try again."
          onRetry={mutate}
        />
      ) : isLoading ? (
        <TableSkeleton rows={8} />
      ) : (
        <>
          <EmailList threads={threads} />
          <Pagination
            page={page}
            pageSize={25}
            total={total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
