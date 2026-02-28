# Architecture Research

**Domain:** LangGraph multi-agent printer monitoring system
**Researched:** 2026-02-28
**Confidence:** HIGH

## System Overview

```
                        SNMP Network
                            |
                            v
┌──────────────────────────────────────────────────────────────────────┐
│                     Adapter Layer (Pure Python)                       │
│  ┌──────────────────┐                    ┌──────────────────┐        │
│  │  snmp_adapter.py  │                    │  ews_scraper.py  │        │
│  │  (pysnmp/pysnmplib)│                    │  (exchangelib)   │        │
│  └────────┬─────────┘                    └────────▲─────────┘        │
│           │ normalized data                       │ send email       │
├───────────┼───────────────────────────────────────┼──────────────────┤
│           │        LangGraph StateGraph Pipeline  │                  │
│           v                                       │                  │
│  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐      │
│  │  monitor_node  │───>│  analyst_node  │───>│ policy_guard   │      │
│  │  (pure Python) │    │  (LLM call)    │    │ (pure Python)  │      │
│  └────────────────┘    └────────────────┘    └───────┬────────┘      │
│                                                      │               │
│                                              ┌───────▼────────┐      │
│                                              │communicator_node│      │
│                                              │ (pure Python)   │      │
│                                              └────────────────┘      │
├──────────────────────────────────────────────────────────────────────┤
│                        Persistence Layer                             │
│  ┌──────────────────┐  ┌──────────────────┐                          │
│  │printer_history   │  │  .env config     │                          │
│  │   .json          │  │  (python-dotenv) │                          │
│  └──────────────────┘  └──────────────────┘                          │
├──────────────────────────────────────────────────────────────────────┤
│                        Scheduler (main.py)                           │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  APScheduler or schedule — hourly cron invoking graph.invoke │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### Why This Shape

Project Sentinel is a **linear pipeline**, not a hub-and-spoke supervisor. The data flow is deterministic: SNMP data in, analysis, gate check, alert out. There is no need for a supervisor to dynamically route between agents because the processing order is fixed. LangGraph's `StateGraph` with simple edges and one conditional edge (at the policy guard) is the correct structure. Do not overcomplicate this with the full supervisor/orchestrator-worker pattern.

## Component Responsibilities

| Component | Responsibility | Communicates With | LangGraph Role |
|-----------|---------------|-------------------|----------------|
| `snmp_adapter.py` | Pull toner %, supply capacity, device status from Lexmark XC2235 via SNMP | Called by `monitor_node` | External (not a node) |
| `ews_scraper.py` | Send formatted alert emails via Exchange Web Services | Called by `communicator_node` | External (not a node) |
| `monitor_node` | Poll SNMP adapter, validate data freshness/plausibility, append to trend history, prepare state for analyst | `snmp_adapter` (calls), `analyst_node` (edge) | Graph Node |
| `analyst_node` | LLM-powered analysis: threshold check, time-to-depletion estimate, confidence score | Reads state from `monitor_node`, writes analysis to state | Graph Node |
| `policy_guard` | Rate limiting (1/day/printer), confidence threshold check, data quality gate | Reads analyst output from state, sets `alert_approved` flag | Graph Node |
| `communicator_node` | Format and send alert email if approved; log suppression if not | `ews_scraper` (calls), reads `alert_approved` from state | Graph Node |
| `main.py` | Scheduler entry point, loads config, compiles graph, runs on interval | Invokes compiled graph | Orchestrator |

### Key Boundary: Adapters Are NOT Graph Nodes

Adapters (`snmp_adapter.py`, `ews_scraper.py`) are plain Python modules imported and called by graph nodes. They do not participate in the LangGraph state flow. This keeps them testable independently and replaceable without touching graph wiring.

## LangGraph State Schema

Use `TypedDict` with `Annotated` reducers. This is the shared state that flows through every node.

```python
from typing import Annotated, Optional
from typing_extensions import TypedDict
from operator import add
import datetime

class PrinterReading(TypedDict):
    """Single SNMP reading from the printer."""
    timestamp: str
    toner_black_pct: float
    toner_cyan_pct: float
    toner_magenta_pct: float
    toner_yellow_pct: float
    device_status: str

class AnalystOutput(TypedDict):
    """LLM analyst results."""
    alert_needed: bool
    time_to_depletion_days: Optional[float]
    confidence_score: float
    reasoning: str
    recommended_action: str

