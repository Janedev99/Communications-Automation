"use client";

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
  onStatusChange: (v: string) => void;
  onCategoryChange: (v: string) => void;
  onClientEmailChange: (v: string) => void;
  onClear: () => void;
}

const STATUS_OPTIONS = Object.entries(STATUS_LABELS) as [EmailStatus, string][];
const CATEGORY_OPTIONS = Object.entries(CATEGORY_LABELS) as [EmailCategory, string][];

export function EmailFilters({
  status,
  category,
  clientEmail,
  onStatusChange,
  onCategoryChange,
  onClientEmailChange,
  onClear,
}: EmailFiltersProps) {
  const hasFilters = !!status || !!category || !!clientEmail;

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

      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <Input
          value={clientEmail}
          onChange={(e) => onClientEmailChange(e.target.value)}
          placeholder="Search by client email..."
          className="pl-8 w-[260px] h-9 text-sm"
        />
      </div>

      {hasFilters && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onClear}
          className="text-xs text-gray-500 hover:text-gray-700 h-9"
        >
          <X className="w-3 h-3 mr-1" />
          Clear filters
        </Button>
      )}
    </div>
  );
}
