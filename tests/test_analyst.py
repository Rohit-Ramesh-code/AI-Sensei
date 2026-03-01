"""
tests/test_analyst.py — Unit tests for agents/analyst.py run_analyst() function.

Tests cover all 7 behavior cases defined in 02-01-PLAN.md:
  1. poll_result=None → alert_needed=False, decision_log entry mentioning "analyst"
  2. All four readings OK at 50% (threshold=20%) → alert_needed=False, flagged_colors=[]
  3. cyan=15% OK, threshold=20%, critical=10% → WARNING urgency
  4. cyan=8% OK, threshold=20%, critical=10% → CRITICAL urgency
  5. yellow has BELOW_LOW_THRESHOLD flag → CRITICAL urgency with display_value text
  6. snmp_error set, readings all SNMP_ERROR flag → alert_needed=False
  7. Multiple colors low in same poll → all appear in flagged_colors

All tests are pure unit tests — no live SNMP or SMTP required.
"""

import os
import sys

# Ensure project root is on path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Inline fixture helpers
# ---------------------------------------------------------------------------

def _make_reading(color: str, flag: str, pct, quality_ok: bool) -> dict:
    """Build a minimal TonerReading dict for test fixtures."""
    return {
        "color": color,
        "raw_value": 0,
        "max_capacity": 100,
        "toner_pct": pct,
        "quality_flag": flag,
        "data_quality_ok": quality_ok,
    }


def _make_poll(readings, snmp_error=None) -> dict:
    """Build a minimal PollResult dict for test fixtures."""
    return {
        "printer_host": "192.168.1.100",
        "timestamp": "2026-03-01T10:00:00+00:00",
        "readings": readings,
        "snmp_error": snmp_error,
        "overall_quality_ok": all(r["data_quality_ok"] for r in readings),
    }


def _make_state(poll_result=None) -> dict:
    """Build a minimal AgentState dict for test fixtures."""
    return {
        "poll_result": poll_result,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
    }


# ---------------------------------------------------------------------------
# Test 1: poll_result=None → alert_needed=False, decision_log has "analyst" entry
# ---------------------------------------------------------------------------

def test_none_poll_result_returns_no_alert():
    """When poll_result is None, analyst sets alert_needed=False and logs an entry mentioning 'analyst'."""
    from agents.analyst import run_analyst

    state = _make_state(poll_result=None)
    result = run_analyst(state)

    assert result["alert_needed"] is False, (
        f"Expected alert_needed=False for None poll_result, got {result['alert_needed']}"
    )
    log_entries = result["decision_log"]
    assert len(log_entries) >= 1, "Expected at least one decision_log entry"
    assert any("analyst" in entry.lower() for entry in log_entries), (
        f"Expected 'analyst' in decision_log, got: {log_entries}"
    )


# ---------------------------------------------------------------------------
# Test 2: All four readings OK at 50% → alert_needed=False, flagged_colors=[]
# ---------------------------------------------------------------------------

def test_all_readings_ok_above_threshold_no_alert():
    """All four CMYK readings OK at 50% (threshold=20%) → alert_needed=False, flagged_colors=[]."""
    from agents.analyst import run_analyst

    os.environ["TONER_ALERT_THRESHOLD"] = "20"
    os.environ["TONER_CRITICAL_THRESHOLD"] = "10"
    try:
        readings = [
            _make_reading("cyan",    "ok", 50.0, True),
            _make_reading("magenta", "ok", 50.0, True),
            _make_reading("yellow",  "ok", 50.0, True),
            _make_reading("black",   "ok", 50.0, True),
        ]
        poll = _make_poll(readings)
        state = _make_state(poll_result=poll)
        result = run_analyst(state)

        assert result["alert_needed"] is False, (
            f"Expected alert_needed=False, got {result['alert_needed']}"
        )
        assert result["flagged_colors"] == [], (
            f"Expected flagged_colors=[], got {result['flagged_colors']}"
        )
    finally:
        os.environ.pop("TONER_ALERT_THRESHOLD", None)
        os.environ.pop("TONER_CRITICAL_THRESHOLD", None)


# ---------------------------------------------------------------------------
# Test 3: cyan=15% OK, threshold=20%, critical=10% → WARNING urgency
# ---------------------------------------------------------------------------

