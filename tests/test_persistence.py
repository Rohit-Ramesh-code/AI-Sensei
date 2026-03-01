"""
tests/test_persistence.py — Tests for adapters/persistence.py JSONL persistence module.

Tests use temporary directories — no real logs/ directory is written during test runs.

Design: All tests inject a temp path via the log_path parameter of append_poll_result
and read_poll_history. This avoids patching globals and keeps tests isolated.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adapters.persistence import append_poll_result, read_poll_history


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_poll_result(
    printer_host: str = "192.168.1.100",
    overall_quality_ok: bool = True,
    quality_flag: str = "ok",
    data_quality_ok: bool = True,
) -> dict:
    """Return a minimal but valid PollResult dict for testing."""
    return {
        "printer_host": printer_host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readings": [
            {
                "color": "black",
                "raw_value": 85,
                "max_capacity": 100,
                "toner_pct": 85.0,
                "quality_flag": quality_flag,
                "data_quality_ok": data_quality_ok,
            }
        ],
        "snmp_error": None,
        "overall_quality_ok": overall_quality_ok,
    }


@pytest.fixture
def tmp_log(tmp_path: Path) -> Path:
    """Return a path inside a fresh temp directory that does NOT exist yet."""
    return tmp_path / "test_history.jsonl"


@pytest.fixture
def tmp_log_nested(tmp_path: Path) -> Path:
    """Return a nested path whose parent directory does NOT exist yet."""
    return tmp_path / "nested" / "subdir" / "history.jsonl"


# ---------------------------------------------------------------------------
# Test 1: append_poll_result() creates the file if it does not exist
# ---------------------------------------------------------------------------

def test_append_creates_file_if_not_exist(tmp_log: Path) -> None:
    """append_poll_result() creates logs/printer_history.jsonl if it does not exist."""
    assert not tmp_log.exists(), "Pre-condition: file must not exist before append"
    result = make_poll_result()
    append_poll_result(result, log_path=tmp_log)
    assert tmp_log.exists(), "File must be created by append_poll_result()"


# ---------------------------------------------------------------------------
# Test 2: append_poll_result() appends — calling twice produces two lines
# ---------------------------------------------------------------------------

def test_append_adds_one_line_per_call(tmp_log: Path) -> None:
    """append_poll_result() appends one line per call (call twice, get two lines)."""
    result = make_poll_result()
    append_poll_result(result, log_path=tmp_log)
    append_poll_result(result, log_path=tmp_log)
    lines = tmp_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, f"Expected 2 lines after 2 appends, got {len(lines)}"


# ---------------------------------------------------------------------------
# Test 3: Each appended line is valid JSON
# ---------------------------------------------------------------------------

def test_each_line_is_valid_json(tmp_log: Path) -> None:
    """Each appended line is valid JSON: json.loads(line) succeeds."""
    result = make_poll_result()
    append_poll_result(result, log_path=tmp_log)
    append_poll_result(result, log_path=tmp_log)
    lines = tmp_log.read_text(encoding="utf-8").strip().splitlines()
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert isinstance(parsed, dict), f"Line {i} must parse to a dict"


# ---------------------------------------------------------------------------
# Test 4: Appended line contains required fields
# ---------------------------------------------------------------------------

def test_appended_line_contains_required_fields(tmp_log: Path) -> None:
    """Appended line contains printer_host, timestamp, readings, snmp_error, overall_quality_ok."""
    result = make_poll_result()
    append_poll_result(result, log_path=tmp_log)
    line = tmp_log.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    required_keys = {"printer_host", "timestamp", "readings", "snmp_error", "overall_quality_ok"}
    missing = required_keys - parsed.keys()
    assert not missing, f"Missing required fields in logged line: {missing}"


# ---------------------------------------------------------------------------
# Test 5: overall_quality_ok=False is logged (no filtering of bad results)
# ---------------------------------------------------------------------------

def test_failed_poll_is_logged_without_filtering(tmp_log: Path) -> None:
    """Calling append_poll_result() with overall_quality_ok=False logs successfully (no filtering)."""
    result = make_poll_result(
        overall_quality_ok=False,
        quality_flag="snmp_error",
        data_quality_ok=False,
    )
    result["snmp_error"] = "Timeout reaching host"
    append_poll_result(result, log_path=tmp_log)
    assert tmp_log.exists(), "File must be created even for failed poll results"
    line = tmp_log.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["overall_quality_ok"] is False
    assert parsed["snmp_error"] == "Timeout reaching host"


# ---------------------------------------------------------------------------
# Test 6: read_poll_history() returns list of dicts matching what was written
# ---------------------------------------------------------------------------

def test_read_returns_written_records(tmp_log: Path) -> None:
    """read_poll_history() returns a list of dicts matching what was written."""
    result1 = make_poll_result(printer_host="10.0.0.1")
    result2 = make_poll_result(printer_host="10.0.0.2")
    append_poll_result(result1, log_path=tmp_log)
    append_poll_result(result2, log_path=tmp_log)
    history = read_poll_history(log_path=tmp_log)
    assert isinstance(history, list), "read_poll_history() must return a list"
    assert len(history) == 2, f"Expected 2 records, got {len(history)}"
    assert history[0]["printer_host"] == "10.0.0.1"
    assert history[1]["printer_host"] == "10.0.0.2"


# ---------------------------------------------------------------------------
# Test 7: read_poll_history() returns [] if file does not exist
# ---------------------------------------------------------------------------

def test_read_returns_empty_list_if_file_missing(tmp_path: Path) -> None:
    """read_poll_history() returns an empty list if the file does not exist (does not raise)."""
    nonexistent = tmp_path / "no_such_file.jsonl"
    assert not nonexistent.exists(), "Pre-condition: file must not exist"
    result = read_poll_history(log_path=nonexistent)
    assert result == [], f"Expected empty list, got {result!r}"


# ---------------------------------------------------------------------------
# Test 8: File is always opened in append mode — existing content is not truncated
# ---------------------------------------------------------------------------

def test_append_never_truncates_existing_content(tmp_log: Path) -> None:
    """File is always opened in append mode — existing content is never truncated."""
    result = make_poll_result(printer_host="first-write")
    append_poll_result(result, log_path=tmp_log)

    # First write recorded
    first_content = tmp_log.read_text(encoding="utf-8")
    assert "first-write" in first_content

    # Second write must NOT erase the first
    result2 = make_poll_result(printer_host="second-write")
    append_poll_result(result2, log_path=tmp_log)
    final_content = tmp_log.read_text(encoding="utf-8")
    assert "first-write" in final_content, "First write was truncated — mode='a' is required"
    assert "second-write" in final_content


# ---------------------------------------------------------------------------
# Test 9: logs/ parent directory is created if it does not exist
# ---------------------------------------------------------------------------

def test_parent_directory_created_if_missing(tmp_log_nested: Path) -> None:
    """logs/ parent directory is created if it does not exist (makedirs parents=True)."""
    assert not tmp_log_nested.parent.exists(), "Pre-condition: parent must not exist"
    result = make_poll_result()
    append_poll_result(result, log_path=tmp_log_nested)
    assert tmp_log_nested.parent.exists(), "Parent directory must be created by append_poll_result()"
    assert tmp_log_nested.exists(), "Log file must be created inside the new parent directory"


# ---------------------------------------------------------------------------
# Test 10: quality_flag value in logged reading is a string (not a QualityFlag enum)
# ---------------------------------------------------------------------------

def test_quality_flag_serialized_as_string(tmp_log: Path) -> None:
    """quality_flag value in logged reading is a string (not a QualityFlag enum instance)."""
    from state_types import QualityFlag

    result = make_poll_result()
    # Inject an actual QualityFlag enum instance to test that it serializes correctly
    result["readings"][0]["quality_flag"] = QualityFlag.OK  # enum instance
    append_poll_result(result, log_path=tmp_log)

    line = tmp_log.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    flag_value = parsed["readings"][0]["quality_flag"]
    assert isinstance(flag_value, str), (
        f"quality_flag must be a plain string in the log, got {type(flag_value).__name__!r}"
    )
    assert flag_value == "ok", f"Expected 'ok', got {flag_value!r}"
