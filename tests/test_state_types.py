"""
Tests for state_types.py — QualityFlag enum and TypedDict state contract.

All tests verify the public API contract that downstream agents depend on.
No external dependencies required — this is pure Python stdlib.
"""

from __future__ import annotations

import json
import operator
import sys
import os

# Ensure project root is on path so `state_types` is importable directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Test 1: QualityFlag.OK value is "ok"
# ---------------------------------------------------------------------------

def test_quality_flag_ok_value():
    """QualityFlag.OK.value == 'ok' — str mixin produces plain string value."""
    from state_types import QualityFlag

    assert QualityFlag.OK.value == "ok"


# ---------------------------------------------------------------------------
# Test 2: QualityFlag.UNKNOWN value is "unknown"
# ---------------------------------------------------------------------------

def test_quality_flag_unknown_value():
    """QualityFlag.UNKNOWN.value == 'unknown' — maps SNMP sentinel -2."""
    from state_types import QualityFlag

    assert QualityFlag.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# Test 3: QualityFlag.BELOW_LOW_THRESHOLD value
# ---------------------------------------------------------------------------

def test_quality_flag_below_low_threshold_value():
    """QualityFlag.BELOW_LOW_THRESHOLD.value == 'below_low_threshold' — maps SNMP sentinel -3."""
    from state_types import QualityFlag

    assert QualityFlag.BELOW_LOW_THRESHOLD.value == "below_low_threshold"


# ---------------------------------------------------------------------------
# Test 4: QualityFlag is JSON-serializable without a custom encoder
# ---------------------------------------------------------------------------

def test_quality_flag_json_serializable():
    """json.dumps({'flag': QualityFlag.OK}) succeeds — str mixin makes value a plain string."""
    from state_types import QualityFlag

    result = json.dumps({"flag": QualityFlag.OK})
    parsed = json.loads(result)
    assert parsed["flag"] == "ok", f"Expected 'ok', got {parsed['flag']!r}"


# ---------------------------------------------------------------------------
# Test 5: TonerReading can be constructed as a dict with all required keys
# ---------------------------------------------------------------------------

def test_toner_reading_construction():
    """TonerReading can be constructed as a plain dict with all expected fields."""
    from state_types import TonerReading, QualityFlag

    reading: TonerReading = {
        "color": "black",
        "raw_value": 85,
        "max_capacity": 100,
        "toner_pct": 85.0,
        "quality_flag": QualityFlag.OK.value,
        "data_quality_ok": True,
    }

    assert reading["color"] == "black"
    assert reading["raw_value"] == 85
    assert reading["max_capacity"] == 100
    assert reading["toner_pct"] == 85.0
    assert reading["quality_flag"] == "ok"
    assert reading["data_quality_ok"] is True


# ---------------------------------------------------------------------------
# Test 6: PollResult.overall_quality_ok is False when any reading is bad
# ---------------------------------------------------------------------------

def test_poll_result_overall_quality_ok_false_when_any_bad():
    """overall_quality_ok must be False when at least one reading has data_quality_ok=False."""
    from state_types import TonerReading, PollResult, QualityFlag

    good_reading: TonerReading = {
        "color": "black",
        "raw_value": 85,
        "max_capacity": 100,
        "toner_pct": 85.0,
        "quality_flag": QualityFlag.OK.value,
        "data_quality_ok": True,
    }
    bad_reading: TonerReading = {
        "color": "cyan",
        "raw_value": -2,
        "max_capacity": 100,
        "toner_pct": None,
        "quality_flag": QualityFlag.UNKNOWN.value,
        "data_quality_ok": False,
    }

    poll: PollResult = {
        "printer_host": "192.168.1.100",
        "timestamp": "2026-02-28T10:00:00+00:00",
        "readings": [good_reading, bad_reading],
        "snmp_error": None,
        "overall_quality_ok": all(r["data_quality_ok"] for r in [good_reading, bad_reading]),
    }

    assert poll["overall_quality_ok"] is False


# ---------------------------------------------------------------------------
# Test 7: AgentState has decision_log typed as Annotated[list[str], operator.add]
# ---------------------------------------------------------------------------

def test_agent_state_decision_log_annotated():
    """AgentState.decision_log field uses Annotated[list[str], operator.add] reducer."""
    import typing
    from state_types import AgentState

    hints = typing.get_type_hints(AgentState, include_extras=True)
    assert "decision_log" in hints, "AgentState must have a decision_log field"

    annotated_type = hints["decision_log"]
    # Annotated types have __metadata__ attribute containing the reducer
    assert hasattr(annotated_type, "__metadata__"), (
        "decision_log must be Annotated — it has no __metadata__ attribute"
    )
    metadata = annotated_type.__metadata__
    assert operator.add in metadata, (
        f"decision_log reducer must be operator.add, got metadata: {metadata}"
    )


# ---------------------------------------------------------------------------
# Test 8: Import of all four public names succeeds
# ---------------------------------------------------------------------------

def test_import_all_public_names():
    """from state_types import QualityFlag, TonerReading, PollResult, AgentState succeeds."""
    from state_types import QualityFlag, TonerReading, PollResult, AgentState  # noqa: F401

    # All four names must be importable without error
    assert QualityFlag is not None
    assert TonerReading is not None
    assert PollResult is not None
    assert AgentState is not None
