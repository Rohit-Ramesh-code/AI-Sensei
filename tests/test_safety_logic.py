"""
tests/test_safety_logic.py — Tests for guardrails/safety_logic.py Policy Guard.

All file-based tests (alert_state.json, printer_history.jsonl) use tmp_path
(pytest fixture) to isolate. No real logs/ directory is written during test runs.

Design: safety_logic helpers accept state_path and log_path parameters for test
isolation — no globals are patched. Timestamps are constructed with timezone.utc
to avoid naive/aware datetime mismatches.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure project root is on path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers — minimal fixtures constructed inline
# ---------------------------------------------------------------------------

def make_poll_result(
    printer_host: str = "192.168.1.100",
    snmp_error: "str | None" = None,
    minutes_ago: float = 5.0,
) -> dict:
    """Return a minimal but valid PollResult dict for testing."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "printer_host": printer_host,
        "timestamp": ts.isoformat(),
        "readings": [
            {
                "color": "black",
                "raw_value": 85,
                "max_capacity": 100,
                "toner_pct": 85.0,
                "quality_flag": "ok",
                "data_quality_ok": True,
            }
        ],
        "snmp_error": snmp_error,
        "overall_quality_ok": snmp_error is None,
    }


def make_agent_state(
    printer_host: str = "192.168.1.100",
    alert_needed: bool = True,
    snmp_error: "str | None" = None,
    minutes_ago: float = 5.0,
) -> dict:
    """Return a minimal AgentState-compatible dict for testing run_policy_guard."""
    return {
        "poll_result": make_poll_result(
            printer_host=printer_host,
            snmp_error=snmp_error,
            minutes_ago=minutes_ago,
        ),
        "alert_needed": alert_needed,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
    }


def make_alert_state_json(printer_host: str, hours_ago: float) -> str:
    """Return a JSON string representing alert_state.json with one prior alert."""
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return json.dumps({
        printer_host: {
            "last_alert_timestamp": ts.isoformat()
        }
    })


# ---------------------------------------------------------------------------
# Test 1: Rate limit — prior alert 1 hour ago → suppressed (rate_limit)
# ---------------------------------------------------------------------------