def test_cyan_below_alert_threshold_gets_warning_urgency():
    """cyan=15% with threshold=20%, critical=10% → flagged_colors has WARNING urgency for cyan."""
    from agents.analyst import run_analyst

    os.environ["TONER_ALERT_THRESHOLD"] = "20"
    os.environ["TONER_CRITICAL_THRESHOLD"] = "10"
    try:
        readings = [
            _make_reading("cyan",    "ok", 15.0, True),
            _make_reading("magenta", "ok", 80.0, True),
            _make_reading("yellow",  "ok", 80.0, True),
            _make_reading("black",   "ok", 80.0, True),
        ]
        poll = _make_poll(readings)
        state = _make_state(poll_result=poll)
        result = run_analyst(state)

        assert result["alert_needed"] is True, (
            f"Expected alert_needed=True for cyan at 15%, got {result['alert_needed']}"
        )
        flagged = result["flagged_colors"]
        assert len(flagged) == 1, f"Expected 1 flagged color, got {len(flagged)}: {flagged}"
        cyan_flag = flagged[0]
        assert cyan_flag["color"] == "cyan", f"Expected cyan, got {cyan_flag['color']}"
        assert cyan_flag["urgency"] == "WARNING", (
            f"Expected WARNING urgency for 15% with critical=10%, got {cyan_flag['urgency']}"
        )
        assert "15.0%" in cyan_flag["display_value"], (
            f"Expected '15.0%' in display_value, got {cyan_flag['display_value']!r}"
        )
    finally:
        os.environ.pop("TONER_ALERT_THRESHOLD", None)
        os.environ.pop("TONER_CRITICAL_THRESHOLD", None)


# ---------------------------------------------------------------------------
# Test 4: cyan=8% OK, threshold=20%, critical=10% → CRITICAL urgency
# ---------------------------------------------------------------------------

def test_cyan_below_critical_threshold_gets_critical_urgency():
    """cyan=8% with threshold=20%, critical=10% → flagged_colors has CRITICAL urgency for cyan."""
    from agents.analyst import run_analyst

    os.environ["TONER_ALERT_THRESHOLD"] = "20"
    os.environ["TONER_CRITICAL_THRESHOLD"] = "10"
    try:
        readings = [
            _make_reading("cyan",    "ok", 8.0, True),
            _make_reading("magenta", "ok", 80.0, True),
            _make_reading("yellow",  "ok", 80.0, True),
            _make_reading("black",   "ok", 80.0, True),
        ]
        poll = _make_poll(readings)
        state = _make_state(poll_result=poll)
        result = run_analyst(state)

        assert result["alert_needed"] is True, (
            f"Expected alert_needed=True for cyan at 8%, got {result['alert_needed']}"
        )
        flagged = result["flagged_colors"]
        assert len(flagged) == 1, f"Expected 1 flagged color, got {len(flagged)}: {flagged}"
        cyan_flag = flagged[0]
        assert cyan_flag["color"] == "cyan", f"Expected cyan, got {cyan_flag['color']}"
        assert cyan_flag["urgency"] == "CRITICAL", (
            f"Expected CRITICAL urgency for 8% with critical=10%, got {cyan_flag['urgency']}"
        )
        assert "8.0%" in cyan_flag["display_value"], (
            f"Expected '8.0%' in display_value, got {cyan_flag['display_value']!r}"
        )
    finally:
        os.environ.pop("TONER_ALERT_THRESHOLD", None)
        os.environ.pop("TONER_CRITICAL_THRESHOLD", None)


# ---------------------------------------------------------------------------
# Test 5: yellow has BELOW_LOW_THRESHOLD flag → CRITICAL, display_value is descriptive text
# ---------------------------------------------------------------------------

