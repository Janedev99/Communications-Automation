"""
Tests for GET /api/v1/analytics — the read-only aggregates behind the
Analytics page (token usage vs budget, email volume, draft workflow,
escalations).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.ai_budget import AIBudgetUsage
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailStatus,
    EmailThread,
    ThreadTier,
)
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus


def _seed_thread(db, *, category=EmailCategory.general_inquiry, tier=ThreadTier.t2_review):
    thread = EmailThread(
        id=uuid.uuid4(),
        subject=f"Analytics seed {uuid.uuid4().hex[:6]}",
        client_email=f"client-{uuid.uuid4().hex[:6]}@example.com",
        status=EmailStatus.categorized,
        category=category,
        tier=tier,
    )
    db.add(thread)
    db.flush()
    return thread


def test_analytics_requires_auth(app_instance):
    from fastapi.testclient import TestClient

    anon = TestClient(app_instance)
    assert anon.get("/api/v1/analytics").status_code == 401


def test_analytics_shape_and_zero_fill(logged_in_staff):
    """All four sections present; daily series are zero-filled to the full
    window so charts never gap."""
    resp = logged_in_staff.get("/api/v1/analytics?days=14")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["days"] == 14
    assert {"token_usage", "email_volume", "draft_workflow", "escalations"} <= body.keys()
    # Zero-filled series span exactly the window, ending today.
    assert len(body["token_usage"]["daily"]) == 14
    assert len(body["email_volume"]["threads_per_day"]) == 14
    assert len(body["escalations"]["created_per_day"]) == 14
    assert body["token_usage"]["daily"][-1]["date"] == date.today().isoformat()


def test_analytics_days_param_is_clamped(logged_in_staff):
    assert logged_in_staff.get("/api/v1/analytics?days=3").status_code == 422
    assert logged_in_staff.get("/api/v1/analytics?days=9999").status_code == 422


def test_token_usage_reflects_budget_rows(logged_in_staff, db_session):
    today = date.today()
    db_session.merge(AIBudgetUsage(date=today, input_tokens=1000, output_tokens=250))
    db_session.merge(
        AIBudgetUsage(
            date=today - timedelta(days=1), input_tokens=999_999, output_tokens=999_999
        )
    )
    db_session.commit()

    body = logged_in_staff.get("/api/v1/analytics?days=7").json()
    tu = body["token_usage"]
    assert tu["today_input_tokens"] == 1000
    assert tu["today_output_tokens"] == 250
    assert tu["daily_budget"] > 0
    # Yesterday blew past the 1M default budget → counted as exhausted.
    assert tu["budget_exhausted_days"] >= 1
    yesterday_entry = next(
        d for d in tu["daily"]
        if d["date"] == (today - timedelta(days=1)).isoformat()
    )
    assert yesterday_entry["input_tokens"] == 999_999


def test_email_volume_counts_categories_and_tiers(logged_in_staff, db_session):
    _seed_thread(db_session, category=EmailCategory.appointment, tier=ThreadTier.t1_auto)
    _seed_thread(db_session, category=EmailCategory.appointment)
    db_session.commit()

    body = logged_in_staff.get("/api/v1/analytics?days=7").json()
    ev = body["email_volume"]
    assert ev["by_category"].get("appointment", 0) >= 2
    assert ev["by_tier"].get("t1_auto", 0) >= 1
    assert ev["total_threads"] >= 2
    # today's bucket includes the freshly created threads
    assert ev["threads_per_day"][-1]["count"] >= 2


def test_draft_workflow_counts_edits_and_rejections(logged_in_staff, db_session):
    thread = _seed_thread(db_session)
    db_session.add_all([
        DraftResponse(
            thread_id=thread.id,
            body_text="Edited final text.",
            original_body_text="Original AI text.",
            status=DraftStatus.sent,
        ),
        DraftResponse(
            thread_id=thread.id,
            body_text="Rejected text.",
            status=DraftStatus.rejected,
            rejection_reason="tone off",
        ),
    ])
    db_session.commit()

    body = logged_in_staff.get("/api/v1/analytics?days=7").json()
    dw = body["draft_workflow"]
    assert dw["edited_count"] >= 1
    assert dw["rejected_count"] >= 1
    assert dw["sent_count"] >= 1
    assert dw["total"] >= 2
    assert dw["by_status"].get("sent", 0) >= 1


def test_escalations_open_count_is_all_time(logged_in_staff, db_session):
    thread = _seed_thread(db_session, category=EmailCategory.complaint)
    db_session.add(
        Escalation(
            id=uuid.uuid4(),
            thread_id=thread.id,
            reason="Client complaint",
            severity=EscalationSeverity.high,
            status=EscalationStatus.pending,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    body = logged_in_staff.get("/api/v1/analytics?days=7").json()
    es = body["escalations"]
    assert es["open_count"] >= 1
    assert es["by_severity"].get("high", 0) >= 1
    assert es["created_per_day"][-1]["count"] >= 1
