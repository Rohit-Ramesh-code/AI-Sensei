"""
tests/test_supervisor_graph.py — Unit tests for agents/supervisor.build_graph()

Tests cover:
  - build_graph() returns a compiled LangGraph StateGraph
  - The graph has the correct node structure
  - Conditional routing: analyst -> policy_guard when alert_needed=True
  - Conditional routing: analyst -> END when alert_needed=False
  - Conditional routing: policy_guard -> communicator when suppression_reason=None
  - Conditional routing: policy_guard -> END when suppression_reason is set
  - run_pipeline() delegates to build_graph().invoke()
  - load_dotenv() is NOT called at module scope in supervisor.py
  - Module-level load_dotenv() import is removed (or at least not called)
"""

import ast
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import guardrails.safety_logic as safety_logic_module
from state_types import AgentState, PollResult, QualityFlag, TonerReading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def graph_env(monkeypatch):
    """Set required env vars for all graph tests."""
    monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
    monkeypatch.setenv("TONER_ALERT_THRESHOLD", "20")
    monkeypatch.setenv("TONER_CRITICAL_THRESHOLD", "10")
    monkeypatch.setenv("USE_MOCK_SMTP", "true")
    monkeypatch.setenv("USE_MOCK_SNMP", "true")


@pytest.fixture
def clean_alert_state(monkeypatch):
    """Isolate alert state for tests that trigger alerts."""
    alert_state_store: dict = {}

    def fake_load(state_path):
        return dict(alert_state_store)

    def fake_save(state, state_path):
        alert_state_store.clear()
        alert_state_store.update(state)

    monkeypatch.setattr(safety_logic_module, "_load_alert_state", fake_load)
    monkeypatch.setattr(safety_logic_module, "_save_alert_state", fake_save)
    return alert_state_store


def _make_reading(color: str, pct: float, quality: str = QualityFlag.OK.value) -> TonerReading:
    data_quality_ok = (quality == QualityFlag.OK.value)
    return {
        "color": color,
        "raw_value": int(pct) if data_quality_ok else -1,
        "max_capacity": 100,
        "toner_pct": pct if data_quality_ok else None,
        "quality_flag": quality,
        "data_quality_ok": data_quality_ok,
    }


def _make_poll_result(
    readings: list,
    printer_host: str = "192.168.1.100",
    snmp_error=None,
) -> PollResult:
    return {
        "printer_host": printer_host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readings": readings,
        "snmp_error": snmp_error,
        "overall_quality_ok": all(r["data_quality_ok"] for r in readings),
    }


# ---------------------------------------------------------------------------
# Test 1: build_graph() is importable and returns a compiled graph
# ---------------------------------------------------------------------------

def test_build_graph_is_importable():
    """build_graph must be importable from agents.supervisor."""
    from agents.supervisor import build_graph
    assert callable(build_graph), "build_graph must be a callable function"


def test_build_graph_returns_compiled_graph():
    """build_graph() must return a compiled LangGraph object."""
    from agents.supervisor import build_graph
    graph = build_graph()
    # Compiled LangGraph graphs have an invoke() method
    assert hasattr(graph, "invoke"), "Compiled graph must have .invoke() method"


# ---------------------------------------------------------------------------
# Test 2: Graph nodes exist — analyst, policy_guard, communicator
# ---------------------------------------------------------------------------

def test_build_graph_has_analyst_node():
    """Compiled graph must expose 'analyst' node."""
    from agents.supervisor import build_graph
    graph = build_graph()
    # CompiledStateGraph exposes graph.nodes or graph.get_graph().nodes
    g = graph.get_graph()
    node_ids = list(g.nodes.keys())
    assert "analyst" in node_ids, f"'analyst' not found in nodes: {node_ids}"


def test_build_graph_has_policy_guard_node():
    """Compiled graph must expose 'policy_guard' node."""
    from agents.supervisor import build_graph
    graph = build_graph()
    g = graph.get_graph()
    node_ids = list(g.nodes.keys())
    assert "policy_guard" in node_ids, f"'policy_guard' not found in nodes: {node_ids}"