def test_below_low_threshold_flag_produces_critical_with_text_display():
    """yellow with quality_flag=BELOW_LOW_THRESHOLD → CRITICAL urgency and descriptive display_value."""
    from agents.analyst import run_analyst

    readings = [
        _make_reading("cyan",    "ok",                   80.0, True),
        _make_reading("magenta", "ok",                   80.0, True),
        _make_reading("yellow",  "below_low_threshold",  None, False),
        _make_reading("black",   "ok",                   80.0, True),
    ]
    poll = _make_poll(readings)
    state = _make_state(poll_result=poll)
    result = run_analyst(state)

    assert result["alert_needed"] is True, (
        f"Expected alert_needed=True for BELOW_LOW_THRESHOLD yellow, got {result['alert_needed']}"
    )
    flagged = result["flagged_colors"]
    yellow_flags = [f for f in flagged if f["color"] == "yellow"]
    assert len(yellow_flags) == 1, (
        f"Expected 1 flagged entry for yellow, got {yellow_flags}"
    )
    yellow_flag = yellow_flags[0]
    assert yellow_flag["urgency"] == "CRITICAL", (
        f"Expected CRITICAL urgency for BELOW_LOW_THRESHOLD, got {yellow_flag['urgency']}"
    )
    assert "below low threshold" in yellow_flag["display_value"].lower(), (
        f"Expected descriptive display_value for BELOW_LOW_THRESHOLD, got {yellow_flag['display_value']!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: snmp_error set, readings all SNMP_ERROR flag → alert_needed=False
# ---------------------------------------------------------------------------

def test_snmp_error_readings_skipped_no_alert():
    """Readings with SNMP_ERROR quality_flag are skipped silently; alert_needed=False."""
    from agents.analyst import run_analyst

    readings = [
        _make_reading("cyan",    "snmp_error", None, False),
        _make_reading("magenta", "snmp_error", None, False),
        _make_reading("yellow",  "snmp_error", None, False),
        _make_reading("black",   "snmp_error", None, False),
    ]
    poll = _make_poll(readings, snmp_error="Timeout reaching 192.168.1.100")
    state = _make_state(poll_result=poll)
    result = run_analyst(state)

    assert result["alert_needed"] is False, (
        f"Expected alert_needed=False for all SNMP_ERROR readings, got {result['alert_needed']}"
    )
    assert result["flagged_colors"] == [], (
        f"Expected flagged_colors=[] for all SNMP_ERROR, got {result['flagged_colors']}"
    )


# ---------------------------------------------------------------------------
# Test 7: Multiple colors low in same poll → all in flagged_colors, alert_needed=True
# ---------------------------------------------------------------------------

def test_multiple_low_colors_all_appear_in_flagged_colors():
    """When multiple colors are low in the same poll, all appear in flagged_colors and alert_needed=True."""
    from agents.analyst import run_analyst

    os.environ["TONER_ALERT_THRESHOLD"] = "20"
    os.environ["TONER_CRITICAL_THRESHOLD"] = "10"
    try:
        readings = [
            _make_reading("cyan",    "ok", 15.0, True),   # WARNING
            _make_reading("magenta", "ok",  5.0, True),   # CRITICAL
            _make_reading("yellow",  "ok", 80.0, True),   # OK
            _make_reading("black",   "ok", 12.0, True),   # WARNING
        ]
        poll = _make_poll(readings)
        state = _make_state(poll_result=poll)
        result = run_analyst(state)

        assert result["alert_needed"] is True, (
            f"Expected alert_needed=True when multiple colors are low, got {result['alert_needed']}"
        )
        flagged = result["flagged_colors"]
        assert len(flagged) == 3, (
            f"Expected 3 flagged colors (cyan, magenta, black), got {len(flagged)}: {flagged}"
        )
        flagged_color_names = {f["color"] for f in flagged}
        assert "cyan" in flagged_color_names, "Expected cyan in flagged_colors"
        assert "magenta" in flagged_color_names, "Expected magenta in flagged_colors"
        assert "black" in flagged_color_names, "Expected black in flagged_colors"
        assert "yellow" not in flagged_color_names, "Expected yellow NOT in flagged_colors"

        # Check urgency levels
        magenta_flag = next(f for f in flagged if f["color"] == "magenta")
        assert magenta_flag["urgency"] == "CRITICAL", (
            f"Expected magenta CRITICAL at 5%, got {magenta_flag['urgency']}"
        )
        cyan_flag = next(f for f in flagged if f["color"] == "cyan")
        assert cyan_flag["urgency"] == "WARNING", (
            f"Expected cyan WARNING at 15%, got {cyan_flag['urgency']}"
        )
    finally:
        os.environ.pop("TONER_ALERT_THRESHOLD", None)
        os.environ.pop("TONER_CRITICAL_THRESHOLD", None)
