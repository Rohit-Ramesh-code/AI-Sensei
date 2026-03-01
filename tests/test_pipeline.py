"""
tests/test_pipeline.py — Integration tests for agents/supervisor.run_pipeline()

Tests cover the full sequential pipeline:
  analyst -> policy_guard -> communicator

All tests use mock adapters (USE_MOCK_SNMP=true, USE_MOCK_SMTP=true) and
inject crafted PollResult dicts directly to avoid dependency on mock SNMP
fixture values for threshold-specific tests.

Test isolation:
  - guardrails.safety_logic.ALERT_STATE_PATH is monkeypatched to tmp_path
    for any test that triggers an alert (prevents cross-test contamination
    with real alert_state.json on disk).
  - ALERT_RECIPIENT is set to test@example.com in env.
  - TONER_ALERT_THRESHOLD and TONER_CRITICAL_THRESHOLD are set via env.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import guardrails.safety_logic as safety_logic_module
from agents.supervisor import run_pipeline
from state_types import AgentState, PollResult, QualityFlag, TonerReading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def pipeline_env(monkeypatch):
    """Set required env vars for all pipeline tests."""
    monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
    monkeypatch.setenv("TONER_ALERT_THRESHOLD", "20")
    monkeypatch.setenv("TONER_CRITICAL_THRESHOLD", "10")
    monkeypatch.setenv("USE_MOCK_SMTP", "true")
    monkeypatch.setenv("USE_MOCK_SNMP", "true")


@pytest.fixture
def clean_alert_state(tmp_path, monkeypatch):
    """
    Isolate alert_state.json for tests that trigger alerts.

    run_policy_guard's default state_path argument is captured at function
    definition time, so monkeypatching the module attribute alone is not
    sufficient. Instead, we patch _load_alert_state to return an empty dict
    (simulating no prior alert) AND patch _save_alert_state to write to a
    tmp_path file — keeping the real logs/alert_state.json untouched.
    """
    alert_state_store: dict = {}

    def fake_load(state_path):
        return dict(alert_state_store)

    def fake_save(state, state_path):
        alert_state_store.clear()
        alert_state_store.update(state)

    monkeypatch.setattr(safety_logic_module, "_load_alert_state", fake_load)
    monkeypatch.setattr(safety_logic_module, "_save_alert_state", fake_save)
    return alert_state_store


def _make_reading(color: str, pct: float, quality: str = QualityFlag.OK.value) -> TonerReading:
    """Helper: build a TonerReading dict for a given toner percentage."""
    data_quality_ok = (quality == QualityFlag.OK.value)
    return {
        "color": color,
        "raw_value": int(pct) if data_quality_ok else -1,
        "max_capacity": 100,
        "toner_pct": pct if data_quality_ok else None,
        "quality_flag": quality,
        "data_quality_ok": data_quality_ok,
    }


def _make_poll_result(
    readings: list[TonerReading],
    printer_host: str = "192.168.1.100",
    snmp_error: str | None = None,
) -> PollResult:
    """Helper: build a PollResult with the given readings."""
    return {
        "printer_host": printer_host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readings": readings,
        "snmp_error": snmp_error,
        "overall_quality_ok": all(r["data_quality_ok"] for r in readings),
    }


# ---------------------------------------------------------------------------
# Test 1: Low toner poll -> alert_needed=True
# ---------------------------------------------------------------------------

def test_pipeline_low_toner_sets_alert_needed(clean_alert_state):
    """run_pipeline with cyan at 15% (below 20% threshold) sets alert_needed=True."""
    readings = [
        _make_reading("cyan", 15.0),   # below 20% threshold -> WARNING
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)

    result = run_pipeline(poll_result=poll_result)

    assert result["alert_needed"] is True or result["alert_sent"] is True, (
        "Expected pipeline to detect low toner — alert_needed should be True "
        f"(suppression_reason={result.get('suppression_reason')})"
    )


# ---------------------------------------------------------------------------
# Test 2: All-OK poll -> alert_needed=False, alert_sent=False
# ---------------------------------------------------------------------------

def test_pipeline_all_ok_no_alert():
    """run_pipeline with all toners at 80% produces alert_needed=False, alert_sent=False."""
    readings = [
        _make_reading("cyan", 80.0),
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)

    result = run_pipeline(poll_result=poll_result)

    assert result["alert_needed"] is False
    assert result["alert_sent"] is False


# ---------------------------------------------------------------------------
# Test 3: decision_log contains entries from analyst, policy_guard, communicator
# ---------------------------------------------------------------------------

def test_pipeline_decision_log_has_all_stages(clean_alert_state):
    """
    decision_log contains log entries from all three stages when an alert fires.
    """
    readings = [
        _make_reading("cyan", 5.0),  # below 10% critical threshold
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)

    result = run_pipeline(poll_result=poll_result)

    decision_log = result["decision_log"]
    log_text = " ".join(decision_log)

    # Analyst must log something about flagged colors
    assert any("analyst" in entry for entry in decision_log), (
        f"Analyst log entry not found. Log: {decision_log}"
    )

    # Policy guard must log something (freshness/rate checks)
    assert any("PolicyGuard" in entry or "policy" in entry.lower() for entry in decision_log), (
        f"Policy guard log entry not found. Log: {decision_log}"
    )

    # Communicator must log something (sent or skipped)
    assert any("communicator" in entry for entry in decision_log), (
        f"Communicator log entry not found. Log: {decision_log}"
    )


# ---------------------------------------------------------------------------
# Test 4: alert_needed=False from analyst -> communicator never runs (alert_sent=False)
# ---------------------------------------------------------------------------

def test_pipeline_no_alert_skips_communicator():
    """
    When analyst finds all toners OK (no alert needed), communicator is never invoked
    and alert_sent remains False.
    """
    readings = [
        _make_reading("cyan", 80.0),
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)

    # Track whether SMTPAdapter.send_alert is ever called
    with patch("agents.communicator.SMTPAdapter") as MockSMTP:
        result = run_pipeline(poll_result=poll_result)

    assert result["alert_sent"] is False
    # SMTPAdapter should not even be instantiated
    MockSMTP.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: run_pipeline with mock env vars completes without real network calls
# ---------------------------------------------------------------------------

def test_pipeline_completes_with_mock_mode(clean_alert_state):
    """
    With USE_MOCK_SNMP=true and USE_MOCK_SMTP=true, run_pipeline() completes
    end-to-end without any real SNMP or SMTP connections.
    """
    # Low toner to exercise the full path including communicator
    readings = [
        _make_reading("black", 5.0),  # below critical threshold
        _make_reading("cyan", 80.0),
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
    ]
    poll_result = _make_poll_result(readings)

    # Should not raise any exception even without real hardware or SMTP server
    result = run_pipeline(poll_result=poll_result)

    # Pipeline should return a valid AgentState with all expected keys
    assert "alert_needed" in result
    assert "alert_sent" in result
    assert "decision_log" in result
    assert isinstance(result["decision_log"], list)
