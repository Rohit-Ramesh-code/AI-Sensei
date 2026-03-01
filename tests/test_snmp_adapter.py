"""
Tests for adapters/snmp_adapter.py — classify_snmp_value function and SNMPAdapter class.

All tests run in mock mode or test pure classification logic.
No live SNMP device required.
"""

from __future__ import annotations

import os
import sys

# Ensure project root is on path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Test 1: classify_snmp_value(-2, 100) returns (QualityFlag.UNKNOWN, None)
# ---------------------------------------------------------------------------

def test_classify_minus2_returns_unknown():
    """SNMP sentinel -2 maps to QualityFlag.UNKNOWN with no percentage."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(-2, 100)
    assert flag == QualityFlag.UNKNOWN
    assert pct is None


# ---------------------------------------------------------------------------
# Test 2: classify_snmp_value(-3, 100) returns (QualityFlag.BELOW_LOW_THRESHOLD, None)
# ---------------------------------------------------------------------------

def test_classify_minus3_returns_below_low_threshold():
    """SNMP sentinel -3 maps to QualityFlag.BELOW_LOW_THRESHOLD with no percentage."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(-3, 100)
    assert flag == QualityFlag.BELOW_LOW_THRESHOLD
    assert pct is None


# ---------------------------------------------------------------------------
# Test 3: classify_snmp_value(-1, 100) returns (QualityFlag.NOT_SUPPORTED, None)
# ---------------------------------------------------------------------------

def test_classify_minus1_returns_not_supported():
    """SNMP sentinel -1 maps to QualityFlag.NOT_SUPPORTED with no percentage."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(-1, 100)
    assert flag == QualityFlag.NOT_SUPPORTED
    assert pct is None


# ---------------------------------------------------------------------------
# Test 4: classify_snmp_value(None, 100) returns (QualityFlag.NULL_VALUE, None)
# ---------------------------------------------------------------------------

def test_classify_none_returns_null_value():
    """None raw_level maps to QualityFlag.NULL_VALUE with no percentage."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(None, 100)
    assert flag == QualityFlag.NULL_VALUE
    assert pct is None


# ---------------------------------------------------------------------------
# Test 5: classify_snmp_value(85, 100) returns (QualityFlag.OK, 85.0)
# ---------------------------------------------------------------------------

def test_classify_valid_value_returns_ok_and_percentage():
    """Valid reading 85/100 maps to QualityFlag.OK and toner_pct=85.0."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(85, 100)
    assert flag == QualityFlag.OK
    assert pct == 85.0


# ---------------------------------------------------------------------------
# Test 6: classify_snmp_value(85, -2) returns (QualityFlag.UNKNOWN, None)
# ---------------------------------------------------------------------------

def test_classify_sentinel_max_capacity_returns_unknown():
    """max_capacity sentinel -2 (invalid capacity) returns UNKNOWN even if level is valid."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(85, -2)
    assert flag == QualityFlag.UNKNOWN
    assert pct is None


# ---------------------------------------------------------------------------
# Test 7: classify_snmp_value(150, 100) returns (QualityFlag.OUT_OF_RANGE, None)
# ---------------------------------------------------------------------------

