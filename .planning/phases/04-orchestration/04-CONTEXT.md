# Phase 4: Orchestration - Context

**Gathered:** 2026-03-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the existing agent nodes into a LangGraph StateGraph and schedule autonomous hourly polling from `python main.py`. No new agent logic — pure wiring and scheduling. Phase succeeds when the full pipeline (SNMP poll → analyst → policy guard → communicator) runs end-to-end on a configurable interval without manual intervention.

</domain>

<decisions>
## Implementation Decisions

### Startup Behavior
- Run an immediate first poll on startup, then schedule hourly after that (don't wait an hour blind)
- If the startup poll fails (SNMP unreachable, exception), log the error and continue — Sentinel stays up and proceeds to the scheduled loop
- Show a startup banner to console: includes Sentinel name, polling interval, and "first poll running now"
- Validate required env vars (SNMP_HOST, ALERT_RECIPIENT, etc.) at startup — fail fast with a clear message listing what's missing, before starting the scheduler
- On Ctrl+C or SIGTERM: catch cleanly, log "Sentinel stopped", exit without dumping a stack trace

### Polling Interval
- Driven by `POLL_INTERVAL_MINUTES` env var (add to .env.example with documentation)
- Default: 60 minutes when env var is not set
- Invalid values (0, negative, non-numeric): fail fast at startup with a clear error message — consistent with env var validation above
- Show the active interval in the startup banner (e.g. "polling every 60 minutes")

### Scheduler (APScheduler)
- Use APScheduler with an **interval trigger** (every N minutes from process start — not cron-style fixed clock times)
- In-memory job store — no SQLite or persistent state; the immediate startup poll covers any gap from restarts
- Non-blocking mode: `scheduler.start()` runs in a background thread; main thread sits in a `try/except KeyboardInterrupt` loop waiting for shutdown
- LangGraph StateGraph is **compiled once at startup** (`graph = workflow.compile()`) and reused each cycle — fresh `AgentState` dict is created per invocation via `graph.invoke(initial_state)`

### LangGraph Wiring (supervisor.py)
- Replace the current plain sequential function with a `StateGraph` with one node per agent stage
- Conditional edges: route past policy guard if `alert_needed=False`, skip communicator if `suppression_reason` is set — mirrors existing conditional logic in the sequential function
- `supervisor.py` exposes `build_graph()` returning a compiled graph; `main.py` calls it at startup

### Error Resilience
- Error boundary lives in `main.py`'s scheduled job wrapper — `run_pipeline()` and the graph remain clean
- On exception: log full traceback via `logger.exception()` at ERROR level; also append `event_type=pipeline_error` record to the JSONL audit log (consistent with `llm_failure` events)
- No escalation for consecutive failures in v1 — log each one and keep running

### Claude's Discretion
- APScheduler executor type (ThreadPoolExecutor vs ProcessPoolExecutor — threading is fine for I/O-bound polling)
- Exact startup banner format beyond the required content (interval, printer host, first poll notice)
- Logging configuration in main.py (format string, log level default)
- Whether `build_graph()` or equivalent lives in `supervisor.py` or a separate `graph.py`

</decisions>

<specifics>
## Specific Ideas

No specific references or "I want it like X" moments from discussion — open to standard APScheduler patterns for the scheduling implementation.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `supervisor.run_pipeline(poll_result=None) -> AgentState`: Current plain sequential function — Phase 4 replaces this with a LangGraph StateGraph, but the SNMP polling logic and state initialization pattern are reused
- `state_types.AgentState`: Already has `Annotated[list[str], operator.add]` on `decision_log` — built for LangGraph reducers from day one; no changes needed
- `adapters/persistence.append_poll_result()`: Used to log `pipeline_error` events (same pattern as `llm_failure` logging in `analyst.py`)
- All three agent functions (`run_analyst`, `run_policy_guard`, `run_communicator`): Already typed as `(AgentState) -> AgentState` — drop-in LangGraph node functions

### Established Patterns
- Mock mode pattern (`USE_MOCK_SNMP`, `USE_MOCK_LLM`, `USE_MOCK_SMTP`): Phase 4 may need `USE_MOCK_PIPELINE` or similar for testing the scheduler without real hardware
- Error logging pattern: `event_type=llm_failure` in JSONL → Phase 4 adds `event_type=pipeline_error` using the same `append_poll_result()` call
- `load_dotenv()` is called at the top of `supervisor.py` — `main.py` should call it once at entry point instead
- State initialization: current `run_pipeline()` creates the initial `AgentState` dict with all required keys — this moves to `main.py`'s scheduled job function

### Integration Points
- `main.py` is currently empty — Phase 4 builds it from scratch as the entry point
- `langgraph>=0.2.0` is already in `requirements.txt` — no new LangGraph dependency needed
- APScheduler is a new dependency — add `apscheduler>=3.10.0` to `requirements.txt`
- `.env.example` needs `POLL_INTERVAL_MINUTES` added with documentation comment

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-orchestration*
*Context gathered: 2026-03-01*
