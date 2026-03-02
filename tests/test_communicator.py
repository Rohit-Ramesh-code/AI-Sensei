"""
tests/test_communicator.py — Unit tests for agents/communicator.py

Tests cover:
  - build_subject(): subject line format for CRITICAL, WARNING, mixed urgency, BELOW_LOW_THRESHOLD
  - build_body(): body format with printer host, color details, recommended actions
  - run_communicator(): dispatch logic, mock SMTP, alert_sent flag, record_alert_sent call,
    no-op when alert_needed=False, single-send for multiple colors, ValueError on missing recipient
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from agents.communicator import build_body, build_subject, run_communicator
from state_types import AgentState, PollResult, QualityFlag, TonerReading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_reading(color: str, pct: float) -> TonerReading:
    """Helper: create a valid OK TonerReading at a given percentage."""
    return {
        "color": color,
        "raw_value": int(pct),
        "max_capacity": 100,
        "toner_pct": pct,
        "quality_flag": QualityFlag.OK.value,
        "data_quality_ok": True,
    }


def _make_poll_result(printer_host: str = "192.168.1.100") -> PollResult:
    """Helper: create a basic PollResult with all toners at 80%."""
    return {
        "printer_host": printer_host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readings": [
            _make_reading("cyan", 80.0),
            _make_reading("magenta", 80.0),
            _make_reading("yellow", 80.0),
            _make_reading("black", 80.0),
        ],
        "snmp_error": None,
        "overall_quality_ok": True,
    }


def _make_state(
    flagged_colors: list | None = None,
    alert_needed: bool = True,
    printer_host: str = "192.168.1.100",
) -> AgentState:
    """Helper: build a minimal AgentState ready for run_communicator."""
    return {
        "poll_result": _make_poll_result(printer_host),
        "alert_needed": alert_needed,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": flagged_colors or [],
        "llm_confidence": None,  # NEW (Phase 3)
        "llm_reasoning": None,   # NEW (Phase 3)
    }


# ---------------------------------------------------------------------------
# Test 1: build_subject() -- single CRITICAL entry
# ---------------------------------------------------------------------------

def test_build_subject_single_critical():
    """Subject starts with [Sentinel] CRITICAL: when one CRITICAL entry is present."""
    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"}]
    subject = build_subject(flagged)
    assert subject.startswith("[Sentinel] CRITICAL: Printer toner low")
    assert "Cyan 8.0%" in subject


# ---------------------------------------------------------------------------
# Test 2: build_subject() -- single WARNING entry
# ---------------------------------------------------------------------------

def test_build_subject_single_warning():
    """Subject starts with [Sentinel] WARNING: when all entries are WARNING."""
    flagged = [{"color": "magenta", "urgency": "WARNING", "display_value": "15%"}]
    subject = build_subject(flagged)
    assert subject.startswith("[Sentinel] WARNING: Printer toner low")
    assert "Magenta 15%" in subject


# ---------------------------------------------------------------------------
# Test 3: build_subject() -- mixed WARNING+CRITICAL -> overall urgency is CRITICAL
# ---------------------------------------------------------------------------

def test_build_subject_mixed_urgency_is_critical():
    """Any CRITICAL entry in the list makes the overall subject CRITICAL."""
    flagged = [
        {"color": "magenta", "urgency": "WARNING", "display_value": "15%"},
        {"color": "cyan", "urgency": "CRITICAL", "display_value": "5%"},
    ]
    subject = build_subject(flagged)
    assert subject.startswith("[Sentinel] CRITICAL:")


# ---------------------------------------------------------------------------
# Test 4: build_subject() -- BELOW_LOW_THRESHOLD display_value appears in subject
# ---------------------------------------------------------------------------

def test_build_subject_below_low_threshold():
    """'below low threshold (unquantified)' appears verbatim in the subject line."""
    flagged = [
        {"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"},
        {"color": "yellow", "urgency": "CRITICAL", "display_value": "below low threshold (unquantified)"},
    ]
    subject = build_subject(flagged)
    assert "below low threshold (unquantified)" in subject
    assert subject.startswith("[Sentinel] CRITICAL:")


# ---------------------------------------------------------------------------
# Test 5: build_body() -- includes printer host, each color, display_value, urgency, and action
# ---------------------------------------------------------------------------

def test_build_body_format():
    """Body contains printer host header, each flagged color, and Order action per color."""
    flagged = [
        {"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"},
        {"color": "yellow", "urgency": "CRITICAL", "display_value": "below low threshold (unquantified)"},
    ]
    body = build_body("192.168.1.100", flagged)

    assert "Printer: 192.168.1.100" in body
    assert "Low toner detected:" in body
    assert "Cyan: 8.0% [CRITICAL]" in body
    assert "Recommended action: Order cyan toner" in body
    assert "Yellow: below low threshold (unquantified) [CRITICAL]" in body
    assert "Recommended action: Order yellow toner" in body


# ---------------------------------------------------------------------------
# Test 6: run_communicator() -- alert_needed=True -> alert_sent=True
# ---------------------------------------------------------------------------

def test_run_communicator_sends_alert(tmp_path, monkeypatch):
    """run_communicator sets alert_sent=True when alert_needed=True (mock SMTP)."""
    monkeypatch.setenv("ALERT_RECIPIENT", "admin@example.com")
    monkeypatch.setenv("USE_MOCK_SMTP", "true")
    # Isolate alert_state.json so record_alert_sent doesn't write to production path
    alert_state_file = tmp_path / "alert_state.json"
    monkeypatch.setattr(
        "guardrails.safety_logic.ALERT_STATE_PATH", alert_state_file
    )

    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"}]
    state = _make_state(flagged_colors=flagged, alert_needed=True)

    result = run_communicator(state)

    assert result["alert_sent"] is True


# ---------------------------------------------------------------------------
# Test 7: run_communicator() -- alert_needed=False -> no-op
# ---------------------------------------------------------------------------

def test_run_communicator_skips_when_not_needed(monkeypatch):
    """run_communicator returns state unchanged when alert_needed=False."""
    monkeypatch.setenv("ALERT_RECIPIENT", "admin@example.com")
    monkeypatch.setenv("USE_MOCK_SMTP", "true")

    state = _make_state(alert_needed=False)
    result = run_communicator(state)

    assert result["alert_sent"] is False
    assert any("skipped" in entry for entry in result["decision_log"])


# ---------------------------------------------------------------------------
# Test 8: run_communicator() -- sends exactly ONE email regardless of multiple flagged colors
# ---------------------------------------------------------------------------

def test_run_communicator_single_send_for_multiple_colors(tmp_path, monkeypatch):
    """Only one send_alert() call is made even when multiple colors are flagged."""
    monkeypatch.setenv("ALERT_RECIPIENT", "admin@example.com")
    monkeypatch.setenv("USE_MOCK_SMTP", "true")
    alert_state_file = tmp_path / "alert_state.json"
    monkeypatch.setattr(
        "guardrails.safety_logic.ALERT_STATE_PATH", alert_state_file
    )

    flagged = [
        {"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"},
        {"color": "yellow", "urgency": "CRITICAL", "display_value": "below low threshold (unquantified)"},
        {"color": "magenta", "urgency": "WARNING", "display_value": "15%"},
    ]
    state = _make_state(flagged_colors=flagged, alert_needed=True)

    mock_smtp = MagicMock()
    with patch("agents.communicator.SMTPAdapter", return_value=mock_smtp):
        run_communicator(state)

    # Exactly one send_alert call, regardless of how many colors were flagged
    assert mock_smtp.send_alert.call_count == 1


# ---------------------------------------------------------------------------
# Test 9: run_communicator() -- calls record_alert_sent() after successful send
# ---------------------------------------------------------------------------

def test_run_communicator_calls_record_alert_sent(tmp_path, monkeypatch):
    """record_alert_sent() is called once with the printer_host after a successful send."""
    monkeypatch.setenv("ALERT_RECIPIENT", "admin@example.com")
    monkeypatch.setenv("USE_MOCK_SMTP", "true")
    alert_state_file = tmp_path / "alert_state.json"
    monkeypatch.setattr(
        "guardrails.safety_logic.ALERT_STATE_PATH", alert_state_file
    )

    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"}]
    state = _make_state(flagged_colors=flagged, alert_needed=True, printer_host="10.0.0.5")

    with patch("agents.communicator.record_alert_sent") as mock_record:
        with patch("agents.communicator.SMTPAdapter") as MockSMTP:
            MockSMTP.return_value.send_alert = MagicMock()
            run_communicator(state)

        mock_record.assert_called_once_with("10.0.0.5")


# ---------------------------------------------------------------------------
# Test 10: ALERT_RECIPIENT not set -> ValueError
# ---------------------------------------------------------------------------

def test_run_communicator_raises_on_missing_recipient(monkeypatch):
    """ValueError is raised with a helpful message when ALERT_RECIPIENT is not set."""
    # Remove ALERT_RECIPIENT from environment
    monkeypatch.delenv("ALERT_RECIPIENT", raising=False)
    monkeypatch.setenv("USE_MOCK_SMTP", "true")

    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "8.0%"}]
    state = _make_state(flagged_colors=flagged, alert_needed=True)

    with pytest.raises(ValueError, match="ALERT_RECIPIENT"):
        run_communicator(state)


# ---------------------------------------------------------------------------
# Phase 3 stub tests — RED state (will pass after Plan 03 implements llm_reasoning in build_body)
# ---------------------------------------------------------------------------

def test_build_body_includes_analysis_section():
    """build_body with llm_reasoning set includes an 'Analysis:' section in the body."""
    from agents.communicator import build_body
    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "12.0%"}]
    reasoning = "Cyan toner dropped from 45% to 12% over 4 days. Depletion estimated in ~1 day. Confidence: 0.91."
    body = build_body("192.168.1.100", flagged, llm_reasoning=reasoning)
    assert "Analysis:" in body, f"Expected 'Analysis:' section in body, got:\n{body}"
    assert "Confidence:" in body, f"Expected 'Confidence:' in body, got:\n{body}"
    assert reasoning in body or "Cyan toner" in body, "Expected reasoning text in body"


def test_build_body_without_llm_reasoning_omits_analysis_section():
    """build_body with llm_reasoning=None does NOT include an 'Analysis:' section."""
    from agents.communicator import build_body
    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "12.0%"}]
    body = build_body("192.168.1.100", flagged, llm_reasoning=None)
    assert "Analysis:" not in body, (
        f"Expected no 'Analysis:' section when llm_reasoning=None, got:\n{body}"
    )


def test_build_body_without_llm_reasoning_has_fallback_note():
    """build_body with llm_reasoning=None includes the LLM-unavailable fallback note."""
    from agents.communicator import build_body
    flagged = [{"color": "cyan", "urgency": "CRITICAL", "display_value": "12.0%"}]
    body = build_body("192.168.1.100", flagged, llm_reasoning=None)
    assert "Note: LLM analysis unavailable" in body, (
        f"Expected fallback note when llm_reasoning=None, got:\n{body}"
    )