def test_classify_out_of_range_returns_out_of_range():
    """Level 150 greater than max_capacity 100 maps to QualityFlag.OUT_OF_RANGE."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(150, 100)
    assert flag == QualityFlag.OUT_OF_RANGE
    assert pct is None


# ---------------------------------------------------------------------------
# Test 8: classify_snmp_value(0, 100) returns (QualityFlag.OK, 0.0)
# ---------------------------------------------------------------------------

def test_classify_zero_is_valid():
    """Zero toner level is valid (empty cartridge) — maps to QualityFlag.OK, 0.0%."""
    from adapters.snmp_adapter import classify_snmp_value
    from state_types import QualityFlag

    flag, pct = classify_snmp_value(0, 100)
    assert flag == QualityFlag.OK
    assert pct == 0.0


# ---------------------------------------------------------------------------
# Test 9: SNMPAdapter.poll() in mock mode returns PollResult with 4 readings
# ---------------------------------------------------------------------------

def test_mock_poll_returns_four_readings(monkeypatch):
    """SNMPAdapter.poll() in mock mode returns a PollResult with exactly 4 TonerReadings."""
    monkeypatch.setenv("USE_MOCK_SNMP", "true")

    from adapters.snmp_adapter import SNMPAdapter

    adapter = SNMPAdapter(host="192.168.1.100", community="public")
    result = adapter.poll()

    assert "readings" in result
    assert len(result["readings"]) == 4, (
        f"Expected 4 readings, got {len(result['readings'])}"
    )


# ---------------------------------------------------------------------------
# Test 10: Mock fixture sentinel values (-2, -3) produce data_quality_ok=False
# ---------------------------------------------------------------------------

def test_mock_fixture_sentinels_produce_bad_quality(monkeypatch):
    """Mock fixture includes -2 and -3 sentinels; those readings must have data_quality_ok=False."""
    monkeypatch.setenv("USE_MOCK_SNMP", "true")

    from adapters.snmp_adapter import SNMPAdapter

    adapter = SNMPAdapter(host="192.168.1.100", community="public")
    result = adapter.poll()

    # At least one reading must have data_quality_ok=False (from -2 or -3 sentinels)
    bad_readings = [r for r in result["readings"] if not r["data_quality_ok"]]
    assert len(bad_readings) >= 1, (
        "Expected at least one bad reading from sentinel fixture values (-2, -3)"
    )

    # Verify the bad readings are for magenta (-2) and yellow (-3) as per fixture
    bad_colors = {r["color"] for r in bad_readings}
    assert "magenta" in bad_colors, f"magenta not in bad readings; bad_colors={bad_colors}"
    assert "yellow" in bad_colors, f"yellow not in bad readings; bad_colors={bad_colors}"


# ---------------------------------------------------------------------------
# Test 11: Mock PollResult.overall_quality_ok is False
# ---------------------------------------------------------------------------

def test_mock_poll_overall_quality_ok_false(monkeypatch):
    """Mock PollResult.overall_quality_ok is False because fixture has sentinel values."""
    monkeypatch.setenv("USE_MOCK_SNMP", "true")

    from adapters.snmp_adapter import SNMPAdapter

    adapter = SNMPAdapter(host="192.168.1.100", community="public")
    result = adapter.poll()

    assert result["overall_quality_ok"] is False, (
        "overall_quality_ok must be False when any reading has bad quality"
    )


# ---------------------------------------------------------------------------
# Test 12: Mock PollResult.timestamp is a valid ISO 8601 UTC string
# ---------------------------------------------------------------------------

def test_mock_poll_timestamp_is_valid_iso8601(monkeypatch):
    """Mock PollResult.timestamp is a non-empty ISO 8601 string with timezone offset."""
    monkeypatch.setenv("USE_MOCK_SNMP", "true")

    from adapters.snmp_adapter import SNMPAdapter
    from datetime import datetime

    adapter = SNMPAdapter(host="192.168.1.100", community="public")
    result = adapter.poll()

    timestamp = result["timestamp"]
    assert isinstance(timestamp, str), f"timestamp must be str, got {type(timestamp)}"
    assert len(timestamp) > 0, "timestamp must not be empty"

    # Must be parseable as an ISO 8601 datetime
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise AssertionError(f"timestamp is not valid ISO 8601: {timestamp!r}") from exc

    # Must include timezone info (UTC offset)
    assert dt.tzinfo is not None, (
        f"timestamp must include timezone info, got: {timestamp!r}"
    )


# ---------------------------------------------------------------------------
# Test 13: Mock PollResult.printer_host matches the host passed to poll()
# ---------------------------------------------------------------------------

def test_mock_poll_printer_host_matches_input(monkeypatch):
    """Mock PollResult.printer_host matches the host argument passed to SNMPAdapter."""
    monkeypatch.setenv("USE_MOCK_SNMP", "true")

    from adapters.snmp_adapter import SNMPAdapter

    test_host = "10.0.0.55"
    adapter = SNMPAdapter(host=test_host, community="public")
    result = adapter.poll()

    assert result["printer_host"] == test_host, (
        f"Expected printer_host={test_host!r}, got {result['printer_host']!r}"
    )


# ---------------------------------------------------------------------------
# Test 14: No raw sentinel integers appear in any TonerReading.quality_flag field
# ---------------------------------------------------------------------------

def test_no_raw_sentinel_in_quality_flag(monkeypatch):
    """quality_flag fields must be QualityFlag string values, never raw integers like -2 or -3."""
    monkeypatch.setenv("USE_MOCK_SNMP", "true")

    from adapters.snmp_adapter import SNMPAdapter

    adapter = SNMPAdapter(host="192.168.1.100", community="public")
    result = adapter.poll()

    raw_sentinel_ints = {-1, -2, -3}

    for reading in result["readings"]:
        flag = reading["quality_flag"]
        assert isinstance(flag, str), (
            f"quality_flag must be a str, got {type(flag)} for color {reading['color']}"
        )
        # Must not be one of the raw SNMP sentinel integer strings either
        assert flag not in ("-1", "-2", "-3"), (
            f"quality_flag must not be a raw sentinel string, got {flag!r} for {reading['color']}"
        )
        # Must not be a raw integer
        assert flag not in raw_sentinel_ints, (
            f"quality_flag must not be a raw integer sentinel, got {flag!r} for {reading['color']}"
        )