class SentinelState(TypedDict):
    """Root state for the LangGraph pipeline."""
    # Monitor node writes
    printer_id: str
    current_reading: Optional[PrinterReading]
    trend_history: list[PrinterReading]       # append-only via reducer
    data_quality_ok: bool

    # Analyst node writes
    analysis: Optional[AnalystOutput]

    # Policy guard writes
    alert_approved: bool
    suppression_reason: Optional[str]

    # Communicator node writes
    alert_sent: bool
    log_entries: Annotated[list[str], add]    # accumulates across nodes
```

### State Design Rationale

- **Flat structure**: No nesting beyond the typed sub-dicts. Every node reads/writes top-level keys. This follows LangGraph best practice of keeping state minimal and explicit.
- **`log_entries` uses `add` reducer**: Every node can append log messages and they accumulate rather than overwrite. All other fields use default overwrite semantics because only one node writes each field.
- **`trend_history` managed externally**: The monitor node loads trend history from `printer_history.json`, appends the current reading, and writes the full list to state. It does not use a reducer because the monitor node owns this field exclusively.
- **`alert_approved` as a boolean gate**: The policy guard sets this. The communicator checks it. Simple and auditable.

## Graph Wiring

```python
from langgraph.graph import StateGraph, START, END

def build_sentinel_graph():
    graph = StateGraph(SentinelState)

    # Add nodes
    graph.add_node("monitor", monitor_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("policy_guard", policy_guard_node)
    graph.add_node("communicator", communicator_node)

    # Linear pipeline edges
    graph.add_edge(START, "monitor")
    graph.add_edge("monitor", "analyst")
    graph.add_edge("analyst", "policy_guard")

    # Conditional edge: only proceed to communicator if data is valid
    # If data_quality_ok is False, skip straight to END (log and exit)
    graph.add_conditional_edges(
        "policy_guard",
        route_after_policy,
        {"send_alert": "communicator", "suppress": END}
    )
    graph.add_edge("communicator", END)

    return graph.compile()


def route_after_policy(state: SentinelState) -> str:
    """Route based on policy guard decision."""
    if state.get("alert_approved", False):
        return "send_alert"
    return "suppress"
```

### Why One Conditional Edge, Not More

The only real decision point is after the policy guard: send or suppress. The monitor-to-analyst flow is always sequential (you always analyze fresh data). Adding conditional edges at the monitor node (e.g., "skip if data is stale") is tempting but wrong -- let the monitor node write `data_quality_ok = False` to state and let the policy guard handle it. One decision point, one place to debug.

## Data Flow

### Primary Pipeline (Happy Path)

```
Scheduler (main.py)
    |
    | graph.invoke({"printer_id": "lexmark-xc2235"})
    v
[monitor_node]
    | 1. Calls snmp_adapter.poll(printer_id)
    | 2. Validates reading (not null, in range, fresh)
    | 3. Loads trend_history from printer_history.json
    | 4. Appends current reading to trend_history
    | 5. Sets data_quality_ok = True/False
    | 6. Returns state update: {current_reading, trend_history, data_quality_ok}
    v
[analyst_node]
    | 1. Reads current_reading and trend_history from state
    | 2. Formats prompt with toner levels and historical trend
    | 3. Calls LLM (e.g., GPT-4o-mini or Claude) for analysis
    | 4. Parses structured output: alert_needed, time_to_depletion, confidence
    | 5. Returns state update: {analysis: AnalystOutput}
    v
[policy_guard_node]
    | 1. Checks analysis.confidence_score >= threshold (env var)
    | 2. Checks data_quality_ok == True
    | 3. Checks rate limit: was alert sent for this printer in last 24h?
    |    (reads printer_history.json for last alert timestamp)
    | 4. Sets alert_approved = True only if ALL checks pass
    | 5. Sets suppression_reason if any check fails
    | 6. Logs decision to log_entries
    v
[route_after_policy] ──── suppress ──> END (log suppression)
    |
    | send_alert
    v
[communicator_node]
    | 1. Formats alert email body (toner %, depletion estimate,
    |    confidence score, recommended action)
    | 2. Calls ews_scraper.send_alert(recipient, subject, body)
    | 3. Records alert timestamp to printer_history.json
    | 4. Sets alert_sent = True
    | 5. Logs to log_entries
    v
END
```

### Suppressed Alert Flow

When the policy guard rejects an alert (low confidence, rate limited, or bad data quality), the graph routes directly to END. The suppression reason and all log entries are still captured in the final state returned by `graph.invoke()`. The scheduler in `main.py` should persist these log entries to `printer_history.json` after invocation completes.

## Recommended Project Structure

```
Project-Sentinel/
├── main.py                        # Entry point: scheduler + graph invocation
├── graph.py                       # build_sentinel_graph() — graph definition
├── state.py                       # SentinelState TypedDict + sub-types
├── agents/
│   ├── __init__.py
│   ├── monitor.py                 # monitor_node function
│   ├── analyst.py                 # analyst_node function (LLM call)
│   └── communicator.py            # communicator_node function
├── guardrails/
│   ├── __init__.py
│   └── policy_guard.py            # policy_guard_node function
├── adapters/
│   ├── __init__.py
│   ├── snmp_adapter.py            # SNMP polling logic (pysnmp)
│   └── ews_adapter.py             # EWS email sending (exchangelib)
├── logs/
│   └── printer_history.json       # Persistent decision/action log
├── .env                           # Credentials and config (never committed)
├── requirements.txt               # Python dependencies
└── tests/
    ├── test_snmp_adapter.py       # Mock SNMP responses
    ├── test_ews_adapter.py        # Mock EWS calls
    ├── test_monitor.py            # Unit test monitor node
    ├── test_analyst.py            # Mock LLM, test prompt + parsing
    ├── test_policy_guard.py       # Test rate limit + threshold logic
    ├── test_communicator.py       # Test email formatting
    └── test_graph_integration.py  # End-to-end with all mocks
```

### Structure Rationale

- **`graph.py` separate from `main.py`**: The graph definition is importable for testing. `main.py` handles scheduling and config only.
- **`state.py` at root**: Every module imports state types. Keeping it at root avoids circular imports.
- **Adapters renamed**: `ews_scraper.py` becomes `ews_adapter.py` for consistency. The existing scaffold names can be preserved if preferred, but the adapter naming convention is cleaner.
- **`agents/supervisor.py` eliminated**: In a linear pipeline there is no supervisor agent. The graph wiring in `graph.py` replaces it. The supervisor concept was inherited from generic multi-agent patterns but adds no value when the flow is deterministic.

**Note on existing scaffold**: The project has `agents/supervisor.py` in its scaffold. This file should become either `graph.py` (the StateGraph definition) or be repurposed as the monitor node. Do not implement a separate supervisor agent -- it would be an empty pass-through.

## Architectural Patterns

### Pattern 1: Node as Pure Function

**What:** Each graph node is a plain Python function that takes `SentinelState`, does work, and returns a partial state dict. No classes, no inheritance.

**When to use:** Always in LangGraph. This is the idiomatic pattern.

**Trade-offs:** Simple and testable. Less encapsulation than class-based agents, but LangGraph does not benefit from OOP agent patterns.

```python
def monitor_node(state: SentinelState) -> dict:
    """Poll SNMP and validate data."""
    adapter = SNMPAdapter(host=os.getenv("SNMP_HOST"),
                          community=os.getenv("SNMP_COMMUNITY"))
    reading = adapter.poll()

    # Validate
    data_quality_ok = (
        reading is not None
        and 0 <= reading["toner_black_pct"] <= 100
        and reading["device_status"] != "offline"
    )

    # Load and append trend
    history = load_trend_history(state["printer_id"])
    if reading:
        history.append(reading)

    return {
        "current_reading": reading,
        "trend_history": history,
        "data_quality_ok": data_quality_ok,
        "log_entries": [f"Monitor polled: quality={'OK' if data_quality_ok else 'FAIL'}"]
    }
```

### Pattern 2: Adapter Isolation

**What:** External system interactions (SNMP, EWS) are encapsulated in adapter modules that return normalized Python dicts. Graph nodes call adapters but never contain protocol-level code.

**When to use:** Always. This is the project's core design principle.

**Trade-offs:** Adds a layer of indirection but makes testing straightforward (mock the adapter, not the protocol).

```python
# adapters/snmp_adapter.py
class SNMPAdapter:
    def __init__(self, host: str, community: str):
        self.host = host
        self.community = community

    def poll(self) -> Optional[PrinterReading]:
        """Poll printer, return normalized dict or None on failure."""
        # pysnmp implementation here
        # Returns PrinterReading TypedDict, never raw SNMP objects
        ...
```

### Pattern 3: Structured LLM Output

**What:** The analyst node uses structured output parsing (e.g., Pydantic model or JSON schema) to guarantee the LLM returns `alert_needed`, `confidence_score`, `time_to_depletion_days`, etc. Never parse free-text LLM responses with regex.

**When to use:** Always when an LLM output feeds into programmatic decision-making.

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

class AnalysisResult(BaseModel):
    alert_needed: bool = Field(description="Whether toner levels require an alert")
    time_to_depletion_days: float = Field(description="Estimated days until depletion")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Self-assessed confidence")
    reasoning: str = Field(description="Brief explanation of the analysis")
    recommended_action: str = Field(description="What the recipient should do")

def analyst_node(state: SentinelState) -> dict:
    parser = PydanticOutputParser(pydantic_object=AnalysisResult)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a printer supply analyst..."),
        ("human", "Current toner levels: {reading}\nTrend: {trend}\n{format_instructions}")
    ])
    chain = prompt | llm | parser
    result = chain.invoke({
        "reading": state["current_reading"],
        "trend": state["trend_history"][-10:],  # Last 10 readings
        "format_instructions": parser.get_format_instructions()
    })
    return {
        "analysis": result.model_dump(),
        "log_entries": [f"Analyst: alert={result.alert_needed}, conf={result.confidence_score}"]
    }
```

### Pattern 4: Policy Guard as Graph Node (Not Middleware)

**What:** The policy guard is a regular graph node that reads state and writes `alert_approved` + `suppression_reason`. It is NOT middleware, NOT a decorator, and NOT a wrapper around the communicator. It is a first-class node with a conditional edge after it.

**Why this matters:** Making the policy guard a node means its decision is visible in the state, loggable, and testable. If it were middleware wrapping the communicator, you could not inspect why an alert was suppressed without looking inside the communicator.

```python
def policy_guard_node(state: SentinelState) -> dict:
    analysis = state.get("analysis")
    reasons = []

    # Check 1: Data quality
    if not state.get("data_quality_ok", False):
        reasons.append("Data quality check failed")

    # Check 2: Confidence threshold
    threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))
    if analysis and analysis["confidence_score"] < threshold:
        reasons.append(f"Confidence {analysis['confidence_score']} < {threshold}")

    # Check 3: Rate limit
    if was_alert_sent_today(state["printer_id"]):
        reasons.append("Rate limit: alert already sent in last 24h")

    # Check 4: Alert actually needed
    if analysis and not analysis["alert_needed"]:
        reasons.append("Analyst determined no alert needed")

    approved = len(reasons) == 0
    return {
        "alert_approved": approved,
        "suppression_reason": "; ".join(reasons) if reasons else None,
        "log_entries": [f"PolicyGuard: approved={approved}" +
                       (f" reasons=[{'; '.join(reasons)}]" if reasons else "")]
    }
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Supervisor Agent for a Linear Pipeline

**What people do:** Implement a supervisor node that dynamically routes between analyst, monitor, and communicator based on LLM-driven decisions (the hub-and-spoke pattern).

**Why it is wrong for this project:** The data flow is deterministic: poll -> analyze -> gate -> alert. There is no branching decision about *which* agent to call. A supervisor adds latency (extra LLM call to decide routing), complexity (conditional edges from supervisor to every node), and a failure mode (supervisor routes incorrectly).

**Do this instead:** Use simple `add_edge` calls for the linear pipeline and one `add_conditional_edges` at the policy guard.

### Anti-Pattern 2: Storing Adapter Instances in Graph State

**What people do:** Put the SNMP connection object or EWS client into `SentinelState` so nodes can share it.

**Why it is wrong:** LangGraph state must be serializable (for checkpointing, debugging, LangSmith tracing). Connection objects are not serializable. It also couples the graph to specific adapter implementations.

**Do this instead:** Instantiate adapters inside nodes using config from environment variables. Each node creates its own adapter instance.

### Anti-Pattern 3: Using LLM for the Policy Guard

**What people do:** Have the LLM decide whether to send the alert (putting guardrails logic in the LLM prompt).

**Why it is wrong:** Rate limiting and confidence thresholds are deterministic rules. An LLM can hallucinate past them. The whole point of a policy guard is that it cannot be talked into bypassing rules.

**Do this instead:** Pure Python logic for all guard checks. No LLM involved in the policy guard node.

### Anti-Pattern 4: Accumulating Unbounded State

**What people do:** Append every SNMP reading to `trend_history` in state without bounds, leading to state objects that grow indefinitely.

**Why it is wrong:** State is passed to every node and potentially serialized. Large state objects slow everything down and can cause memory issues over time.

**Do this instead:** Cap `trend_history` to the last N readings (e.g., 30 days of hourly polls = 720 entries). Store full history in `printer_history.json`, but only load a window into state.

## Scaling Considerations

| Concern | 1 Printer (v1) | 10 Printers | 100+ Printers |
|---------|----------------|-------------|---------------|
| SNMP polling | Sequential in monitor node | Sequential is fine (SNMP is fast) | Async polling with asyncio or thread pool |
| Graph invocation | Single `graph.invoke()` | Loop over printers, one invocation each | Parallel invocations or LangGraph `Send` API |
| Rate limiting | Simple file check | Per-printer check in JSON | Move to SQLite or Redis for concurrent access |
| Alert emails | Single EWS call | Batch or sequential EWS calls | Connection pooling, consider SMTP fallback |
| Trend storage | JSON file | JSON file (still fine) | SQLite or PostgreSQL |
| LLM calls | 1 per poll cycle | 10 per cycle (cost: low) | Batch prompts or use cheaper model |

### Scaling Priority

1. **First bottleneck (10+ printers):** JSON file for rate limiting becomes a concurrency risk. Move to SQLite.
2. **Second bottleneck (50+ printers):** Sequential SNMP polling becomes slow. Add async polling.
3. **Third bottleneck (100+ printers):** LLM cost and latency. Use batch prompts or a cheaper/faster model for routine checks, reserving the full model for edge cases.

## Integration Points

### External Services

| Service | Integration Pattern | Gotchas |
|---------|---------------------|---------|
| Lexmark XC2235 (SNMP) | `pysnmp` / `pysnmplib` GET requests for OIDs | Community string auth only; OIDs are vendor-specific (need Lexmark MIB or manual OID lookup); SNMP v2c is typical for printers |
| Microsoft Exchange (EWS) | `exchangelib` with service account credentials | EWS is deprecated by Microsoft in favor of Graph API, but still works for on-prem Exchange; autodiscover can be flaky, prefer explicit server URL |
| LLM Provider | `langchain-openai` or `langchain-anthropic` via LangChain | API key in `.env`; structured output parsing can fail if model does not follow schema; add retry logic |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Adapter <-> Node | Direct function call (import and invoke) | Adapters return typed dicts, never raw protocol objects |
| Node <-> Node | LangGraph state (TypedDict) | Nodes never import or call each other directly |
| Node <-> Persistence | Direct file I/O to `printer_history.json` | Consider a small persistence module to avoid duplicating JSON read/write logic across nodes |
| Scheduler <-> Graph | `graph.invoke()` call in main.py | Scheduler passes initial state `{"printer_id": "..."}`, receives final state with all log entries |

## Build Order (Dependency-Driven)

This is the recommended implementation sequence based on what depends on what:

```
Phase 1: Foundation (no dependencies)
    ├── state.py          (TypedDict definitions — everything imports this)
    ├── snmp_adapter.py   (standalone, testable with mock SNMP)
    └── ews_adapter.py    (standalone, testable with mock EWS)

Phase 2: Guard + Monitor (depend on adapters + state)
    ├── policy_guard.py   (depends on state.py + printer_history.json)
    └── monitor.py        (depends on snmp_adapter + state.py)

Phase 3: LLM Agent (depends on state schema)
    └── analyst.py        (depends on state.py + LLM provider)

Phase 4: Communicator + Graph (depends on everything above)
    ├── communicator.py   (depends on ews_adapter + state.py)
    └── graph.py          (imports all nodes, wires StateGraph)

Phase 5: Orchestration
    └── main.py           (scheduler + graph.invoke)
```

**Why this order:**
- State types must exist before any node can be written or tested.
- Adapters have zero internal dependencies -- build and test them first against real hardware/services.
- Policy guard before communicator (project constraint: guardrails must exist before outbound actions are possible).
- Analyst can be developed in parallel with Phase 2 if state.py is done.
- Graph wiring is last because it imports all nodes.

## Sources

- [LangGraph GitHub repository (v1.0.10)](https://github.com/langchain-ai/langgraph) - HIGH confidence
- [LangGraph Graph API documentation](https://docs.langchain.com/oss/python/langgraph/graph-api) - HIGH confidence
- [LangGraph Workflows and Agents documentation](https://docs.langchain.com/oss/python/langgraph/workflows-agents) - HIGH confidence
- [LangGraph Supervisor pattern](https://github.com/langchain-ai/langgraph-supervisor-py) - HIGH confidence (reviewed to confirm it is NOT needed here)
- [LangGraph State Management best practices](https://medium.com/@bharatraj1918/langgraph-state-management-part-1-how-langgraph-manages-state-for-multi-agent-workflows-da64d352c43b) - MEDIUM confidence
- [LangGraph Best Practices (Swarnendu De)](https://www.swarnendu.de/blog/langgraph-best-practices/) - MEDIUM confidence

---
*Architecture research for: Project Sentinel (LangGraph multi-agent printer monitoring)*
*Researched: 2026-02-28*
