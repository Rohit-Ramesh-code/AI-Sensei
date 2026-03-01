"""
agents/analyst.py — Deterministic threshold checker for Project Sentinel.

Implements run_analyst(state: AgentState) -> AgentState, which inspects each
TonerReading from the SNMP poll result and flags any color cartridge that has
dropped below the configured alert threshold.

Design decisions:
- No LLM involved. This is pure comparison logic against environment-configured
  thresholds. Speed and predictability matter more than inference here.
- BELOW_LOW_THRESHOLD (SNMP sentinel -3) is treated as CRITICAL regardless of
  data_quality_ok, because it means toner is present but unquantified — the
  printer cannot measure how little remains.
- Only OK readings with numeric toner_pct are checked against thresholds.
  UNKNOWN, SNMP_ERROR, NULL_VALUE, NOT_SUPPORTED, and OUT_OF_RANGE readings
  are silently skipped — they do not trigger alerts.
- decision_log uses list concatenation (not .append()) to stay compatible with
  LangGraph's Annotated[list, operator.add] reducer pattern in Phase 4.

Environment variables:
  TONER_ALERT_THRESHOLD    — Float percentage below which WARNING is raised (default: 20.0)
  TONER_CRITICAL_THRESHOLD — Float percentage below which CRITICAL is raised (default: 10.0)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from state_types import AgentState, QualityFlag

logger = logging.getLogger(__name__)


def run_analyst(state: AgentState) -> AgentState:
    """
    Inspect each toner reading and flag colors that need attention.

    Args:
        state: Current AgentState from the LangGraph pipeline.

    Returns:
        Updated AgentState with alert_needed, flagged_colors, and decision_log populated.
    """
    alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
    critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))

    # --- Early exit: no poll data ---
    if state["poll_result"] is None:
        log_entry = "analyst: no poll_result available, skipping threshold analysis"
        logger.info(log_entry)
        state["decision_log"] = state["decision_log"] + [log_entry]
        state["alert_needed"] = False
        return state

    # --- Iterate readings and classify ---
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

    # --- Update state ---
    state["flagged_colors"] = flagged
    state["alert_needed"] = len(flagged) > 0

    log_entry = (
        f"analyst: {len(flagged)} colors flagged, alert_needed={state['alert_needed']}"
    )
    logger.info(log_entry)
    state["decision_log"] = state["decision_log"] + [log_entry]

    return state
