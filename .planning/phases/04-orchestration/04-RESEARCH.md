# Phase 4: Orchestration - Research

**Researched:** 2026-03-02
**Domain:** APScheduler 3.x interval scheduling + LangGraph StateGraph wiring
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Startup Behavior**
- Run an immediate first poll on startup, then schedule hourly after that (don't wait an hour blind)
- If the startup poll fails (SNMP unreachable, exception), log the error and continue — Sentinel stays up and proceeds to the scheduled loop
- Show a startup banner to console: includes Sentinel name, polling interval, and "first poll running now"
- Validate required env vars (SNMP_HOST, ALERT_RECIPIENT, etc.) at startup — fail fast with a clear message listing what's missing, before starting the scheduler
- On Ctrl+C or SIGTERM: catch cleanly, log "Sentinel stopped", exit without dumping a stack trace

**Polling Interval**
- Driven by `POLL_INTERVAL_MINUTES` env var (add to .env.example with documentation)
- Default: 60 minutes when env var is not set
- Invalid values (0, negative, non-numeric): fail fast at startup with a clear error message — consistent with env var validation above
- Show the active interval in the startup banner (e.g. "polling every 60 minutes")

**Scheduler (APScheduler)**
- Use APScheduler with an **interval trigger** (every N minutes from process start — not cron-style fixed clock times)
- In-memory job store — no SQLite or persistent state; the immediate startup poll covers any gap from restarts
- Non-blocking mode: `scheduler.start()` runs in a background thread; main thread sits in a `try/except KeyboardInterrupt` loop waiting for shutdown
- LangGraph StateGraph is **compiled once at startup** (`graph = workflow.compile()`) and reused each cycle — fresh `AgentState` dict is created per invocation via `graph.invoke(initial_state)`

**LangGraph Wiring (supervisor.py)**
- Replace the current plain sequential function with a `StateGraph` with one node per agent stage
- Conditional edges: route past policy guard if `alert_needed=False`, skip communicator if `suppression_reason` is set — mirrors existing conditional logic in the sequential function
- `supervisor.py` exposes `build_graph()` returning a compiled graph; `main.py` calls it at startup

**Error Resilience**
- Error boundary lives in `main.py`'s scheduled job wrapper — `run_pipeline()` and the graph remain clean
- On exception: log full traceback via `logger.exception()` at ERROR level; also append `event_type=pipeline_error` record to the JSONL audit log (consistent with `llm_failure` events)
- No escalation for consecutive failures in v1 — log each one and keep running

### Claude's Discretion
- APScheduler executor type (ThreadPoolExecutor vs ProcessPoolExecutor — threading is fine for I/O-bound polling)
- Exact startup banner format beyond the required content (interval, printer host, first poll notice)
- Logging configuration in main.py (format string, log level default)
- Whether `build_graph()` or equivalent lives in `supervisor.py` or a separate `graph.py`

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCHD-01 | System runs autonomously on an hourly polling schedule via APScheduler 3.x, requiring no manual trigger after startup | APScheduler 3.11.2 BackgroundScheduler + IntervalTrigger with `next_run_time=datetime.now()` enables immediate startup poll then hourly repeats; LangGraph StateGraph compiled once, invoked per cycle |
</phase_requirements>

---

## Summary

Phase 4 wires the three existing agent functions (`run_analyst`, `run_policy_guard`, `run_communicator`) into a LangGraph `StateGraph`, then schedules autonomous execution via APScheduler 3.x. No new agent logic is introduced. The two core technologies are: (1) APScheduler `BackgroundScheduler` with an `IntervalTrigger`, and (2) LangGraph `StateGraph` with conditional edges.

The critical scheduling pattern is `next_run_time=datetime.now()` on the `add_job()` call. This is the only reliable way to make APScheduler fire a job immediately on startup rather than waiting the full interval. Without this, the system would wait 60 minutes before the first poll — violating the locked startup decision.

The LangGraph StateGraph compiled graph is fully thread-safe and stateless between invocations. Compiling once at startup and calling `graph.invoke(fresh_state)` per cycle is the correct pattern — no per-invocation state leaks between polling cycles. `main.py` is built from scratch as the entry point; `supervisor.py` gets refactored to expose `build_graph()` returning a compiled graph.

**Primary recommendation:** Build `main.py` around `BackgroundScheduler` + `IntervalTrigger` with `next_run_time=datetime.now()`. Keep `run_pipeline()` as the graph invocation wrapper in the scheduler job function. Compile the LangGraph graph once at startup in `main.py` before the scheduler starts.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| apscheduler | 3.11.2 (latest stable 3.x) | Interval-based background scheduling | Locked decision; 3.x is stable production release; 4.x is still alpha |
| langgraph | >=0.2.0 (already in requirements.txt) | StateGraph wiring of agent nodes | Already declared; all agent functions already typed as `(AgentState) -> AgentState` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | >=1.0.0 (already installed) | `load_dotenv()` in main.py entry point | Call once at top of `main.py` before any env var reads |
| signal (stdlib) | stdlib | SIGTERM graceful shutdown | Register `signal.SIGTERM` handler alongside KeyboardInterrupt catch |
| logging (stdlib) | stdlib | Startup banner, error logging | Configure in `main.py` before any other module init |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| BackgroundScheduler | BlockingScheduler | BlockingScheduler blocks main thread from `start()` — makes signal handling harder; Background is correct for this pattern |
| IntervalTrigger | CronTrigger | Cron aligns to fixed clock times (e.g., :00 of every hour); Interval counts from process start — locked decision requires interval |
| ThreadPoolExecutor (default) | ProcessPoolExecutor | Process pool has high overhead for I/O-bound tasks; threading is correct for SNMP + HTTP calls |

**Installation:**
```bash
pip install "apscheduler>=3.10.0"
```

---

## Architecture Patterns

### Recommended Project Structure

```
Project-Sentinel/
├── main.py                    # Entry point: startup banner, env validation, scheduler loop
├── agents/
│   └── supervisor.py          # build_graph() -> compiled StateGraph; (run_pipeline removed or delegated)
├── requirements.txt           # Add apscheduler>=3.10.0
└── .env.example               # Add POLL_INTERVAL_MINUTES with documentation comment
```

### Pattern 1: Immediate-Startup Interval Job (APScheduler)

**What:** Add a single job with both an `IntervalTrigger` (for repeats) AND `next_run_time=datetime.now()` (for the immediate first run). This is more reliable than adding two separate jobs.

**When to use:** Any time you need "run now, then repeat every N minutes."

**Example:**
```python
# Source: https://jdhao.github.io/2024/11/02/python_apascheduler_start_job_immediately/
# Source: https://apscheduler.readthedocs.io/en/3.x/userguide.html

from datetime import datetime
import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

def run_pipeline_job():
    """Scheduled job wrapper — error boundary lives here."""
    try:
        graph.invoke(build_initial_state())
    except Exception:
        logger.exception("Pipeline error — continuing scheduler")
        append_pipeline_error_to_log()

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=run_pipeline_job,
    trigger=IntervalTrigger(minutes=poll_interval_minutes),
    next_run_time=datetime.now(),   # fires immediately on scheduler.start()
    id="sentinel_poll",
    name="Sentinel toner poll",
)
scheduler.start()

# Graceful SIGTERM handler
def _on_sigterm(signum, frame):
    logger.info("Sentinel stopped (SIGTERM)")
    scheduler.shutdown(wait=False)
    sys.exit(0)

signal.signal(signal.SIGTERM, _on_sigterm)

# Main thread blocks here; Ctrl+C triggers the except
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Sentinel stopped")
    scheduler.shutdown()
```

### Pattern 2: LangGraph StateGraph Build Function

**What:** `supervisor.py` exposes `build_graph()` which constructs, wires, and compiles a `StateGraph`. `main.py` calls it once at startup. Each poll cycle calls `graph.invoke(fresh_state_dict)`.

**When to use:** Stateless polling — no memory between cycles required. No checkpointer needed.

**Example:**
```python
# Source: https://docs.langchain.com/oss/python/langgraph/graph-api
# Source: https://github.com/langchain-ai/langgraph/discussions/1211 (thread safety confirmation)

from langgraph.graph import StateGraph, START, END
from state_types import AgentState
from agents.analyst import run_analyst
from agents.communicator import run_communicator
from guardrails.safety_logic import run_policy_guard


def _route_after_analyst(state: AgentState) -> str:
    """Conditional edge: skip policy guard if no alert needed."""
    return "policy_guard" if state["alert_needed"] else END


def _route_after_policy_guard(state: AgentState) -> str:
    """Conditional edge: skip communicator if suppressed."""
    return "communicator" if state["suppression_reason"] is None else END


def build_graph():
    """Build and compile the Sentinel monitoring StateGraph. Call once at startup."""
    workflow = StateGraph(AgentState)

    workflow.add_node("analyst", run_analyst)
    workflow.add_node("policy_guard", run_policy_guard)
    workflow.add_node("communicator", run_communicator)

    workflow.add_edge(START, "analyst")
    workflow.add_conditional_edges("analyst", _route_after_analyst)
    workflow.add_conditional_edges("policy_guard", _route_after_policy_guard)
    workflow.add_edge("communicator", END)

    return workflow.compile()
```

### Pattern 3: main.py Entry Point Structure

**What:** `main.py` is the single entry point. It validates env vars, loads the graph, prints the banner, then hands off to the scheduler.

**Example:**
```python
# main.py skeleton

import logging
import os
import signal
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  # Must be first — before any os.getenv() calls

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from adapters.persistence import append_poll_result
from agents.supervisor import build_graph
from state_types import AgentState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("sentinel.main")


REQUIRED_ENV_VARS = ["SNMP_HOST", "ALERT_RECIPIENT"]

def _validate_env() -> int:
    """Validate required env vars. Print missing ones. Return poll interval minutes."""
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    raw = os.getenv("POLL_INTERVAL_MINUTES", "60")
    try:
        minutes = int(raw)
        if minutes <= 0:
            raise ValueError("must be positive")
    except ValueError:
        print(f"ERROR: POLL_INTERVAL_MINUTES={raw!r} is invalid — must be a positive integer")
        sys.exit(1)
    return minutes


def _build_initial_state() -> AgentState:
    return {
        "poll_result": None,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
        "llm_confidence": None,
        "llm_reasoning": None,
    }


def main():
    poll_interval = _validate_env()
    graph = build_graph()

    host = os.getenv("SNMP_HOST", "unknown")
    print(f"=== Project Sentinel ===")
    print(f"  Printer:  {host}")
    print(f"  Interval: every {poll_interval} minutes")
    print(f"  Status:   first poll running now")

    def run_job():
        try:
            graph.invoke(_build_initial_state())
        except Exception:
            logger.exception("Pipeline error in scheduled job — Sentinel continues")
            # append pipeline_error event to JSONL log here

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=run_job,
        trigger=IntervalTrigger(minutes=poll_interval),
        next_run_time=datetime.now(),
        id="sentinel_poll",
        name="Sentinel toner poll",
    )

    def _on_sigterm(signum, frame):
        logger.info("Sentinel stopped (SIGTERM)")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Sentinel stopped")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
```

### Anti-Patterns to Avoid

- **Calling `load_dotenv()` in `supervisor.py` when `main.py` exists:** The current `supervisor.py` calls `load_dotenv()` at module import. Phase 4 moves this to `main.py` top-level — `supervisor.py`'s call should be removed or guarded so it only fires when running the module directly.
- **Compiling the graph inside `run_job()`:** Compilation validates the graph structure and is a one-time cost. Compiling inside the scheduled job creates unnecessary overhead and repeated validation per poll cycle.
- **Using `BlockingScheduler` when signal handling is needed:** `BlockingScheduler.start()` blocks the main thread immediately, making it difficult to register signal handlers before the scheduler takes over. `BackgroundScheduler` + explicit `while True` loop is cleaner.
- **Using `start_date=datetime.now()` on IntervalTrigger instead of `next_run_time`:** `start_date` sets the reference point for interval calculation but does not guarantee immediate execution. `next_run_time=datetime.now()` in `add_job()` is the correct approach (verified by APScheduler maintainer blog post).
- **Storing state on the compiled graph:** The `CompiledStateGraph` object is stateless — graph execution state lives in the dict passed to `invoke()`. Never attach polling counters or mutable state to the graph object.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Periodic job execution | `threading.Timer` recursive chain or `while True: time.sleep()` poll loop | `apscheduler.BackgroundScheduler` + `IntervalTrigger` | Timer chains miss drift correction; APScheduler handles missed jobs, jitter, thread pool management |
| Agent routing logic | Custom `if/else` chain calling functions | `StateGraph` + `add_conditional_edges` | LangGraph handles state merging (Annotated list reducers), provides execution tracing, and is already declared as a dependency |
| Job error recovery | Try/except in every agent function | Single try/except in the `run_job()` wrapper in `main.py` | Agents stay clean; error boundary is explicit and in one place per CONTEXT.md decision |

**Key insight:** APScheduler 3.x default configuration already includes a `MemoryJobStore` and `ThreadPoolExecutor(10)` — no explicit configuration of either is needed for this use case. Just instantiate `BackgroundScheduler()` with no arguments.

---

## Common Pitfalls

### Pitfall 1: First Poll Waits a Full Hour
**What goes wrong:** Using `scheduler.add_job(func, 'interval', minutes=60)` with no `next_run_time` — the first execution happens 60 minutes after `scheduler.start()`.
**Why it happens:** Interval trigger's first run time defaults to `now + interval`.
**How to avoid:** Always pass `next_run_time=datetime.now()` in `add_job()`. This overrides the default first-run calculation.
**Warning signs:** "first poll running now" in startup banner but no pipeline log entry appears for 60 minutes.

### Pitfall 2: `load_dotenv()` Called Too Late
**What goes wrong:** Agent modules that call `os.getenv()` at import time (or at module level) miss env vars because `load_dotenv()` hasn't been called yet.
**Why it happens:** Python evaluates module-level code at import. If `import agents.supervisor` happens before `load_dotenv()`, env vars aren't set yet.
**How to avoid:** Call `load_dotenv()` as the very first statement in `main.py`, before any project module imports.
**Warning signs:** `SNMP_HOST` reads as `None` even though `.env` contains a value.

### Pitfall 3: Graph State Leaking Between Cycles
**What goes wrong:** Alert state or `decision_log` entries from one poll cycle bleed into the next.
**Why it happens:** Passing the same mutable `AgentState` dict across invocations rather than creating a fresh dict per call.
**How to avoid:** `_build_initial_state()` creates a new dict literal every time `run_job()` calls it. Never reuse the dict returned by `graph.invoke()` as input to the next invocation.
**Warning signs:** `decision_log` grows indefinitely across polling cycles; `alert_sent=True` persists into cycles where no alert should fire.

### Pitfall 4: SIGTERM Not Handled on Windows
**What goes wrong:** `signal.SIGTERM` is raised by process managers (Docker, systemd) to request graceful shutdown. Without a handler, Python on Windows exits immediately without calling `scheduler.shutdown()`.
**Why it happens:** Windows supports `SIGTERM` via `signal.signal()` but does not raise it on Ctrl+C (that's `SIGINT`/`KeyboardInterrupt`). The two signals must be handled separately.
**How to avoid:** Register both: `signal.signal(signal.SIGTERM, _on_sigterm)` and catch `KeyboardInterrupt` in the `while True` loop.
**Warning signs:** Running jobs are cut off mid-execution when the process receives a stop signal.

### Pitfall 5: `build_graph()` Location Confusion
**What goes wrong:** Importing `build_graph` from `supervisor.py` also triggers the module-level `load_dotenv()` call in the current `supervisor.py`, which may re-read `.env` after `main.py` has already set env vars.
**Why it happens:** Current `supervisor.py` has `load_dotenv()` at module scope (Phase 2 artifact).
**How to avoid:** Remove or guard the `load_dotenv()` call in `supervisor.py` when refactoring to expose `build_graph()`. Only `main.py` should call `load_dotenv()`.
**Warning signs:** `.env` values silently overwrite environment variables set before `python main.py` was invoked.

---

## Code Examples

Verified patterns from official sources:

### APScheduler: Immediate-start interval job
```python
# Source: https://apscheduler.readthedocs.io/en/3.x/userguide.html
# Source: https://jdhao.github.io/2024/11/02/python_apascheduler_start_job_immediately/

from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()  # uses MemoryJobStore + ThreadPoolExecutor(10) by default
scheduler.add_job(
    func=my_job_function,
    trigger=IntervalTrigger(minutes=60),
    next_run_time=datetime.now(),   # <-- fires immediately on scheduler.start()
    id="sentinel_poll",
)
scheduler.start()
```

### APScheduler: Graceful shutdown (both SIGTERM and KeyboardInterrupt)
```python
# Source: https://apscheduler.readthedocs.io/en/3.x/userguide.html

import signal
import sys
import time

def _on_sigterm(signum, frame):
    scheduler.shutdown(wait=False)
    sys.exit(0)

signal.signal(signal.SIGTERM, _on_sigterm)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    scheduler.shutdown()
```

### LangGraph: StateGraph with conditional routing to END
```python
# Source: https://docs.langchain.com/oss/python/langgraph/graph-api

from langgraph.graph import StateGraph, START, END
from state_types import AgentState

workflow = StateGraph(AgentState)

workflow.add_node("analyst", run_analyst)
workflow.add_node("policy_guard", run_policy_guard)
workflow.add_node("communicator", run_communicator)

workflow.add_edge(START, "analyst")

# Route: analyst -> policy_guard if alert needed, else END
workflow.add_conditional_edges(
    "analyst",
    lambda state: "policy_guard" if state["alert_needed"] else END,
)

# Route: policy_guard -> communicator if not suppressed, else END
workflow.add_conditional_edges(
    "policy_guard",
    lambda state: "communicator" if state["suppression_reason"] is None else END,
)

workflow.add_edge("communicator", END)

graph = workflow.compile()  # compile ONCE at startup
```

### LangGraph: Stateless per-cycle invocation
```python
# Source: https://github.com/langchain-ai/langgraph/discussions/1211
# Compiled graph is thread-safe and stateless — safe to reuse across calls

def run_job():
    """Called by APScheduler on each polling cycle."""
    initial_state: AgentState = {
        "poll_result": None,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
        "llm_confidence": None,
        "llm_reasoning": None,
    }
    result = graph.invoke(initial_state)  # graph compiled once in main()
    return result
```

### Env var validation with fail-fast
```python
def _validate_env() -> int:
    """Returns poll_interval_minutes or exits with clear message."""
    missing = [v for v in ["SNMP_HOST", "ALERT_RECIPIENT"] if not os.getenv(v)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    raw = os.getenv("POLL_INTERVAL_MINUTES", "60")
    try:
        minutes = int(raw)
        if minutes <= 0:
            raise ValueError
    except ValueError:
        print(f"ERROR: POLL_INTERVAL_MINUTES={raw!r} — must be a positive integer")
        sys.exit(1)
    return minutes
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `run_pipeline()` plain sequential function in `supervisor.py` | `StateGraph` with conditional edges compiled via `build_graph()` | Phase 4 (this phase) | Enables LangGraph's state merging via Annotated reducers; execution tracing; aligns with v1 architecture intent documented in CLAUDE.md |
| Manual `if alert_needed: ...` routing in `run_pipeline()` | `add_conditional_edges()` routing in StateGraph | Phase 4 (this phase) | Same logic, expressed as graph edges rather than Python if/else |

**Deprecated/outdated:**
- `supervisor.run_pipeline()` as the primary callable: replaced by `supervisor.build_graph()` returning a compiled graph. The scheduled job in `main.py` constructs initial state and calls `graph.invoke()` directly.
- `load_dotenv()` in `supervisor.py` at module scope: moved to `main.py` entry point.

---

## Open Questions

1. **Where exactly does `build_graph()` live?**
   - What we know: CONTEXT.md marks this as Claude's Discretion — `supervisor.py` or a separate `graph.py` are both valid.
   - What's unclear: Whether keeping it in `supervisor.py` creates a circular import risk (supervisor imports analyst/policy_guard/communicator — those don't import supervisor, so no cycle).
   - Recommendation: Keep `build_graph()` in `supervisor.py` alongside any remaining pipeline utilities. No new file needed for v1 scope.

2. **Should `run_pipeline()` remain as a thin wrapper or be deleted?**
   - What we know: Existing `tests/test_pipeline.py` imports `run_pipeline` directly. Removing it would break 5 existing tests.
   - What's unclear: Whether Phase 4 should update `run_pipeline()` to delegate to the graph, or update the tests to call `graph.invoke()` directly.
   - Recommendation: Keep `run_pipeline()` but reimplement it as a thin wrapper that calls `build_graph().invoke(initial_state)` — or update the test imports. Resolve in planning.

3. **APScheduler ThreadPoolExecutor default worker count (10) vs single poll job**
   - What we know: Default APScheduler `ThreadPoolExecutor` has 10 workers. The poll job is a single I/O-bound task.
   - What's unclear: Whether max_workers=1 would be more explicit for this use case.
   - Recommendation: Accept the default (10 workers). Single job never saturates the pool. Explicit `max_workers=1` can be set but is not necessary.

---

## Sources

### Primary (HIGH confidence)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — BackgroundScheduler setup, interval trigger, shutdown patterns
- [APScheduler IntervalTrigger docs](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/interval.html) — trigger parameters including `jitter`, `start_date`, time units
- [LangGraph Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api) — StateGraph, add_node, add_edge, add_conditional_edges, compile, invoke
- [LangGraph thread safety discussion](https://github.com/langchain-ai/langgraph/discussions/1211) — confirmed: compiled graph is stateless and thread-safe for concurrent invocations

### Secondary (MEDIUM confidence)
- [APScheduler PyPI page](https://pypi.org/project/APScheduler/) — version 3.11.2 confirmed as latest stable; 4.x remains alpha (4.0.0a6)
- [jdhao: Run job immediately on startup](https://jdhao.github.io/2024/11/02/python_apascheduler_start_job_immediately/) — `next_run_time=datetime.now()` confirmed as correct pattern; `start_date=now` on trigger is unreliable

### Tertiary (LOW confidence)
- WebSearch results on SIGTERM handling on Windows — confirmed `signal.SIGTERM` is supported on Windows per Python stdlib docs; graceful shutdown pattern cross-referenced with APScheduler docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — APScheduler 3.11.2 verified on PyPI; LangGraph already in requirements.txt; all APIs verified against official docs
- Architecture: HIGH — Patterns derived from official APScheduler guide and LangGraph graph API docs; thread safety confirmed from LangGraph maintainer discussion
- Pitfalls: HIGH — Most pitfalls derived from specific API behaviors verified in official documentation; `next_run_time` vs `start_date` distinction verified by author article

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (APScheduler 3.x is stable; LangGraph API changes infrequently at this abstraction level)
