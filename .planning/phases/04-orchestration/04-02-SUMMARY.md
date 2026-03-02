---
phase: 04-orchestration
plan: 02
subsystem: infra
tags: [apscheduler, langgraph, dotenv, scheduling, entry-point]

# Dependency graph
requires:
  - phase: 04-01
    provides: build_graph() LangGraph StateGraph factory compiled at startup
  - phase: 01-02
    provides: append_poll_result() JSONL persistence for pipeline_error logging
provides:
  - "main.py entry point with APScheduler BackgroundScheduler, env validation, and graceful shutdown"
  - "tests/test_main.py with 11 tests covering env validation, initial state, and error boundary"
  - "SCHD-01: python main.py starts Sentinel and polls automatically on configured interval"
affects: []

# Tech tracking
tech-stack:
  added: [apscheduler==3.11.2, tzdata, tzlocal, langgraph==0.2.73 (installed)]
  patterns:
    - "load_dotenv() called at module top-level before any project imports — RESEARCH.md Pitfall 2"
    - "Compiled graph reused across polling cycles — build_graph() called once in main()"
    - "_build_initial_state() called per cycle inside run_job() — no state leak between polls"
    - "next_run_time=datetime.now() for immediate first poll on scheduler.start()"
    - "Module-level test imports to prevent load_dotenv() re-run per test case"

key-files:
  created:
    - "main.py"
    - "tests/test_main.py"
  modified:
    - "guardrails/safety_logic.py"

key-decisions:
  - "load_dotenv() called before project imports at module top level in main.py — prevents env miss at import time"
  - "build_graph() compiled once in main() before scheduler starts — never inside run_job()"
  - "_build_initial_state() returns a fresh dict per polling cycle — called inside run_job() each cycle"
  - "next_run_time=datetime.now() NOT start_date — ensures immediate first poll without waiting full interval"
  - "SIGTERM handler uses a mutable list as ref container to access scheduler from closure"
  - "Module-level import of _validate_env and _build_initial_state in test_main.py — prevents load_dotenv() re-run per test overwriting monkeypatched env vars"
  - "AgentState imported at runtime scope in safety_logic.py — TYPE_CHECKING guard caused NameError in LangGraph 0.2.73 get_type_hints()"

patterns-established:
  - "Scheduled entry point pattern: validate env -> compile graph once -> start scheduler -> block in while-True"
  - "Error boundary pattern: run_job() wraps graph.invoke() in try/except, logs via logger.exception(), persists pipeline_error to JSONL"
  - "Test isolation pattern: import module-level functions once at top of test module to prevent dotenv re-run side effects"

requirements-completed: [SCHD-01]

# Metrics
duration: 8min
completed: 2026-03-02
---

# Phase 4 Plan 02: APScheduler Entry Point Summary

**APScheduler BackgroundScheduler entry point in main.py with env validation, immediate-first-poll, pipeline error boundary, and graceful shutdown — 103 tests GREEN**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-02T05:50:05Z
- **Completed:** 2026-03-02T05:57:42Z
- **Tasks:** 2 (TDD: RED + GREEN per task)
- **Files modified:** 3

## Accomplishments

- main.py entry point: `python main.py` starts Sentinel, validates env, prints startup banner, and begins polling immediately via APScheduler
- _validate_env() exits with code 1 and clear error for missing SNMP_HOST, ALERT_RECIPIENT, or invalid POLL_INTERVAL_MINUTES
- run_job() error boundary: pipeline exceptions logged and appended as pipeline_error events to JSONL — scheduler never crashes
- 11 new tests in tests/test_main.py all GREEN; all 103 tests pass

## Task Commits

Each task was committed atomically:

1. **TDD RED: tests/test_main.py (failing)** - `05c6930` (test)
2. **TDD GREEN: main.py implementation + safety_logic.py bug fix** - `1c4c88f` (feat)
3. **TDD GREEN: tests/test_main.py finalized** - `575a216` (feat)

