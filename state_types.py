"""
state_types.py — Data contract for the Project Sentinel LangGraph pipeline.

This module defines all shared type definitions consumed by every downstream
agent node (Monitor, Analyst, Policy Guard, Communicator). Import from here;
do not redefine these types elsewhere.

Design decisions:
- TypedDict only — no Pydantic, no dataclasses. TypedDict is native to
  LangGraph and adds zero external dependencies.
- QualityFlag is a str Enum so its .value is a plain JSON-serializable string.
  No custom JSONEncoder needed: json.dumps({"flag": QualityFlag.OK}) just works.
- AgentState.decision_log uses Annotated[list[str], operator.add] so that
  LangGraph's reducer merges log entries from concurrent nodes instead of
  overwriting them.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Optional, TypedDict


# ---------------------------------------------------------------------------
# QualityFlag — toner reading validity encoding
# ---------------------------------------------------------------------------

class QualityFlag(str, Enum):
    """
    Encodes the validity state of a single toner reading from an SNMP poll.

    The str mixin makes each value a plain Python string, so QualityFlag.OK
    serialises to JSON as "ok" without any custom encoder.

    Standard RFC 3805 / Printer-MIB sentinel values:
      -1 = other / not applicable
      -2 = unknown (device cannot measure the supply level)
      -3 = present but unquantified (below low threshold, some toner remains)
    """

    OK = "ok"                                      # Valid percentage in [0, max_capacity]
    UNKNOWN = "unknown"                            # SNMP sentinel -2: device reports unknown
    BELOW_LOW_THRESHOLD = "below_low_threshold"    # SNMP sentinel -3: some remains, unquantified
    NOT_SUPPORTED = "not_supported"                # SNMP sentinel -1: not applicable
    STALE = "stale"                                # Timestamp too old (reserved for Phase 2+)
    NULL_VALUE = "null_value"                      # None / missing from SNMP response
    OUT_OF_RANGE = "out_of_range"                  # Value outside [0, max_capacity]
    SNMP_ERROR = "snmp_error"                      # SNMP transport / protocol failure


# ---------------------------------------------------------------------------
# TonerReading — single-color toner reading from one SNMP poll
# ---------------------------------------------------------------------------

class TonerReading(TypedDict):
    """
    Represents the toner state for a single color cartridge at one point in time.

    color          — "cyan" | "magenta" | "yellow" | "black"
    raw_value      — Raw integer returned by prtMarkerSuppliesLevel (may be -2, -3, etc.)
    max_capacity   — Raw integer returned by prtMarkerSuppliesMaxCapacity
    toner_pct      — Computed percentage [0.0, 100.0]; None when quality_flag != OK
    quality_flag   — QualityFlag.value string (always a plain str — JSON-safe)
    data_quality_ok — True only when quality_flag == QualityFlag.OK.value
    """

    color: str
    raw_value: int
    max_capacity: int
    toner_pct: Optional[float]
    quality_flag: str
    data_quality_ok: bool


# ---------------------------------------------------------------------------
# PollResult — output of one complete SNMP poll cycle for one printer
# ---------------------------------------------------------------------------

class PollResult(TypedDict):
    """
    Aggregated result of polling all four CMYK cartridges from one printer.

    printer_host     — IP address or hostname polled
    timestamp        — ISO 8601 UTC string, e.g. "2026-02-28T10:00:00+00:00"
    readings         — One TonerReading per CMYK color (four entries in v1)
    snmp_error       — Error message string if transport failed; None on success
    overall_quality_ok — True only if ALL readings have data_quality_ok=True
    """

    printer_host: str
    timestamp: str
    readings: list[TonerReading]
    snmp_error: Optional[str]
    overall_quality_ok: bool


# ---------------------------------------------------------------------------
# AgentState — LangGraph graph state flowing through all nodes
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """
    Shared state object passed between every node in the LangGraph pipeline.

    Data flow: SNMP Adapter → Monitor → Analyst → Policy Guard → Communicator.

    decision_log uses Annotated[list[str], operator.add] so that LangGraph
    merges log entries from each node instead of overwriting previous entries.
    This is the canonical LangGraph pattern for accumulating list values.

    LLM fields (Phase 3): analyst writes llm_confidence and llm_reasoning;
    policy guard reads llm_confidence to enforce the confidence threshold;
    communicator reads llm_reasoning to include the analysis section in the
    alert email body. Both are None when the LLM was not called (cold start
    or LLM failure), in which case deterministic fallback logic applies.

    poll_result        — Populated by the Monitor node after SNMP poll
    alert_needed       — Set True by the Analyst when toner is below threshold
    alert_sent         — Set True by the Communicator after a successful send
    suppression_reason — Human-readable reason set by Policy Guard when blocked
    decision_log       — Append-only log; each node appends its own entry
    flagged_colors     — List of flagged color dicts from Analyst; None until Analyst runs
    llm_confidence     — LLM self-reported confidence 0.0–1.0; None when LLM not called
    llm_reasoning      — 2-3 sentence natural language analysis; None when LLM not called
    """

    poll_result: Optional[PollResult]
    alert_needed: bool
    alert_sent: bool
    suppression_reason: Optional[str]
    decision_log: Annotated[list[str], operator.add]
    flagged_colors: Optional[list]  # Pipeline carrier: list of flagged color dicts from Analyst
    llm_confidence: Optional[float]   # LLM self-reported confidence 0.0–1.0; None when LLM not called (cold start / LLM failure)
    llm_reasoning: Optional[str]      # 2-3 sentence natural language analysis; None when LLM not called
