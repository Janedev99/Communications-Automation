"""
Unit tests for app.services.runpod_orchestrator.

Strategy:
  - `enabled_orchestrator` fixture sets RUNPOD_POD_ID / LLM_BASE_URL /
    LLM_API_KEY / LLM_MODEL via monkeypatch, clears the settings cache,
    and rebuilds the orchestrator singleton with those values. Tear-down
    resets everything so the next test starts clean.
  - `runpod_client` is mocked at module level so no real HTTP happens.
  - Each test exercises one state-machine path; assertions check both
    the RunPodState DB row AND the calls that should/shouldn't have
    happened.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.runpod_state import RunPodState


# ── Fixture: enabled orchestrator ─────────────────────────────────────────────


@pytest.fixture
def enabled_orchestrator(monkeypatch, db_session):
    """Configure env so the orchestrator manages a (fake) pod, with cleanup.

    The conftest's shared SQLite DB persists rows across tests — so we delete
    any leftover runpod_state rows before AND after each test. Without that,
    the pod_id PK collides on the second test that uses this fixture.
    """
    # Purge any leftover state from previous tests
    db_session.query(RunPodState).delete()
    db_session.commit()

    monkeypatch.setenv("RUNPOD_POD_ID", "test-pod-id")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv(
        "LLM_BASE_URL", "https://test-pod-8000.proxy.runpod.net/v1"
    )
    monkeypatch.setenv("LLM_MODEL", "test/model")

    from app.config import get_settings
    get_settings.cache_clear()

    from app.services.runpod_orchestrator import (
        get_runpod_orchestrator,
        reset_runpod_orchestrator,
    )
    reset_runpod_orchestrator()
    orchestrator = get_runpod_orchestrator()
    assert orchestrator.enabled, "fixture failed to enable orchestration"

    yield orchestrator

    reset_runpod_orchestrator()
    get_settings.cache_clear()
    db_session.query(RunPodState).delete()
    db_session.commit()


# ── ensure_ready: disabled mode ──────────────────────────────────────────────


def test_ensure_ready_disabled_returns_base_url_no_api_calls(db_session: Session):
    """Disabled orchestrator returns base_url and never touches RunPod."""
    from app.services.runpod_orchestrator import (
        get_runpod_orchestrator,
        reset_runpod_orchestrator,
    )
    reset_runpod_orchestrator()
    orchestrator = get_runpod_orchestrator()
    assert not orchestrator.enabled

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        url = orchestrator.ensure_ready(db_session)

    # In test conftest LLM_BASE_URL is "" — disabled mode returns whatever is configured
    assert url == ""
    mock_client.fetch_pod.assert_not_called()
    mock_client.start_pod.assert_not_called()


# ── ensure_ready: hot path ───────────────────────────────────────────────────


def test_ensure_ready_running_and_healthy_fast_returns(db_session, enabled_orchestrator):
    """Pod RUNNING + vLLM healthy → fast return, only fetch_pod + list_models called."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "RUNNING"}
        mock_client.list_models.return_value = ["test/model"]

        url = enabled_orchestrator.ensure_ready(db_session)

    assert url == "https://test-pod-8000.proxy.runpod.net/v1"
    mock_client.start_pod.assert_not_called()
    mock_client.wait_for_running.assert_not_called()
    mock_client.probe_vllm.assert_not_called()

    state = db_session.query(RunPodState).filter_by(pod_id="test-pod-id").one()
    assert state.last_known_state == "RUNNING"
    assert state.last_used_at is not None


# ── ensure_ready: cold path ──────────────────────────────────────────────────


