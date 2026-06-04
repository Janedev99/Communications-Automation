"""Pydantic schemas for the Analytics page (GET /api/v1/analytics)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DailyTokens(BaseModel):
    date: date
    input_tokens: int
    output_tokens: int


class TokenUsageSection(BaseModel):
    daily: list[DailyTokens]            # one entry per day, zero-filled
    today_input_tokens: int
    today_output_tokens: int
    daily_budget: int                   # 0 = unlimited
    budget_exhausted_days: int          # days in range where usage >= budget


class DailyCount(BaseModel):
    date: date
    count: int


class EmailVolumeSection(BaseModel):
    threads_per_day: list[DailyCount]   # zero-filled
    by_category: dict[str, int]
    by_tier: dict[str, int]
    total_threads: int


class DraftWorkflowSection(BaseModel):
    by_status: dict[str, int]
    total: int
    edited_count: int                   # drafts staff modified before sending
    sent_count: int
    rejected_count: int


class EscalationsSection(BaseModel):
    created_per_day: list[DailyCount]   # zero-filled
    by_severity: dict[str, int]
    by_status: dict[str, int]
    open_count: int                     # pending + acknowledged, all-time


class AnalyticsResponse(BaseModel):
    days: int                           # the range actually applied
    start_date: date
    token_usage: TokenUsageSection
    email_volume: EmailVolumeSection
    draft_workflow: DraftWorkflowSection
    escalations: EscalationsSection
