"""
agents/analyst.py — LLM-powered trend analyst for Project Sentinel.

Implements run_analyst(state: AgentState) -> AgentState, which:
1. Runs deterministic threshold checks to identify flagged colors.
2. For each flagged color, calls an Ollama-hosted LLM via langchain-openai to
   produce a structured AnalystOutput with trend label, depletion estimate,
   confidence, and reasoning.
3. Falls back to deterministic logic only on LLM failure (any exception).
   Failure path sets llm_confidence=None and llm_reasoning=None.

Design decisions:
- AnalystOutput is a Pydantic BaseModel enforcing confidence float 0.0-1.0 at
  the LLM boundary.
- compute_color_stats() uses actual timestamps for velocity (not assumed hourly
  intervals) and filters non-poll records (event_type key set).
- call_llm_analyst() catches all exceptions immediately — no retry. Logs
  event_type=llm_failure to JSONL and returns None on failure.
- run_analyst() sets llm_confidence to the minimum across all LLM-analyzed
  colors (conservative: alert gates on weakest confidence).
- USE_MOCK_LLM env var (default: false) bypasses the real LLM call in tests.
- log_path parameter on run_analyst() enables test isolation without patching
  globals.
- BELOW_LOW_THRESHOLD (SNMP sentinel -3) is treated as CRITICAL regardless of
  data_quality_ok.
- decision_log uses list concatenation (not .append()) for LangGraph
  Annotated[list, operator.add] reducer compatibility.

Environment variables:
  TONER_ALERT_THRESHOLD    — Float percentage below which WARNING is raised (default: 20.0)
  TONER_CRITICAL_THRESHOLD — Float percentage below which CRITICAL is raised (default: 10.0)
  USE_MOCK_LLM             — Set to 'true' to bypass real LLM call in tests (default: false)
  OLLAMA_BASE_URL          — Ollama OpenAI-compatible API base URL (default: http://localhost:11434/v1)
  OLLAMA_MODEL             — Ollama model name (default: llama3.2)
  OLLAMA_API_KEY           — Ollama API key (default: ollama — Ollama ignores this)
"""

from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from adapters.persistence import append_poll_result, read_poll_history
from state_types import AgentState, QualityFlag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# USE_MOCK_LLM — bypass real LLM call in tests
# ---------------------------------------------------------------------------

USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "false").lower() == "true"


# ---------------------------------------------------------------------------
# AnalystOutput — structured LLM response schema
# ---------------------------------------------------------------------------

class AnalystOutput(BaseModel):
    """Structured output from the LLM analyst for a single color cartridge."""

    trend_label: str = Field(
        description="One of: 'Stable', 'Declining slowly', 'Declining rapidly', 'Critically low'"
    )
    depletion_estimate_days: Optional[float] = Field(
        description="Days until depletion at current rate; None if stable or rising"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Self-reported confidence 0.0-1.0; lower when readings are erratic or sparse"
    )
    reasoning: str = Field(
        description="2-3 sentence natural language explanation: trend, estimate, confidence factors"
    )


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT — passed as the system message to the LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a printer supply analyst for Project Sentinel.
Analyze pre-computed toner level statistics from the last 7 days and produce a structured assessment.