def test_rate_limit_suppresses_within_24_hours(tmp_path: Path) -> None:
    """run_policy_guard suppresses when prior alert was sent 1 hour ago (within 24h window)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    # Write alert state showing an alert 1 hour ago
    state_path.write_text(make_alert_state_json(printer_host, hours_ago=1.0), encoding="utf-8")

    state = make_agent_state(printer_host=printer_host)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is False, (
        "alert_needed must be False when within 24h rate limit window"
    )
    assert result["suppression_reason"] is not None, "suppression_reason must be set"
    assert "rate_limit" in result["suppression_reason"], (
        f"suppression_reason must contain 'rate_limit', got: {result['suppression_reason']!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: Rate limit cleared — prior alert 25 hours ago → allowed
# ---------------------------------------------------------------------------

def test_rate_limit_allows_after_24_hours(tmp_path: Path) -> None:
    """run_policy_guard allows when prior alert was sent 25 hours ago (window expired)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    # Write alert state showing an alert 25 hours ago (window expired)
    state_path.write_text(make_alert_state_json(printer_host, hours_ago=25.0), encoding="utf-8")

    state = make_agent_state(printer_host=printer_host)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is True, (
        "alert_needed must remain True when 24h window has passed"
    )
    assert result["suppression_reason"] is None, (
        f"suppression_reason must be None after window expires, got: {result['suppression_reason']!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: No alert_state.json → allowed (no prior alert on record)
# ---------------------------------------------------------------------------

def test_no_alert_state_file_allows_alert(tmp_path: Path) -> None:
    """run_policy_guard allows when alert_state.json does not exist (first ever alert)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    # No state file written — simulates first run
    assert not state_path.exists(), "Pre-condition: alert_state.json must not exist"

    state = make_agent_state(printer_host=printer_host)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is True, (
        "alert_needed must be True when no prior alert is on record"
    )
    assert result["suppression_reason"] is None


# ---------------------------------------------------------------------------
# Test 4: Corrupted alert_state.json → allowed (graceful fallback to empty state)
# ---------------------------------------------------------------------------

def test_corrupted_alert_state_file_allows_alert(tmp_path: Path) -> None:
    """run_policy_guard allows when alert_state.json contains invalid JSON (graceful recovery)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    # Write intentionally corrupted JSON
    state_path.write_text("{ this is not valid json !!!!", encoding="utf-8")

    state = make_agent_state(printer_host=printer_host)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is True, (
        "alert_needed must be True when alert_state.json is corrupted (treat as no prior state)"
    )
    assert result["suppression_reason"] is None


# ---------------------------------------------------------------------------
# Test 5: Stale data — poll timestamp 130 minutes ago → suppressed (stale_data)
# ---------------------------------------------------------------------------

def test_stale_data_suppresses_alert(tmp_path: Path, monkeypatch) -> None:
    """run_policy_guard suppresses when poll timestamp is 130 minutes old (threshold=120)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    # Patch STALE_THRESHOLD_MINUTES to 120 via env var
    monkeypatch.setenv("STALE_THRESHOLD_MINUTES", "120")

    state = make_agent_state(printer_host=printer_host, minutes_ago=130.0)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is False, (
        "alert_needed must be False when poll data is stale (130 min > 120 min threshold)"
    )
    assert result["suppression_reason"] is not None
    assert "stale_data" in result["suppression_reason"], (
        f"suppression_reason must contain 'stale_data', got: {result['suppression_reason']!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: Fresh data — poll timestamp 5 minutes ago → not suppressed for staleness
# ---------------------------------------------------------------------------

def test_fresh_data_not_suppressed_for_staleness(tmp_path: Path, monkeypatch) -> None:
    """run_policy_guard does NOT suppress when poll data is 5 minutes old (well within threshold)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    monkeypatch.setenv("STALE_THRESHOLD_MINUTES", "120")

    state = make_agent_state(printer_host=printer_host, minutes_ago=5.0)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    # May still be True (rate limit not triggered, no snmp_error)
    assert result["suppression_reason"] is None or "stale_data" not in result["suppression_reason"], (
        "Fresh data (5 min) must not trigger stale_data suppression"
    )


# ---------------------------------------------------------------------------
# Test 7: snmp_error set on poll_result → suppressed (data_quality)
# ---------------------------------------------------------------------------

def test_snmp_error_suppresses_alert(tmp_path: Path) -> None:
    """run_policy_guard suppresses when poll_result.snmp_error is set (data quality failure)."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    state = make_agent_state(
        printer_host=printer_host,
        snmp_error="Timeout: no response from 192.168.1.100",
    )
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is False, (
        "alert_needed must be False when snmp_error is set"
    )
    assert result["suppression_reason"] is not None
    assert "data_quality" in result["suppression_reason"], (
        f"suppression_reason must contain 'data_quality', got: {result['suppression_reason']!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: Suppression appends record to printer_history.jsonl
# ---------------------------------------------------------------------------

def test_suppression_appends_record_to_jsonl(tmp_path: Path) -> None:
    """Suppressed alert appends a record with event_type='suppressed_alert' and reason field to JSONL."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    # Trigger rate-limit suppression (prior alert 1 hour ago)
    state_path.write_text(make_alert_state_json(printer_host, hours_ago=1.0), encoding="utf-8")

    state = make_agent_state(printer_host=printer_host)
    run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert log_path.exists(), "printer_history.jsonl must be created after suppression"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "At least one record must be appended on suppression"

    record = json.loads(lines[0])
    assert record.get("event_type") == "suppressed_alert", (
        f"event_type must be 'suppressed_alert', got: {record.get('event_type')!r}"
    )
    assert "reason" in record, "Suppression record must include 'reason' field"
    assert record.get("printer_host") == printer_host


# ---------------------------------------------------------------------------
# Test 9: alert_state.json is updated after allowed alert (record_alert_sent called)
# ---------------------------------------------------------------------------

def test_record_alert_sent_updates_state_file(tmp_path: Path) -> None:
    """record_alert_sent() creates or updates alert_state.json with ISO 8601 timestamp."""
    from guardrails.safety_logic import record_alert_sent

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"

    # File does not exist yet
    assert not state_path.exists(), "Pre-condition: file must not exist before record_alert_sent"

    record_alert_sent(printer_host, state_path=state_path)

    assert state_path.exists(), "alert_state.json must be created by record_alert_sent()"

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert printer_host in data, f"printer_host key must exist in alert_state.json"
    assert "last_alert_timestamp" in data[printer_host], (
        "last_alert_timestamp key must exist under printer_host"
    )

    # Verify it is a valid ISO 8601 datetime string
    ts_str = data[printer_host]["last_alert_timestamp"]
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError as exc:
        raise AssertionError(
            f"last_alert_timestamp is not valid ISO 8601: {ts_str!r}"
        ) from exc

    assert dt.tzinfo is not None, (
        f"last_alert_timestamp must include timezone info, got: {ts_str!r}"
    )


# ---------------------------------------------------------------------------
# Test 10: alert_needed=False → run_policy_guard is a no-op (returns state unchanged)
# ---------------------------------------------------------------------------

def test_run_policy_guard_noop_when_alert_not_needed(tmp_path: Path) -> None:
    """run_policy_guard returns state unchanged when alert_needed is False."""
    from guardrails.safety_logic import run_policy_guard

    printer_host = "192.168.1.100"
    state_path = tmp_path / "alert_state.json"
    log_path = tmp_path / "history.jsonl"

    state = make_agent_state(printer_host=printer_host, alert_needed=False)
    result = run_policy_guard(state, state_path=state_path, log_path=log_path)

    assert result["alert_needed"] is False
    assert result["suppression_reason"] is None, (
        "suppression_reason must not be set when alert was not needed in the first place"
    )
    # No log entry written (no suppression occurred)
    assert not log_path.exists(), "No JSONL record must be written when alert_needed=False"