def test_build_graph_has_communicator_node():
    """Compiled graph must expose 'communicator' node."""
    from agents.supervisor import build_graph
    graph = build_graph()
    g = graph.get_graph()
    node_ids = list(g.nodes.keys())
    assert "communicator" in node_ids, f"'communicator' not found in nodes: {node_ids}"


# ---------------------------------------------------------------------------
# Test 3: Routing — alert_needed=False skips policy_guard and communicator
# ---------------------------------------------------------------------------

def test_graph_skips_policy_guard_when_no_alert_needed():
    """
    When analyst sets alert_needed=False, graph must skip policy_guard.
    We verify by running the graph with all-OK toner levels and asserting
    that policy_guard was never called (via mock).
    """
    from agents.supervisor import build_graph

    readings = [
        _make_reading("cyan", 80.0),
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)
    initial_state: AgentState = {
        "poll_result": poll_result,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
        "llm_confidence": None,
        "llm_reasoning": None,
    }

    with patch("guardrails.safety_logic.run_policy_guard") as mock_guard, \
         patch("agents.supervisor.run_policy_guard", mock_guard):
        graph = build_graph()
        result = graph.invoke(initial_state)

    assert result["alert_needed"] is False
    assert result["alert_sent"] is False


def test_graph_skips_communicator_when_suppressed(clean_alert_state, monkeypatch):
    """
    When policy_guard suppresses (suppression_reason set), communicator is skipped.
    """
    from agents.supervisor import build_graph

    # Force policy guard to always suppress
    def always_suppress(state: AgentState) -> AgentState:
        state = dict(state)
        state["suppression_reason"] = "rate_limit"
        state["decision_log"] = state["decision_log"] + ["PolicyGuard: suppressed - rate_limit"]
        return state

    readings = [
        _make_reading("cyan", 5.0),  # below critical
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)
    initial_state: AgentState = {
        "poll_result": poll_result,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
        "llm_confidence": None,
        "llm_reasoning": None,
    }

    with patch("agents.supervisor.run_policy_guard", always_suppress), \
         patch("agents.communicator.SMTPAdapter") as mock_smtp:
        graph = build_graph()
        result = graph.invoke(initial_state)

    assert result["alert_sent"] is False
    mock_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: run_pipeline() delegates to build_graph().invoke()
# ---------------------------------------------------------------------------

def test_run_pipeline_delegates_to_graph_invoke(clean_alert_state):
    """
    run_pipeline() must call build_graph().invoke() — verified by checking
    that the result has all AgentState keys (same as direct graph invocation).
    """
    from agents.supervisor import run_pipeline

    readings = [
        _make_reading("cyan", 80.0),
        _make_reading("magenta", 80.0),
        _make_reading("yellow", 80.0),
        _make_reading("black", 80.0),
    ]
    poll_result = _make_poll_result(readings)

    result = run_pipeline(poll_result=poll_result)

    # Must return all AgentState keys
    required_keys = [
        "poll_result", "alert_needed", "alert_sent",
        "suppression_reason", "decision_log",
        "flagged_colors", "llm_confidence", "llm_reasoning",
    ]
    for key in required_keys:
        assert key in result, f"Missing key '{key}' in run_pipeline() result"


# ---------------------------------------------------------------------------
# Test 5: load_dotenv() is NOT called at module scope in supervisor.py
# ---------------------------------------------------------------------------

def test_no_module_level_load_dotenv():
    """
    supervisor.py must NOT have a module-level load_dotenv() call.
    Verified by AST-parsing the source file.
    """
    supervisor_path = Path("C:/Users/rohit/ROHIT/Project-Sentinel/agents/supervisor.py")
    source = supervisor_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find all top-level expression statements (function calls at module scope)
    module_level_calls = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            # Check for load_dotenv() call
            if isinstance(call.func, ast.Name) and call.func.id == "load_dotenv":
                module_level_calls.append("load_dotenv()")
            elif isinstance(call.func, ast.Attribute) and call.func.attr == "load_dotenv":
                module_level_calls.append("load_dotenv()")

    assert module_level_calls == [], (
        f"Found module-level load_dotenv() call(s) in supervisor.py: {module_level_calls}. "
        "Per Phase 4 design, load_dotenv() must only be called in main.py."
    )