Output requirements:
- trend_label: exactly one of "Stable", "Declining slowly", "Declining rapidly", "Critically low"
- depletion_estimate_days: float (days to depletion at current rate) or null if stable/rising
- confidence: float 0.0-1.0 (lower when std_dev is high = erratic readings, or n is low)
- reasoning: 2-3 sentences covering trend direction, depletion estimate, and confidence factors
"""


# ---------------------------------------------------------------------------
# compute_color_stats — pre-compute history stats for a single color
# ---------------------------------------------------------------------------

def compute_color_stats(
    color: str,
    log_path: Path,
    window_days: int = 7,
) -> dict:
    """
    Load 7-day toner history for a color and compute velocity and standard deviation.

    Args:
        color:       Color name ("cyan", "magenta", "yellow", "black").
        log_path:    Path to the JSONL history file.
        window_days: Number of days to look back (default: 7).

    Returns:
        dict with keys:
          n                    — total readings in window
          std_dev              — stdev of toner_pct values (None if n < 2)
          velocity_pct_per_day — rate of change in %/day using first/last timestamps
                                 (None if n < 2; negative = declining)
    """
    history = read_poll_history(log_path=log_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    pairs: list[tuple[str, float]] = []  # (timestamp_iso, toner_pct)

    for record in history:
        # Skip non-poll records (suppression events, llm_failure events, etc.)
        if record.get("event_type") is not None:
            continue

        # Filter by timestamp window
        ts_str = record.get("timestamp")
        if ts_str is None:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            # Normalize to UTC-aware if naive
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue

        # Extract readings for this color
        for reading in record.get("readings", []):
            if reading.get("color") == color and reading.get("toner_pct") is not None:
                pairs.append((ts_str, reading["toner_pct"]))

    n = len(pairs)

    if n < 2:
        return {"n": n, "std_dev": None, "velocity_pct_per_day": None}

    # Compute standard deviation across all toner_pct values
    pct_values = [pct for _, pct in pairs]
    std_dev = statistics.stdev(pct_values)

    # Compute velocity using actual timestamps (first vs. last entry)
    first_ts = datetime.fromisoformat(pairs[0][0])
    last_ts = datetime.fromisoformat(pairs[-1][0])
    if first_ts.tzinfo is None:
        first_ts = first_ts.replace(tzinfo=timezone.utc)
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)

    elapsed_hours = max((last_ts - first_ts).total_seconds() / 3600, 1.0)
    velocity_pct_per_day = (pairs[-1][1] - pairs[0][1]) / elapsed_hours * 24

    return {
        "n": n,
        "std_dev": round(std_dev, 2),
        "velocity_pct_per_day": round(velocity_pct_per_day, 3),
    }


# ---------------------------------------------------------------------------
# _mock_analyst_output — deterministic mock for USE_MOCK_LLM=true
# ---------------------------------------------------------------------------

def _mock_analyst_output(current_pct: float) -> AnalystOutput:
    """Return a fixed AnalystOutput for test isolation (USE_MOCK_LLM=true)."""
    return AnalystOutput(
        trend_label="Declining rapidly",
        depletion_estimate_days=5.0,
        confidence=0.85,
        reasoning=(
            f"Toner at {current_pct}% with a steady decline over the history window. "
            "Depletion estimated in approximately 5 days at current rate. "
            "Confidence is high due to consistent readings."
        ),
    )


# ---------------------------------------------------------------------------
# call_llm_analyst — invoke the LLM with pre-computed stats
# ---------------------------------------------------------------------------

def call_llm_analyst(
    color: str,
    current_pct: float,
    stats: dict,
    log_path: Path,
) -> Optional[AnalystOutput]:
    """
    Call the Ollama LLM analyst with pre-computed color stats.

    Returns an AnalystOutput on success, or None on any failure (logs
    event_type=llm_failure to JSONL and returns None immediately — no retry).

    Args:
        color:       Color cartridge name.
        current_pct: Current toner percentage.
        stats:       Pre-computed stats dict from compute_color_stats().
        log_path:    Path for llm_failure event logging.
    """
    # Re-read USE_MOCK_LLM at call time to respect per-test env var changes
    use_mock = os.getenv("USE_MOCK_LLM", "false").lower() == "true"
    if use_mock:
        return _mock_analyst_output(current_pct)

    # Build the history summary string (pre-computed stats only — no raw JSONL)
    n = stats.get("n", 0)
    velocity = stats.get("velocity_pct_per_day")
    std_dev = stats.get("std_dev")

    if velocity is not None and std_dev is not None:
        history_summary = (
            f"Current level: {current_pct}%\n"
            f"Readings in last 7 days: {n}\n"
            f"Velocity: {velocity:.3f} %/day (negative = declining)\n"
            f"Std dev: {std_dev:.2f}%"
        )
    else:
        history_summary = (
            f"Current level: {current_pct}%\n"
            f"Readings in last 7 days: {n}\n"
            "(Insufficient history for velocity/std_dev calculation)"
        )

    messages = [
        SystemMessage(SYSTEM_PROMPT),
        HumanMessage(f"Color: {color}\n{history_summary}"),
    ]

    try:
        llm = ChatOpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            temperature=0,
        )
        # Try json_schema first; fall back to json_mode if model does not support it
        try:
            structured_llm = llm.with_structured_output(AnalystOutput, method="json_schema")
            return structured_llm.invoke(messages)
        except Exception:
            structured_llm = llm.with_structured_output(AnalystOutput, method="json_mode")
            return structured_llm.invoke(messages)

    except Exception as exc:
        logger.error(
            "LLM analyst failed for %s: %s: %s", color, type(exc).__name__, exc
        )
        append_poll_result(
            {
                "event_type": "llm_failure",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "color": color,
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
            },
            log_path=log_path,
        )
        return None


# ---------------------------------------------------------------------------
# _run_deterministic — Phase 2 deterministic threshold logic (private helper)
# ---------------------------------------------------------------------------

def _run_deterministic(
    state: AgentState,
    flagged: list[dict],
) -> None:
    """
    Update state with deterministic threshold results (no LLM).

    Mutates state in-place: sets alert_needed, flagged_colors, decision_log.
    Does NOT set llm_confidence or llm_reasoning (caller handles those).

    Args:
        state:   AgentState to update.
        flagged: List of flagged color dicts already computed by run_analyst().
    """
    state["flagged_colors"] = flagged
    state["alert_needed"] = len(flagged) > 0
    log_entry = (
        f"analyst: {len(flagged)} colors flagged, alert_needed={state['alert_needed']}"
    )
    logger.info(log_entry)
    state["decision_log"] = state["decision_log"] + [log_entry]


# ---------------------------------------------------------------------------
# run_analyst — main entry point
# ---------------------------------------------------------------------------

def run_analyst(state: AgentState, *, log_path: Path = None) -> AgentState:
    """
    Inspect each toner reading, flag colors that need attention, and call the
    LLM analyst for trend analysis (with cold start and failure fallbacks).

    Args:
        state:    Current AgentState from the LangGraph pipeline.
        log_path: Path to JSONL history file. Defaults to adapters.persistence.LOG_PATH.
                  Pass a temp path in tests to avoid touching real logs/.

    Returns:
        Updated AgentState with alert_needed, flagged_colors, decision_log,
        llm_confidence, and llm_reasoning populated.
    """
    if log_path is None:
        from adapters.persistence import LOG_PATH as _LOG_PATH
        log_path = _LOG_PATH

    alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
    critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))

    # --- Early exit: no poll data ---
    if state["poll_result"] is None:
        log_entry = "analyst: no poll_result available, skipping threshold analysis"
        logger.info(log_entry)
        state["decision_log"] = state["decision_log"] + [log_entry]
        state["alert_needed"] = False
        state["llm_confidence"] = None
        state["llm_reasoning"] = None
        return state

    # --- Iterate readings and classify (deterministic threshold logic) ---
    flagged: list[dict] = []
    readings = state["poll_result"]["readings"]

    for reading in readings:
        color = reading["color"]
        quality_flag = reading["quality_flag"]
        toner_pct = reading["toner_pct"]
        data_quality_ok = reading["data_quality_ok"]

        if quality_flag == QualityFlag.BELOW_LOW_THRESHOLD.value:
            # SNMP sentinel -3: toner is present but unquantified — always CRITICAL
            flagged.append({
                "color": color,
                "urgency": "CRITICAL",
                "display_value": "below low threshold (unquantified)",
            })
            logger.debug("analyst: %s flagged CRITICAL (BELOW_LOW_THRESHOLD)", color)

        elif data_quality_ok and toner_pct is not None:
            # Valid numeric reading — apply two-tier threshold check
            if toner_pct < critical_threshold:
                flagged.append({
                    "color": color,
                    "urgency": "CRITICAL",
                    "display_value": f"{toner_pct}%",
                })
                logger.debug(
                    "analyst: %s flagged CRITICAL (%.1f%% < %.1f%% critical threshold)",
                    color, toner_pct, critical_threshold,
                )
            elif toner_pct < alert_threshold:
                flagged.append({
                    "color": color,
                    "urgency": "WARNING",
                    "display_value": f"{toner_pct}%",
                })
                logger.debug(
                    "analyst: %s flagged WARNING (%.1f%% < %.1f%% alert threshold)",
                    color, toner_pct, alert_threshold,
                )
            # else: above alert threshold — no flag needed

        else:
            # UNKNOWN, SNMP_ERROR, NULL_VALUE, NOT_SUPPORTED, OUT_OF_RANGE — skip silently
            logger.debug("analyst: %s skipped (quality_flag=%s)", color, quality_flag)

    # --- Update state with deterministic results ---
    _run_deterministic(state, flagged)

    # --- Early exit: no alert needed — skip LLM ---
    if not state["alert_needed"]:
        state["llm_confidence"] = None
        state["llm_reasoning"] = None
        return state

    # --- LLM analysis per flagged color ---
    # Build a lookup from color -> toner_pct for flagged colors
    color_pct: dict[str, Optional[float]] = {}
    for reading in readings:
        color_pct[reading["color"]] = reading.get("toner_pct")

    llm_confidences: list[float] = []
    llm_reasonings: list[str] = []

    for item in flagged:
        color = item["color"]
        current_pct = color_pct.get(color)

        # If toner_pct is None (BELOW_LOW_THRESHOLD), use 0.0 as a proxy for stats
        pct_for_stats = current_pct if current_pct is not None else 0.0

        # Compute history stats for this color
        stats = compute_color_stats(color, log_path)

        # Call LLM analyst
        result = call_llm_analyst(color, pct_for_stats, stats, log_path)

        if result is None:
            # LLM failure — keep deterministic urgency, log the event
            log_entry = (
                f"analyst: LLM failed for {color} — using deterministic fallback"
            )
            logger.warning(log_entry)
            state["decision_log"] = state["decision_log"] + [log_entry]
            continue

        # LLM success — override urgency from trend_label
        trend_label = result.trend_label
        urgency_map = {
            "Critically low": "CRITICAL",
            "Declining rapidly": "CRITICAL",
            "Declining slowly": "WARNING",
            "Stable": None,  # keep deterministic urgency
        }
        new_urgency = urgency_map.get(trend_label)
        if new_urgency is not None:
            item["urgency"] = new_urgency

        llm_confidences.append(result.confidence)
        llm_reasonings.append(result.reasoning)

        log_entry = (
            f"analyst: {color} LLM result — "
            f"trend={trend_label}, confidence={result.confidence:.2f}, "
            f"depletion={result.depletion_estimate_days} days"
        )
        logger.info(log_entry)
        state["decision_log"] = state["decision_log"] + [log_entry]

    # --- LLM unavailable fallback note ---
    if not llm_confidences:
        # All colors were cold start or LLM failure — no LLM was called
        state["llm_confidence"] = None
        state["llm_reasoning"] = None
        fallback_entry = "analyst: LLM unavailable — using deterministic fallback"
        state["decision_log"] = state["decision_log"] + [fallback_entry]
    else:
        # Set minimum confidence (conservative: alert gates on weakest signal)
        state["llm_confidence"] = min(llm_confidences)
        # Combine reasoning (multiple colors separated by newline)
        state["llm_reasoning"] = "\n".join(llm_reasonings)

    return state
