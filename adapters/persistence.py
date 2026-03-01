"""
adapters/persistence.py — JSONL persistence layer for Project Sentinel.

Every SNMP poll result is durably logged to a JSON Lines file before the
Phase 2 policy guard and analyst reason about history. This module provides:

  append_poll_result() — append one PollResult dict as a JSON line (always mode='a')
  read_poll_history()  — read back the full history as a list of PollResult dicts

Design decisions:
- JSON Lines (one JSON object per line) makes partial reads safe and streaming
  reads memory-efficient even when the log grows to thousands of entries.
- mode='a' is critical — 'w' would truncate the entire history on every poll.
- The log_path parameter (with a default) lets tests inject a temp path without
  patching globals, keeping tests isolated and fast.
- QualityFlag is a str Enum so its .value is already a plain string; no custom
  JSONEncoder is needed for correct serialization.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jsonlines

if TYPE_CHECKING:
    from state_types import PollResult

# ---------------------------------------------------------------------------
# Default log path — relative to the project root where main.py runs
# ---------------------------------------------------------------------------

LOG_PATH = Path("logs/printer_history.jsonl")


# ---------------------------------------------------------------------------
# append_poll_result — write one PollResult to the JSONL log
# ---------------------------------------------------------------------------

def append_poll_result(result: "PollResult", log_path: Path = LOG_PATH) -> None:
    """
    Append a single PollResult dict to the JSON Lines log file.

    The parent directory is created if it does not exist (parents=True).
    The file is always opened in append mode — existing lines are never lost.

    Args:
        result:   A PollResult TypedDict (or any compatible dict).
        log_path: Path to the JSONL log file. Defaults to LOG_PATH.
                  Pass a temp path in tests to avoid touching real logs/.
    """
    # Ensure the parent directory exists (e.g., logs/ on first run)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # mode='a' is critical — 'w' would truncate the entire history on every poll.
    # jsonlines handles newline insertion between records automatically.
    with jsonlines.open(str(log_path), mode="a") as writer:
        writer.write(result)


# ---------------------------------------------------------------------------
# read_poll_history — read the full JSONL log back as a list
# ---------------------------------------------------------------------------

def read_poll_history(log_path: Path = LOG_PATH) -> list["PollResult"]:
    """
    Read the full poll history from the JSON Lines log file.

    Returns an empty list if the file does not exist (no exception raised).
    Useful for the Phase 2 analyst and policy guard to inspect historical trends.

    Args:
        log_path: Path to the JSONL log file. Defaults to LOG_PATH.

    Returns:
        A list of PollResult dicts in the order they were written.
        Returns [] if the file does not exist.
    """
    if not log_path.exists():
        return []

    with jsonlines.open(str(log_path), mode="r") as reader:
        return list(reader)
