---
phase: 04-orchestration
plan: 01
subsystem: orchestration
tags: [langgraph, stategraph, apscheduler, supervisor, pipeline, routing]

# Dependency graph
requires:
  - phase: 03-llm-analyst
    provides: "run_analyst(), run_policy_guard(), run_communicator() typed as AgentState->AgentState LangGraph nodes; AgentState TypedDict with llm_confidence and llm_reasoning"
provides:
  - "build_graph() factory that compiles LangGraph StateGraph with analyst, policy_guard, communicator nodes and conditional routing edges"
  - "run_pipeline() updated as thin delegate to build_graph().invoke()"
  - "APScheduler declared in requirements.txt for Phase 4 Plan 02 (main.py scheduler)"
  - "POLL_INTERVAL_MINUTES documented in .env.example for scheduler configuration"
affects: [04-02-main-entry-point, future-scheduler-plans]

# Tech tracking
tech-stack:
  added: [apscheduler>=3.10.0]
  patterns: [LangGraph StateGraph factory function, named routing functions for conditional edges, build-graph-then-invoke pattern]

key-files:
  created: []
  modified:
    - agents/supervisor.py
    - requirements.txt
    - .env.example

key-decisions:
  - "build_graph() is a factory function not a module-level variable — main.py calls it once at startup and reuses the compiled graph"
  - "load_dotenv() removed from supervisor.py module scope — main.py will call it at entry point (Phase 4 architectural decision)"
  - "_route_after_analyst and _route_after_policy_guard are named functions not lambdas — clarity and testability"
  - "apscheduler>=3.10.0 uses 3.x branch not 4.x alpha — stable 3.11.2 confirmed per RESEARCH.md"
  - "USE_MOCK_LLM added to .env.example — Phase 3 mock mode was implemented but undocumented"

patterns-established:
  - "LangGraph factory pattern: build_graph() constructs and compiles StateGraph, run_pipeline() delegates to graph.invoke(initial_state)"
  - "Conditional routing: named _route_after_* functions return node name string or END constant based on AgentState values"
  - "Initial state construction: all AgentState keys explicitly initialized before graph.invoke() call"

requirements-completed: [SCHD-01]

# Metrics
duration: 20min
completed: 2026-03-02
---

# Phase 4 Plan 01: Supervisor Graph Wiring Summary

**LangGraph StateGraph compiled with analyst->policy_guard->communicator conditional routing via named _route_after_* functions; run_pipeline() delegates to build_graph().invoke(); APScheduler declared for Phase 4 Plan 02**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-02T05:20:00Z
- **Completed:** 2026-03-02T05:41:20Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Refactored supervisor.py to expose build_graph() as a factory that compiles a LangGraph StateGraph with correct conditional edges
- Updated run_pipeline() to delegate to build_graph().invoke() — all 5 existing test_pipeline.py tests remain GREEN
- Removed module-level load_dotenv() from supervisor.py (main.py will call it at startup)
- Added apscheduler>=3.10.0 to requirements.txt for Phase 4 Plan 02 consumption
- Documented POLL_INTERVAL_MINUTES and USE_MOCK_LLM in .env.example
- 92 total tests pass (83 pre-existing + 9 new test_supervisor_graph.py tests from RED commit)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add build_graph() to supervisor.py and update run_pipeline() as delegate** - `19bc0f6` (feat)
2. **Task 2: Add apscheduler to requirements.txt and POLL_INTERVAL_MINUTES to .env.example** - `930eab1` (feat)

**Plan metadata:** (docs commit — see below)

_Note: TDD RED commit for test_supervisor_graph.py was pre-committed as `bdbc5b0` before plan execution. Task 1 above is the GREEN commit._

## Files Created/Modified

- `agents/supervisor.py` - Added build_graph() factory with StateGraph, conditional routing via _route_after_analyst/_route_after_policy_guard; run_pipeline() rewritten as graph.invoke() delegate; load_dotenv() removed from module scope
- `requirements.txt` - Added `# Scheduling (Phase 4)` section with `apscheduler>=3.10.0`
- `.env.example` - Added `POLL_INTERVAL_MINUTES=60` in new Scheduling section; added `USE_MOCK_LLM=false` to Development/Test Mode section

## Decisions Made

- **build_graph() is a factory, not a module-level variable:** main.py will call it once at startup and reuse the compiled graph. This avoids re-compilation on each poll cycle.
- **load_dotenv() removed from supervisor.py:** Phase 4 architectural decision — supervisor.py must be importable without side effects. main.py is the single entry point that owns environment setup.
- **Named routing functions (not lambdas):** `_route_after_analyst` and `_route_after_policy_guard` are defined as named functions for clarity and testability, following plan specification.
- **apscheduler 3.x constraint:** `>=3.10.0` targets the stable 3.11.2 release. APScheduler 4.x is still alpha per RESEARCH.md and not used.
- **USE_MOCK_LLM documented:** Phase 3 introduced mock LLM mode but .env.example was never updated. Added as a deviation to keep documentation in sync.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added USE_MOCK_LLM to .env.example**
- **Found during:** Task 2 (.env.example update)
- **Issue:** Phase 3 added USE_MOCK_LLM env var to analyst.py but never documented it in .env.example. Any developer setting up from .env.example would not know this option exists.
- **Fix:** Added `USE_MOCK_LLM=false` to the Development/Test Mode section of .env.example with a documentation comment
- **Files modified:** .env.example
- **Verification:** grep "USE_MOCK_LLM" .env.example returns the entry
- **Committed in:** `930eab1` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing documentation — Rule 2)
**Impact on plan:** Minimal — documentation-only addition for pre-existing functionality. No scope creep.

## Issues Encountered

- The Python environment used during execution (Python 3.14.2) required separate `pip install` for langgraph, langchain-core, and langchain-openai since pysnmp-sync-adapter fails to build on Python 3.14 (missing pkg_resources in temp dirs, same issue noted in Phase 3 decision log). The test suite ran correctly once dependencies were installed.
- Stray empty files (`=0.2.0`, `=0.3.0`, `=1.0.0`, `=4.0.0`) were created in project root during pip install (pip incorrectly parsed `>=` version specifier when passed as positional arg). Removed before committing.

## Next Phase Readiness

- **build_graph() is ready for main.py:** Plan 02 can call `from agents.supervisor import build_graph` and use the returned CompiledStateGraph directly in the scheduler.
- **APScheduler declared:** `apscheduler>=3.10.0` is in requirements.txt. Plan 02 can import APScheduler without any requirements change.
- **POLL_INTERVAL_MINUTES documented:** .env.example shows users what to configure before running the scheduler.
- **No blockers:** All 92 tests GREEN. Supervisor graph compiles and invokes correctly end-to-end.

## Self-Check: PASSED

- agents/supervisor.py: FOUND
- requirements.txt: FOUND
- .env.example: FOUND
- .planning/phases/04-orchestration/04-01-SUMMARY.md: FOUND
- Commit 19bc0f6 (Task 1): FOUND
- Commit 930eab1 (Task 2): FOUND

---
*Phase: 04-orchestration*
*Completed: 2026-03-02*
