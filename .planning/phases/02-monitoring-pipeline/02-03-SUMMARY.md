---
phase: 02-monitoring-pipeline
plan: 03
subsystem: monitoring
tags: [communicator, supervisor, smtp, langgraph, pipeline, tdd, pytest]

# Dependency graph
requires:
  - phase: 02-monitoring-pipeline/02-01
    provides: run_analyst() deterministic threshold checker and AgentState with flagged_colors
  - phase: 02-monitoring-pipeline/02-02
    provides: run_policy_guard() with rate limiting, staleness check, and record_alert_sent()
  - phase: 01-foundation/01-03
    provides: SMTPAdapter.send_alert() for outbound email dispatch
provides:
  - agents/communicator.py — run_communicator() builds CONTEXT.md-compliant subject/body and dispatches single email via SMTPAdapter
  - agents/supervisor.py — run_pipeline() sequential coordinator: analyst -> policy_guard -> communicator
  - Complete Phase 2 monitoring pipeline — end-to-end low-toner detection to email alert with policy gating
  - 15 new tests (10 communicator + 5 pipeline integration) — 74 total passing across 8 test files
affects:
  - Phase 4: Orchestration (LangGraph StateGraph wiring will replace run_pipeline() sequential call)
  - Phase 3: LLM Analyst (analyst.py will be extended; communicator.py email body will add reasoning)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single send_alert() call regardless of flagged color count — one email per poll cycle with all colors listed"
    - "run_pipeline() accepts optional pre-fetched PollResult — enables test injection without SNMP network calls"
    - "TDD RED/GREEN flow — test file committed before implementation, then implementation committed to pass"
    - "USE_MOCK_SMTP and USE_MOCK_SNMP env vars control adapter mock mode — no code changes for testing"

key-files:
  created:
    - agents/communicator.py
    - agents/supervisor.py
    - tests/test_communicator.py
    - tests/test_pipeline.py
  modified:
    - .env.example

key-decisions:
  - "build_subject() uses em dash (U+2014) per CONTEXT.md locked format — not double hyphen"
  - "Overall urgency is CRITICAL if ANY flagged color has urgency==CRITICAL — WARNING only when all are WARNING"
  - "run_pipeline() is a plain sequential function in Phase 2 — LangGraph StateGraph wiring deferred to Phase 4"
  - "run_communicator() raises ValueError on missing ALERT_RECIPIENT — fail-fast at agent boundary, not silently"
  - "SNMPAdapter.poll() is synchronous (wraps asyncio internally) — asyncio.run() in supervisor was incorrect and was fixed"

patterns-established:
  - "Agent functions all take and return AgentState — consistent pipeline carrier pattern"
  - "Mock mode via environment variable — USE_MOCK_SMTP=true, USE_MOCK_SNMP=true — no constructor args needed in tests"
  - "Decision log entries follow format: 'agent_name: human-readable action description'"

requirements-completed: [ALRT-02, GURD-04]

# Metrics
duration: ~25min
completed: 2026-03-01
---

# Phase 2 Plan 03: Communicator and Pipeline Coordinator Summary

**Sequential monitoring pipeline complete: communicator.py dispatches CONTEXT.md-format alert emails via SMTPAdapter and supervisor.py chains analyst -> policy_guard -> communicator with 74 tests passing end-to-end**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-03-01T13:20:00Z (estimated from commit timestamps)
- **Completed:** 2026-03-01T18:45:06Z (including checkpoint verification)
- **Tasks:** 3 (2 TDD auto + 1 human-verify checkpoint)
- **Files modified:** 5

## Accomplishments

- agents/communicator.py exports run_communicator() — builds exact CONTEXT.md subject/body format (em dash, urgency rollup, single send regardless of color count) and calls record_alert_sent() for rate limit update
- agents/supervisor.py exports run_pipeline() — sequential analyst -> policy_guard -> communicator with optional PollResult injection for test isolation
- 74 tests pass across 8 test files — 10 communicator unit tests + 5 pipeline integration tests added; no regressions
- Smoke test confirmed: pipeline runs end-to-end with mock adapters, producing alert_needed=True, alert_sent=True, suppression_reason=None

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement agents/communicator.py (TDD RED)** - `f3e4645` (test)
2. **Task 1: Implement agents/communicator.py (TDD GREEN)** - `29cd893` (feat)
3. **Task 2: Implement agents/supervisor.py (TDD RED)** - `c0094f2` (test)
4. **Task 2: Implement agents/supervisor.py (TDD GREEN)** - `758ed32` (feat)
5. **Task 3 auto-fix: SNMPAdapter host + poll() sync fix** - `610d819` (fix)

_Note: TDD tasks have two commits each (test RED then feat GREEN). Task 3 was a human-verify checkpoint — no new code committed after approval._

