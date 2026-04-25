"use client";

import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { STATUS_LABELS, CATEGORY_LABELS } from "@/lib/constants";
import type { EmailStatus, EmailCategory } from "@/lib/types";

interface EmailFiltersProps {
  status: string;
  category: string;
  clientEmail: string;
  assignedTo: string;
  onStatusChange: (v: string) => void;
  onCategoryChange: (v: string) => void;
  onClientEmailChange: (v: string) => void;
  onAssignedToChange: (v: string) => void;
  onClear: () => void;
}

const STATUS_OPTIONS = Object.entries(STATUS_LABELS) as [EmailStatus, string][];
const CATEGORY_OPTIONS = Object.entries(CATEGORY_LABELS) as [EmailCategory, string][];

export function EmailFilters({
  status,
  category,
  clientEmail,
  assignedTo,
  onStatusChange,
  onCategoryChange,
  onClientEmailChange,
  onAssignedToChange,
  onClear,
}: EmailFiltersProps) {
  // Local input state updates immediately for a responsive feel.
  // The parent callback (which triggers an API call) is debounced by 500ms.
  const [inputValue, setInputValue] = useState(clientEmail);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep local state in sync when the parent resets filters externally (e.g. "Clear").
  useEffect(() => {
    setInputValue(clientEmail);
  }, [clientEmail]);

  const handleEmailInput = (value: string) => {
    setInputValue(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onClientEmailChange(value);
    }, 500);
  };

  const hasFilters = !!status || !!category || !!clientEmail || !!assignedTo;

  return (
    <div className="flex flex-wrap items-center gap-3 mb-4">
      <Select value={status || "all"} onValueChange={(v: string | null) => onStatusChange(!v || v === "all" ? "" : v)}>
        <SelectTrigger className="w-[180px] h-9 text-sm">
          <SelectValue placeholder="All statuses" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All statuses</SelectItem>
          {STATUS_OPTIONS.map(([value, label]) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={category || "all"} onValueChange={(v: string | null) => onCategoryChange(!v || v === "all" ? "" : v)}>
        <SelectTrigger className="w-[180px] h-9 text-sm">
          <SelectValue placeholder="All categories" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All categories</SelectItem>
          {CATEGORY_OPTIONS.map(([value, label]) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Assigned-to filter */}
      <Select value={assignedTo || "all"} onValueChange={(v: string | null) => onAssignedToChange(!v || v === "all" ? "" : v)}>
        <SelectTrigger className="w-[160px] h-9 text-sm">
          <SelectValue placeholder="All assignees" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All assignees</SelectItem>
          <SelectItem value="me">Assigned to me</SelectItem>
        </SelectContent>
      </Select>

      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <Input
          value={inputValue}
          onChange={(e) => handleEmailInput(e.target.value)}
          placeholder="Filter by client email..."
          className="pl-8 w-[240px] h-9 text-sm"
        />
      </div>

      {hasFilters && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onClear}
          className="text-xs text-muted-foreground hover:text-foreground h-9"
        >
          <X className="w-3 h-3 mr-1" />
          Clear filters
        </Button>
      )}
    </div>
  );
}