def test_ensure_ready_exited_starts_waits_probes(db_session, enabled_orchestrator):
    """EXITED pod → start_pod + wait_for_running + probe_vllm → state RUNNING."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.return_value = True
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = True

        url = enabled_orchestrator.ensure_ready(db_session)

    assert url == "https://test-pod-8000.proxy.runpod.net/v1"
    mock_client.start_pod.assert_called_once()
    mock_client.wait_for_running.assert_called_once()
    mock_client.probe_vllm.assert_called_once()

    state = db_session.query(RunPodState).filter_by(pod_id="test-pod-id").one()
    assert state.last_known_state == "RUNNING"
    assert state.last_started_at is not None
    assert state.last_used_at is not None


# ── ensure_ready: unhealthy RUNNING → cycle ──────────────────────────────────


def test_ensure_ready_running_but_unhealthy_cycles_stop_start(
    db_session, enabled_orchestrator
):
    """RUNNING per RunPod but list_models fails → stop + start cycle."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "RUNNING"}
        mock_client.list_models.return_value = None  # vLLM dead inside container
        mock_client.stop_pod.return_value = True
        mock_client.start_pod.return_value = True
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = True

        enabled_orchestrator.ensure_ready(db_session)

    mock_client.stop_pod.assert_called_once()
    mock_client.start_pod.assert_called_once()


# ── ensure_ready: failure cases all raise RunPodUnavailableError ─────────────


def test_ensure_ready_daily_cap_reached_raises(db_session, enabled_orchestrator):
    """uptime_today_seconds >= cap → RunPodUnavailableError, no API calls."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    state = RunPodState(
        pod_id="test-pod-id",
        uptime_today_seconds=11 * 3600,  # 11h > 10h cap
        uptime_day_utc=datetime.now(timezone.utc).date(),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        with pytest.raises(RunPodUnavailableError, match="daily_cap_reached"):
            enabled_orchestrator.ensure_ready(db_session)
    mock_client.start_pod.assert_not_called()


def test_ensure_ready_pod_missing_raises(db_session, enabled_orchestrator):
    """fetch_pod returns None → RunPodUnavailableError (pod externally terminated)."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = None
        with pytest.raises(RunPodUnavailableError, match="not found"):
            enabled_orchestrator.ensure_ready(db_session)


def test_ensure_ready_start_failure_raises(db_session, enabled_orchestrator):
    """start_pod returns False → RunPodUnavailableError."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.return_value = False
        # New: failure surfaces as terminal_state=START_FAILED from the
        # background-start path (refactor for fast-fail mode).
        with pytest.raises(RunPodUnavailableError, match="terminal_state=START_FAILED"):
            enabled_orchestrator.ensure_ready(db_session)


def test_ensure_ready_wait_timeout_raises(db_session, enabled_orchestrator):
    """wait_for_running times out → RunPodUnavailableError."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.return_value = True
        mock_client.wait_for_running.return_value = None  # timeout
        # New: wait_for_running returning None surfaces as terminal_state=FAILED_START
        with pytest.raises(RunPodUnavailableError, match="terminal_state=FAILED_START"):
            enabled_orchestrator.ensure_ready(db_session)


def test_ensure_ready_probe_failure_raises(db_session, enabled_orchestrator):
    """probe_vllm returns False after start → RunPodUnavailableError."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.return_value = True
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = False
        # New: probe failure surfaces as terminal_state=UNHEALTHY
        with pytest.raises(RunPodUnavailableError, match="terminal_state=UNHEALTHY"):
            enabled_orchestrator.ensure_ready(db_session)


# ── mark_used ────────────────────────────────────────────────────────────────


def test_mark_used_bumps_last_used_at(db_session, enabled_orchestrator):
    """mark_used updates last_used_at to a recent timestamp."""
    enabled_orchestrator.mark_used(db_session)
    state = db_session.query(RunPodState).filter_by(pod_id="test-pod-id").one()
    assert state.last_used_at is not None
    # SQLite strips tzinfo on read-back; coerce both sides to naive UTC for comparison.
    last_used_naive = state.last_used_at.replace(tzinfo=None)
    delta = datetime.utcnow() - last_used_naive
    assert delta.total_seconds() < 5


def test_mark_used_when_disabled_is_noop(db_session):
    """Disabled orchestrator's mark_used inserts no rows."""
    from app.services.runpod_orchestrator import (
        get_runpod_orchestrator,
        reset_runpod_orchestrator,
    )
    reset_runpod_orchestrator()
    orchestrator = get_runpod_orchestrator()
    orchestrator.mark_used(db_session)
    assert db_session.query(RunPodState).count() == 0