_Note: TDD tasks have multiple commits (RED test commit, then GREEN implementation commit)_

## Files Created/Modified

- `C:/Users/rohit/ROHIT/Project-Sentinel/main.py` - Entry point: env validation, load_dotenv(), build_graph() once, BackgroundScheduler with immediate first poll, SIGTERM handler, KeyboardInterrupt handler
- `C:/Users/rohit/ROHIT/Project-Sentinel/tests/test_main.py` - 11 tests: 8 env validation, 2 initial state, 1 run_job error boundary
- `C:/Users/rohit/ROHIT/Project-Sentinel/guardrails/safety_logic.py` - Bug fix: AgentState moved from TYPE_CHECKING guard to runtime import

## Decisions Made

- load_dotenv() placed before project imports at module top level in main.py — RESEARCH.md Pitfall 2 compliance
- build_graph() compiled once before scheduler.start() — never inside run_job(), avoids re-compilation overhead per poll
- SIGTERM closure pattern: `scheduler_ref` list used as mutable container since closures can't rebind outer variables
- Module-level test imports prevent load_dotenv() from re-running during each test, which would overwrite monkeypatched env vars

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed safety_logic.py TYPE_CHECKING guard causing NameError in LangGraph 0.2.73**
- **Found during:** Task 1 (full test suite verification after langgraph installation)
- **Issue:** `guardrails/safety_logic.py` imported `AgentState` under `if TYPE_CHECKING:` with `from __future__ import annotations`. LangGraph v0.2.73 calls `get_type_hints()` on node functions at `add_node()` time. With deferred annotations, Python resolves the string `"AgentState"` in the module's global namespace at runtime — but since the import is guarded by `TYPE_CHECKING` (which is `False` at runtime), `AgentState` was not in globals, causing `NameError: name 'AgentState' is not defined`. This broke 10 tests in test_supervisor_graph.py and test_pipeline.py.
- **Fix:** Moved `from state_types import AgentState, PollResult` to runtime scope (outside `TYPE_CHECKING` guard) in safety_logic.py
- **Files modified:** `guardrails/safety_logic.py`
- **Verification:** All 10 previously-failing tests in test_supervisor_graph.py and test_pipeline.py now pass; 103 total tests GREEN
- **Committed in:** `1c4c88f` (part of Task 1 implementation commit)

**2. [Rule 3 - Blocking] Installed langgraph==0.2.73 and apscheduler==3.11.2**
- **Found during:** Task 1 setup (checking dependencies)
- **Issue:** langgraph was declared in requirements.txt but not installed in the venv. apscheduler was also not installed. Both are required for main.py to import and tests to run.
- **Fix:** Installed langgraph==0.2.73 and apscheduler==3.11.2 via pip
- **Files modified:** None (venv only)
- **Verification:** `import langgraph`, `import apscheduler` succeed; 103 tests pass

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 blocking dependency)
**Impact on plan:** Both auto-fixes required for correctness. Rule 1 fix restored 10 pre-existing tests that would have been broken by the langgraph installation. No scope creep.

## Issues Encountered

- **load_dotenv() re-run edge case in tests:** When `from main import _validate_env` was placed inside individual test methods, importing `main` triggered `load_dotenv()` which re-set env vars that monkeypatch had just removed. Fixed by moving the import to module level — `main` is imported once and `load_dotenv()` only fires once.

## User Setup Required

None - no external service configuration required for the entry point itself. Existing `.env` file already has all required keys documented.

## Next Phase Readiness

- Phase 4 is complete. All 2 plans in Phase 04-orchestration are done.
- main.py is the final deliverable of Phase 4. Running `python main.py` starts Sentinel autonomously.
- Phase 5 (if any) or production deployment can proceed.
- Live hardware testing (Lexmark XC2235 SNMP, Outlook SMTP) remains the only outstanding validation step.

---
*Phase: 04-orchestration*
*Completed: 2026-03-02*