## Files Created/Modified

- `agents/communicator.py` - Email construction (build_subject, build_body) and dispatch (run_communicator) via SMTPAdapter
- `agents/supervisor.py` - Sequential pipeline coordinator run_pipeline() with optional PollResult injection
- `tests/test_communicator.py` - 10 unit tests covering subject/body format, dispatch, record_alert_sent(), and error handling
- `tests/test_pipeline.py` - 5 integration tests covering alert/no-alert paths, decision_log content, and mock end-to-end
- `.env.example` - Appended TONER_ALERT_THRESHOLD, TONER_CRITICAL_THRESHOLD, STALE_THRESHOLD_MINUTES

## Decisions Made

- **Em dash subject format**: build_subject() uses U+2014 per CONTEXT.md locked format — not a double hyphen. Future agents must not change this character.
- **CRITICAL urgency rollup**: Overall subject urgency is CRITICAL if ANY flagged color is CRITICAL, WARNING only when all are WARNING. Mixed-urgency batches still send one email.
- **Plain sequential pipeline for Phase 2**: run_pipeline() is a regular function, not a LangGraph StateGraph. LangGraph wiring is deferred to Phase 4 (Orchestration) where it adds real value (conditional edges, retries, persistence).
- **Fail-fast on missing ALERT_RECIPIENT**: run_communicator() raises ValueError immediately rather than silently skipping — misconfigured environment should fail loudly.
- **SNMPAdapter.poll() is synchronous**: The adapter wraps asyncio internally; calling asyncio.run() on top was incorrect and was auto-fixed during verification.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SNMPAdapter missing host argument and asyncio.run() on synchronous poll()**
- **Found during:** Task 3 (Verify complete Phase 2 pipeline end-to-end) — smoke test of run_pipeline() with no pre-fetched PollResult
- **Issue:** supervisor.py instantiated SNMPAdapter() without the required host argument, and called asyncio.run(snmp.poll()) when poll() is already synchronous (the adapter handles its own asyncio loop internally)
- **Fix:** Read SNMP_HOST from os.getenv("SNMP_HOST", "127.0.0.1"), pass to SNMPAdapter(host=snmp_host), call snmp.poll() directly without asyncio.run()
- **Files modified:** agents/supervisor.py
- **Verification:** Smoke test completed without errors; 74/74 tests still pass
- **Committed in:** 610d819 (fix(02-03))

**2. [Rule 1 - Bug] Test isolation for alert_state monkeypatching in pipeline tests**
- **Found during:** Task 2 (implementing test_pipeline.py)
- **Issue:** Default argument captures in run_policy_guard made module-attribute monkeypatching of ALERT_STATE_PATH ineffective across tests — cross-test contamination with alert_state.json
- **Fix:** Used in-memory store approach with _load_alert_state/_save_alert_state monkeypatching to ensure clean state per test
- **Files modified:** tests/test_pipeline.py (extended during GREEN commit)
- **Verification:** Pipeline tests run in any order without cross-contamination
- **Committed in:** 758ed32 (feat(02-03))

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both auto-fixes necessary for correct behavior. No scope creep. Plan delivered as specified.

## Issues Encountered

- asyncio.run() pattern from Phase 1 decision (for snmp_adapter async tests) did not carry over correctly to supervisor.py — SNMPAdapter.poll() wraps asyncio internally and does not need an outer asyncio.run(). Fixed in 610d819.

## User Setup Required

None - no external service configuration required beyond existing .env variables.

## Next Phase Readiness

- Phase 2 monitoring pipeline is complete and verified end-to-end with mock adapters
- All 74 tests pass across 8 test files; no known regressions
- run_pipeline() is ready to be called from main.py scheduler (Phase 4)
- Phase 3 (LLM Analyst) can extend analyst.py to add confidence scoring and trend analysis — communicator.py email body will need the analyst reasoning field added to AgentState
- Blocker: Physical Lexmark XC2235 device needed to validate SNMP OIDs return correct toner data
- Blocker: Outlook SMTP credentials (SMTP_USERNAME + SMTP_PASSWORD) needed to validate live email delivery

---
*Phase: 02-monitoring-pipeline*
*Completed: 2026-03-01*

## Self-Check: PASSED

All files and commits verified:
- FOUND: agents/communicator.py
- FOUND: agents/supervisor.py
- FOUND: tests/test_communicator.py
- FOUND: tests/test_pipeline.py
- FOUND: .env.example
- FOUND commit: f3e4645 (test RED — communicator)
- FOUND commit: 29cd893 (feat GREEN — communicator)
- FOUND commit: c0094f2 (test RED — pipeline)
- FOUND commit: 758ed32 (feat GREEN — supervisor + pipeline)
- FOUND commit: 610d819 (fix — SNMPAdapter host + sync poll)