# ── stop_if_idle ─────────────────────────────────────────────────────────────


def test_stop_if_idle_recent_use_does_nothing(db_session, enabled_orchestrator):
    """Pod RUNNING + last_used_at recent → no stop call."""
    now = datetime.now(timezone.utc)
    state = RunPodState(
        pod_id="test-pod-id",
        last_known_state="RUNNING",
        last_started_at=now - timedelta(seconds=30),
        last_used_at=now - timedelta(seconds=30),  # very recent
        uptime_today_seconds=0,
        uptime_day_utc=datetime.now(timezone.utc).date(),
        updated_at=now,
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        result = enabled_orchestrator.stop_if_idle(db_session)
    assert result is False
    mock_client.stop_pod.assert_not_called()


def test_stop_if_idle_idle_stops_and_accumulates_uptime(
    db_session, enabled_orchestrator
):
    """Idle > threshold → stop_pod called + session uptime added to daily counter."""
    now = datetime.now(timezone.utc)
    state = RunPodState(
        pod_id="test-pod-id",
        last_known_state="RUNNING",
        last_started_at=now - timedelta(seconds=900),  # 15 min session
        last_used_at=now - timedelta(seconds=600),  # 10 min idle
        uptime_today_seconds=0,
        uptime_day_utc=datetime.now(timezone.utc).date(),
        updated_at=now,
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.stop_pod.return_value = True
        result = enabled_orchestrator.stop_if_idle(db_session)
    assert result is True
    mock_client.stop_pod.assert_called_once()

    db_session.refresh(state)
    assert state.last_known_state == "EXITED"
    assert state.last_started_at is None  # session ended
    # Accumulated ~900s — allow some slack for test timing.
    assert state.uptime_today_seconds >= 850


def test_stop_if_idle_already_exited_does_nothing(db_session, enabled_orchestrator):
    """last_known_state=EXITED → stop_if_idle is a no-op."""
    state = RunPodState(
        pod_id="test-pod-id",
        last_known_state="EXITED",
        uptime_today_seconds=0,
        uptime_day_utc=datetime.now(timezone.utc).date(),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        result = enabled_orchestrator.stop_if_idle(db_session)
    assert result is False
    mock_client.stop_pod.assert_not_called()


def test_stop_if_idle_stop_failure_keeps_state_running(
    db_session, enabled_orchestrator
):
    """stop_pod returns False → state stays RUNNING (retry next tick), no uptime added."""
    now = datetime.now(timezone.utc)
    state = RunPodState(
        pod_id="test-pod-id",
        last_known_state="RUNNING",
        last_started_at=now - timedelta(seconds=900),
        last_used_at=now - timedelta(seconds=600),
        uptime_today_seconds=0,
        uptime_day_utc=datetime.now(timezone.utc).date(),
        updated_at=now,
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.stop_pod.return_value = False  # stop refused
        result = enabled_orchestrator.stop_if_idle(db_session)
    assert result is True  # we tried
    db_session.refresh(state)
    assert state.last_known_state == "RUNNING"  # unchanged
    assert state.uptime_today_seconds == 0  # not accounted (stop failed)


# ── daily counter rollover ───────────────────────────────────────────────────


def test_daily_counter_rolls_over_at_midnight_utc(db_session, enabled_orchestrator):
    """uptime_day_utc != today → reset to 0 on next access."""
    today_utc = datetime.now(timezone.utc).date()
    yesterday_utc = today_utc - timedelta(days=1)
    state = RunPodState(
        pod_id="test-pod-id",
        last_known_state="RUNNING",
        last_started_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        last_used_at=datetime.now(timezone.utc),
        uptime_today_seconds=8 * 3600,  # 8h from yesterday
        uptime_day_utc=yesterday_utc,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "RUNNING"}
        mock_client.list_models.return_value = ["test/model"]
        enabled_orchestrator.ensure_ready(db_session)

    db_session.refresh(state)
    assert state.uptime_day_utc == today_utc
    assert state.uptime_today_seconds == 0


# ── status_snapshot ──────────────────────────────────────────────────────────


def test_status_snapshot_disabled_returns_enabled_false(db_session):
    """Disabled orchestrator status_snapshot is the canonical {enabled: False}."""
    from app.services.runpod_orchestrator import (
        get_runpod_orchestrator,
        reset_runpod_orchestrator,
    )
    reset_runpod_orchestrator()
    orchestrator = get_runpod_orchestrator()
    assert orchestrator.status_snapshot(db_session) == {"enabled": False}


def test_status_snapshot_enabled_returns_full_state(db_session, enabled_orchestrator):
    """Enabled orchestrator status_snapshot includes pod_id, caps, and counters."""
    snap = enabled_orchestrator.status_snapshot(db_session)
    assert snap["enabled"] is True
    assert snap["pod_id"] == "test-pod-id"
    assert snap["daily_cap_seconds"] == 10 * 3600
    assert snap["idle_timeout_seconds"] == 300
    assert "daily_cap_remaining_seconds" in snap


# ── wake_async ───────────────────────────────────────────────────────────────


def _wait_for_bg_thread(orchestrator, timeout: float = 5.0) -> None:
    """Wait for any background-start thread to finish.

    Avoids flakiness: tests that mock runpod_client need the bg thread to
    finish *within* the patch context, otherwise the next test's patch
    catches stale invocations.
    """
    orchestrator._start_completed.wait(timeout=timeout)


def test_wake_async_disabled_returns_disabled(db_session: Session):
    from app.services.runpod_orchestrator import (
        get_runpod_orchestrator,
        reset_runpod_orchestrator,
    )
    reset_runpod_orchestrator()
    orchestrator = get_runpod_orchestrator()
    assert orchestrator.wake_async(db_session) == {"status": "disabled"}


def test_wake_async_running_and_healthy_returns_ready(db_session, enabled_orchestrator):
    """Pod already RUNNING + healthy → no bg start, status=ready."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "RUNNING"}
        mock_client.list_models.return_value = ["test/model"]
        result = enabled_orchestrator.wake_async(db_session)
    assert result["status"] == "ready"
    assert result["pod_id"] == "test-pod-id"
    mock_client.start_pod.assert_not_called()


def test_wake_async_exited_spawns_background_start(db_session, enabled_orchestrator):
    """Pod EXITED → bg thread spawned, status=starting."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.return_value = True
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = True

        result = enabled_orchestrator.wake_async(db_session)
        assert result["status"] == "starting"
        assert result["pod_id"] == "test-pod-id"

        # Wait for bg thread to finish before exiting the patch
        _wait_for_bg_thread(enabled_orchestrator)

    mock_client.start_pod.assert_called_once()


def test_wake_async_second_call_returns_already_starting(
    db_session, enabled_orchestrator
):
    """Calling wake_async twice in rapid succession → second returns already_starting."""
    # Block the bg thread by making start_pod hang briefly
    import threading
    block = threading.Event()

    def slow_start_pod(*a, **kw):
        block.wait(timeout=3.0)
        return True

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.side_effect = slow_start_pod
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = True

        # First call: spawns bg thread
        first = enabled_orchestrator.wake_async(db_session)
        assert first["status"] == "starting"

        # Second call while bg thread blocked: already_starting
        second = enabled_orchestrator.wake_async(db_session)
        assert second["status"] == "already_starting"

        # Release bg thread + wait for it
        block.set()
        _wait_for_bg_thread(enabled_orchestrator)


def test_wake_async_missing_pod_returns_missing(db_session, enabled_orchestrator):
    """fetch_pod returns None → status=missing (no exception, no bg start)."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = None
        result = enabled_orchestrator.wake_async(db_session)
    assert result["status"] == "missing"
    mock_client.start_pod.assert_not_called()


def test_wake_async_daily_cap_returns_capacity_exceeded(
    db_session, enabled_orchestrator
):
    """uptime_today_seconds >= cap → status=capacity_exceeded (no API call, no bg start)."""
    state = RunPodState(
        pod_id="test-pod-id",
        uptime_today_seconds=11 * 3600,
        uptime_day_utc=datetime.now(timezone.utc).date(),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(state)
    db_session.commit()

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        result = enabled_orchestrator.wake_async(db_session)
    assert result["status"] == "capacity_exceeded"
    assert result["uptime_today_seconds"] >= 11 * 3600
    mock_client.fetch_pod.assert_not_called()


# ── ensure_ready fast-fail (wait_for_ready=False) ────────────────────────────


def test_ensure_ready_fast_fail_returns_url_when_pod_running(
    db_session, enabled_orchestrator
):
    """Pod RUNNING + healthy → returns URL immediately, no bg start (same as default)."""
    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "RUNNING"}
        mock_client.list_models.return_value = ["test/model"]
        url = enabled_orchestrator.ensure_ready(db_session, wait_for_ready=False)
    assert url == "https://test-pod-8000.proxy.runpod.net/v1"
    mock_client.start_pod.assert_not_called()


def test_ensure_ready_fast_fail_raises_immediately_when_pod_exited(
    db_session, enabled_orchestrator
):
    """Pod EXITED → fast-fail raises RunPodUnavailableError + spawns bg start."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.return_value = True
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = True

        with pytest.raises(
            RunPodUnavailableError, match="runpod_cold_start_in_progress"
        ):
            enabled_orchestrator.ensure_ready(db_session, wait_for_ready=False)

        # The bg start should have been kicked off (one of these will be called)
        _wait_for_bg_thread(enabled_orchestrator)

    # After bg thread completes, start_pod should have been called
    mock_client.start_pod.assert_called_once()


def test_ensure_ready_fast_fail_concurrent_calls_only_spawn_one_bg_thread(
    db_session, enabled_orchestrator
):
    """Two ensure_ready(wait_for_ready=False) calls → only one bg thread spawns."""
    from app.services.runpod_orchestrator import RunPodUnavailableError

    import threading
    block = threading.Event()
    start_pod_call_count = [0]

    def slow_counting_start_pod(*a, **kw):
        start_pod_call_count[0] += 1
        block.wait(timeout=3.0)
        return True

    with patch("app.services.runpod_orchestrator.runpod_client") as mock_client:
        mock_client.fetch_pod.return_value = {"desiredStatus": "EXITED"}
        mock_client.start_pod.side_effect = slow_counting_start_pod
        mock_client.wait_for_running.return_value = (
            "https://test-pod-8000.proxy.runpod.net/v1"
        )
        mock_client.probe_vllm.return_value = True

        # First call spawns bg thread + raises
        with pytest.raises(RunPodUnavailableError):
            enabled_orchestrator.ensure_ready(db_session, wait_for_ready=False)

        # Second call: bg is still running. Should also raise without
        # spawning a second start_pod call.
        with pytest.raises(RunPodUnavailableError):
            enabled_orchestrator.ensure_ready(db_session, wait_for_ready=False)

        # Release bg thread + wait
        block.set()
        _wait_for_bg_thread(enabled_orchestrator)

    # start_pod should have been called exactly once (one bg thread)
    assert start_pod_call_count[0] == 1


# ── Integration: draft_generator fallback path ───────────────────────────────


def test_draft_generator_falls_back_to_claude_on_runpod_unavailable(
    db_session, mock_anthropic, monkeypatch
):
    """When the orchestrator raises RunPodUnavailableError, draft_generator
    switches to Claude and logs draft.fallback_to_claude.

    End-to-end wiring check: ensures the import wiring, the catch block in
    generate(), the AnthropicLLMClient fallback, and the audit log all
    cooperate. Doesn't rely on a real RunPod or real Anthropic.
    """
    import uuid
    from unittest.mock import MagicMock

    from app.models.email import (
        EmailCategory,
        EmailMessage,
        EmailStatus,
        EmailThread,
        MessageDirection,
    )
    from app.models.audit import AuditLog
    from app.services.runpod_orchestrator import RunPodUnavailableError

    # Override the mock_anthropic canned response with a plausible email body.
    # (mock_anthropic defaults to a categorizer-shaped JSON; we want plain text.)
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(
            text=(
                "Dear Tony, thank you for reaching out — we'll review your "
                "situation and follow up soon. Best regards, Schiller CPA team."
            )
        )],
        usage=MagicMock(input_tokens=200, output_tokens=60),
    )

    # Build the smallest valid thread + inbound message so generate() has
    # something to draft against.
    thread = EmailThread(
        id=uuid.uuid4(),
        client_email="tony@ferreiralaw.com",
        client_name="Tony Ferreira",
        subject="Quick question",
        category=EmailCategory.general_inquiry,
        status=EmailStatus.categorized,
        ai_summary="Client has a question.",
        suggested_reply_tone="professional",
    )
    msg = EmailMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        direction=MessageDirection.inbound,
        sender="tony@ferreiralaw.com",
        recipient="jane@schilcpa.com",
        body_text="Hi Jane, just wondering about the next steps?",
        message_id_header=f"<{uuid.uuid4().hex}@test>",
        received_at=datetime.now(timezone.utc),
    )
    db_session.add_all([thread, msg])
    db_session.commit()

    # Force the draft_generator's orchestrator to raise RunPodUnavailableError
    # at ensure_ready. Mock the singleton accessor so the in-method call to
    # get_runpod_orchestrator() returns our prepared mock.
    fake_orchestrator = MagicMock()
    fake_orchestrator.enabled = True
    # Use the canonical reason code shape the orchestrator now produces.
    # The draft_generator preserves this verbatim in the audit log so
    # downstream dashboards can filter fallbacks by cause.
    fake_orchestrator.ensure_ready.side_effect = RunPodUnavailableError(
        "runpod_capacity_error: test capacity failure"
    )
    monkeypatch.setattr(
        "app.services.draft_generator.get_runpod_orchestrator",
        lambda: fake_orchestrator,
    )

    # Reset llm_client singletons so the freshly mocked Anthropic is picked up
    # for BOTH the primary client (test conftest pins LLM_PROVIDER=anthropic
    # already so primary IS Anthropic) AND the fallback client.
    from app.services import llm_client as _llm_module
    _llm_module.reset_llm_client()

    # Also reset draft generator singleton so it rebuilds against the freshly
    # configured (and now mocked) LLM client.
    from app.services import draft_generator as _draft_module
    _draft_module._draft_generator = None

    # Run the draft path.
    from app.services.draft_generator import get_draft_generator
    generator = get_draft_generator()
    draft = generator.generate(db_session, thread)
    db_session.commit()

    # Draft was produced (fallback succeeded)
    assert draft is not None
    assert "Tony" in draft.body_text or "thank you" in draft.body_text.lower()
    # ai_model reflects the Claude fallback model, not the primary's name
    assert draft.ai_model  # any string is fine — the test conftest config'd Claude

    # Audit log has the fallback event
    fallback_rows = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "draft.fallback_to_claude")
        .filter(AuditLog.entity_id == str(thread.id))
        .all()
    )
    assert len(fallback_rows) == 1
    details = fallback_rows[0].details
    # Reason is the structured reason code from the orchestrator. Filter
    # criteria: prefix matches one of the canonical codes documented in
    # runpod_orchestrator.py module docstring.
    assert details["reason"].startswith("runpod_capacity_error")
    assert details["draft_id"] == str(draft.id)

    # draft.generated also records the fallback flag for dashboards
    gen_rows = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "draft.generated")
        .filter(AuditLog.entity_id == str(draft.id))
        .all()
    )
    assert len(gen_rows) == 1
    assert gen_rows[0].details["fallback_used"] is True

    # ensure_ready was called (proves we went through the orchestrator path)
    fake_orchestrator.ensure_ready.assert_called_once()
    # mark_used was NOT called — fallback path doesn't bump RunPod's idle clock
    fake_orchestrator.mark_used.assert_not_called()
