"""
agents/supervisor.py — LangGraph monitoring pipeline orchestrator for Project Sentinel.

Exposes:
  - build_graph() -> CompiledStateGraph  Factory that constructs and compiles the
    LangGraph StateGraph with all agent nodes and conditional routing. Call once
    at startup (in main.py) and reuse the returned compiled graph.
  - run_pipeline(poll_result=None) -> AgentState  Thin delegate to build_graph().invoke().
    Kept for backward compatibility and direct test/CLI invocation.

Graph topology:
  START -> analyst
  analyst -> policy_guard   (if alert_needed=True)
  analyst -> END            (if alert_needed=False)
  policy_guard -> communicator  (if suppression_reason is None)
  policy_guard -> END           (if suppression_reason is set)
  communicator -> END

Design decisions:
- load_dotenv() is intentionally omitted here — main.py calls it at entry point.
  (Phase 4 decision: supervisor.py must be importable without side-effects.)
- build_graph() is a factory function, NOT a module-level variable, so that
  main.py can call it once at startup and reuse the compiled graph efficiently.
- run_pipeline() builds a fresh initial AgentState and delegates to
  build_graph().invoke() — all five test_pipeline.py tests remain GREEN.
- _route_after_analyst and _route_after_policy_guard are named functions
  (not lambdas) for clarity and testability.

Environment variables:
  USE_MOCK_SNMP   — Set to 'true' to use mock SNMP fixture data (no real hardware)
  USE_MOCK_SMTP   — Set to 'true' to log emails instead of sending (no real SMTP)
  ALERT_RECIPIENT — Required by communicator if alert_needed=True
  TONER_ALERT_THRESHOLD    — Analyst warning threshold (default: 20%)
  TONER_CRITICAL_THRESHOLD — Analyst critical threshold (default: 10%)
  STALE_THRESHOLD_MINUTES  — Policy guard staleness threshold (default: 120)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

# load_dotenv() is intentionally omitted here — main.py calls it at entry point.

from langgraph.graph import END, START, StateGraph

from adapters.snmp_adapter import SNMPAdapter
from agents.analyst import run_analyst
from agents.communicator import run_communicator
from guardrails.safety_logic import run_policy_guard
from state_types import AgentState, PollResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def _route_after_analyst(state: AgentState) -> str:
    """Route to policy_guard if alert needed; skip to END otherwise."""
    return "policy_guard" if state["alert_needed"] else END


def _route_after_policy_guard(state: AgentState) -> str:
    """Route to communicator if not suppressed; skip to END otherwise."""
    return "communicator" if state["suppression_reason"] is None else END


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph():
    """
    Build and compile the Sentinel monitoring StateGraph.

    Constructs a StateGraph(AgentState) with three agent nodes and conditional
    routing edges:

      START -> analyst
      analyst --[alert_needed=True]--> policy_guard
      analyst --[alert_needed=False]--> END
      policy_guard --[suppression_reason=None]--> communicator
      policy_guard --[suppression_reason set]--> END
      communicator -> END

    Returns:
        CompiledStateGraph ready to invoke via graph.invoke(initial_state).

    Usage:
        graph = build_graph()   # Call once at startup
        result = graph.invoke(initial_state)
    """
    workflow = StateGraph(AgentState)

    # Register agent nodes
    workflow.add_node("analyst", run_analyst)
    workflow.add_node("policy_guard", run_policy_guard)
    workflow.add_node("communicator", run_communicator)

    # Entry point
    workflow.add_edge(START, "analyst")

    # Conditional routing after analyst
    workflow.add_conditional_edges("analyst", _route_after_analyst)

    # Conditional routing after policy_guard
    workflow.add_conditional_edges("policy_guard", _route_after_policy_guard)

    # Communicator always ends the graph
    workflow.add_edge("communicator", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Pipeline entry point (thin delegate)
# ---------------------------------------------------------------------------

def run_pipeline(poll_result: Optional[PollResult] = None) -> AgentState:
    """
    Run the complete monitoring pipeline via the LangGraph StateGraph.

    Builds a fresh initial AgentState, then delegates to build_graph().invoke().
    Backward-compatible with Phase 2/3 callers and all existing tests.

    Args:
        poll_result: Pre-fetched PollResult to inject. If None, polls the SNMP
                     adapter using SNMPAdapter() (respects USE_MOCK_SNMP env var).

    Returns:
        Final AgentState after all pipeline stages have run.
    """
    if poll_result is None:
        host = os.getenv("SNMP_HOST", "localhost")
        community = os.getenv("SNMP_COMMUNITY", "public")
        snmp = SNMPAdapter(host=host, community=community)
        poll_result = snmp.poll()

    # Build initial state with all required AgentState keys
    initial_state: AgentState = {
        "poll_result": poll_result,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
        "llm_confidence": None,    # Phase 3: analyst writes; policy guard reads
        "llm_reasoning": None,     # Phase 3: analyst writes; communicator reads
    }

    # Delegate to compiled graph
    graph = build_graph()
    state = graph.invoke(initial_state)

    logger.info(
        "Pipeline complete: alert_needed=%s alert_sent=%s suppression=%s",
        state["alert_needed"],
        state["alert_sent"],
        state["suppression_reason"],
    )

    return state
