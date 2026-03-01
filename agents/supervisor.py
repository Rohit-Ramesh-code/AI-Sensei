"""
agents/supervisor.py — Sequential monitoring pipeline coordinator for Project Sentinel.

Implements run_pipeline(poll_result=None) -> AgentState, which sequences the
full agent pipeline:

    SNMP poll -> analyst -> policy_guard -> communicator

Design decisions:
- Phase 2 implementation: plain sequential function, not a LangGraph StateGraph.
  LangGraph StateGraph wiring is reserved for Phase 4 per the project roadmap.
- asyncio.run() is used for the async SNMP poll — consistent with the pattern
  established in Phase 1 (snmp_adapter.py decision log).
- policy_guard runs only when alert_needed=True (skip if analyst found nothing).
- communicator runs only when alert_needed=True AND suppression_reason is None
  (i.e., the policy guard cleared the alert).
- AgentState is initialised with all required keys before the first agent runs.

Environment variables:
  USE_MOCK_SNMP   — Set to 'true' to use mock SNMP fixture data (no real hardware)
  USE_MOCK_SMTP   — Set to 'true' to log emails instead of sending (no real SMTP)
  ALERT_RECIPIENT — Required by communicator if alert_needed=True
  TONER_ALERT_THRESHOLD    — Analyst warning threshold (default: 20%)
  TONER_CRITICAL_THRESHOLD — Analyst critical threshold (default: 10%)
  STALE_THRESHOLD_MINUTES  — Policy guard staleness threshold (default: 120)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from adapters.snmp_adapter import SNMPAdapter
from agents.analyst import run_analyst
from agents.communicator import run_communicator
from guardrails.safety_logic import run_policy_guard
from state_types import AgentState, PollResult

logger = logging.getLogger(__name__)


def run_pipeline(poll_result: Optional[PollResult] = None) -> AgentState:
    """
    Run the complete monitoring pipeline in sequence.

    Phase 2: Plain sequential function. LangGraph StateGraph wiring is Phase 4.

    Pipeline stages:
      1. SNMP poll    — if poll_result is None, polls the adapter
      2. Analyst      — checks toner levels against thresholds
      3. Policy Guard — validates freshness, SNMP quality, rate limit (if needed)
      4. Communicator — sends alert email (if guard cleared)

    Args:
        poll_result: Pre-fetched PollResult to inject. If None, polls the SNMP
                     adapter using SNMPAdapter() (respects USE_MOCK_SNMP env var).

    Returns:
        Final AgentState after all pipeline stages have run.
    """
    if poll_result is None:
        snmp = SNMPAdapter()
        poll_result = asyncio.run(snmp.poll())

    # Initialise state with all required keys
    state: AgentState = {
        "poll_result": poll_result,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
    }

    # Stage 1: Analyst — determine if any colors are below threshold
    state = run_analyst(state)

    # Stage 2: Policy Guard — only run if analyst flagged something
    if state["alert_needed"]:
        state = run_policy_guard(state)

    # Stage 3: Communicator — only run if alert cleared all policy checks
    if state["alert_needed"] and state["suppression_reason"] is None:
        state = run_communicator(state)

    logger.info(
        "Pipeline complete: alert_needed=%s alert_sent=%s suppression=%s",
        state["alert_needed"],
        state["alert_sent"],
        state["suppression_reason"],
    )

    return state
