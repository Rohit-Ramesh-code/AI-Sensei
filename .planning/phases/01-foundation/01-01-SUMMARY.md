---
phase: 01-foundation
plan: "01"
subsystem: infra
tags: [snmp, pysnmp, typeddict, langgraph, quality-flag, printer-mib, mock-mode]

# Dependency graph
requires: []
provides:
  - "QualityFlag str Enum — 8 members, JSON-serializable without custom encoder"
  - "TonerReading TypedDict — single-color SNMP reading with data_quality_ok flag"
  - "PollResult TypedDict — aggregated CMYK poll result with overall_quality_ok"
  - "AgentState TypedDict — LangGraph pipeline state with Annotated decision_log reducer"
  - "classify_snmp_value() — pure function converting raw SNMP integers to QualityFlag"
  - "SNMPAdapter class — mock mode + real pysnmp v7 asyncio polling"
affects:
  - 01-02-plan
  - 01-03-plan
  - agents/analyst
  - agents/communicator
  - agents/supervisor
  - guardrails/safety_logic

# Tech tracking
tech-stack:
  added:
    - pysnmp==7.1.22 (pure Python SNMP engine, asyncio API)
    - python-dotenv (env var loading)
    - pytest (test runner, already in venv)
  patterns:
    - "QualityFlag(str, Enum) for JSON-safe sentinel encoding"
    - "TypedDict state contract — no Pydantic, zero extra dependencies"
    - "Annotated[list[str], operator.add] reducer for LangGraph multi-node writes"
    - "Mock mode via USE_MOCK_SNMP env flag — branch at adapter init, not import time"
    - "Adapter never raises — transport failures caught, returned as PollResult.snmp_error"
    - "Dynamic OID index discovery via prtMarkerSuppliesDescription walk"

key-files:
  created:
    - state_types.py
    - adapters/snmp_adapter.py
    - tests/test_state_types.py
    - tests/test_snmp_adapter.py
  modified:
    - requirements.txt

key-decisions:
  - "Used asyncio.run() instead of pysnmp-sync-adapter (package incompatible with build environment — pkg_resources missing from build isolation)"
  - "QualityFlag extends both str and Enum — str mixin ensures .value is a plain string for JSON serialization"
  - "classify_snmp_value checks max_capacity <= 0 as sentinel — prevents nonsensical negative percentages"
  - "MOCK_FIXTURE hardcodes magenta=-2 (UNKNOWN) and yellow=-3 (BELOW_LOW) to ensure test coverage of bad-quality paths"
  - "SNMPAdapter.use_mock combines constructor arg OR env var — allows both programmatic and env-based override"

patterns-established:
  - "Pattern 1: QualityFlag(str, Enum) — all downstream agents compare flag values as strings"
  - "Pattern 2: TypedDict as LangGraph state contract — import from state_types everywhere"
  - "Pattern 3: Adapter never raises — always returns structured result, callers check snmp_error"
  - "Pattern 4: Mock mode env flag (USE_MOCK_SNMP=true) for offline dev and CI testing"

requirements-completed: [SNMP-01, SNMP-02, SNMP-03]

# Metrics
duration: 9min
completed: 2026-03-01
---

# Phase 1 Plan 01: State Types and SNMP Adapter Summary

**QualityFlag str Enum + TypedDict state contract (state_types.py) and SNMPAdapter with classify_snmp_value sentinel handling and mock mode (adapters/snmp_adapter.py)**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-01T02:16:55Z
- **Completed:** 2026-03-01T02:25:45Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 5

## Accomplishments

- Defined the complete LangGraph data contract in state_types.py — QualityFlag, TonerReading, PollResult, AgentState — importable by all downstream agents with zero external dependencies
- Implemented classify_snmp_value() covering all RFC 3805 sentinel values (-1, -2, -3, None, out-of-range, max_capacity sentinel) correctly
- Built SNMPAdapter with mock mode (MOCK_FIXTURE returns 4 CMYK readings with sentinel values exercised) and real pysnmp v7 asyncio poll path with dynamic OID index discovery
- All 22 tests pass across both modules

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: State types failing tests** - `2301419` (test)
2. **Task 1 GREEN: state_types.py implementation** - `fa395f1` (feat)
3. **Task 2 RED: SNMP adapter failing tests** - `6abe352` (test)
4. **Task 2 GREEN: adapters/snmp_adapter.py implementation** - `f0fdd62` (feat)

_Note: TDD tasks have separate RED (test) and GREEN (feat) commits._

## Files Created/Modified

- `state_types.py` — QualityFlag(str, Enum) with 8 members; TonerReading, PollResult, AgentState TypedDicts; Annotated decision_log reducer
- `adapters/snmp_adapter.py` — classify_snmp_value() pure function; MOCK_FIXTURE dict; SNMPAdapter class with mock and real poll modes
- `tests/test_state_types.py` — 8 tests covering enum values, JSON serialization, TypedDict construction, Annotated reducer introspection
- `tests/test_snmp_adapter.py` — 14 tests covering all sentinel classification cases and mock mode PollResult behavior
- `requirements.txt` — Added pysnmp==7.1.22

## Decisions Made

- **asyncio.run() instead of pysnmp-sync-adapter:** The pysnmp-sync-adapter package (v1.0.8) uses pkg_resources in its setup.py, which is not available in pip's build isolation environment. The package fails to build on both Python 3.12 and 3.14. asyncio.run() is the documented alternative and is functionally identical.
- **QualityFlag extends str:** Ensures .value is a plain Python str, making json.dumps({"flag": QualityFlag.OK}) work without a custom JSONEncoder — a requirement for the JSON Lines log in Plan 02.
- **max_capacity sentinel check:** classify_snmp_value checks max_capacity <= 0 before computing the percentage, preventing nonsensical results when the device returns -2 for max_capacity (documented Pitfall 5 in RESEARCH.md).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used asyncio.run() instead of pysnmp-sync-adapter**
- **Found during:** Task 2 (SNMP adapter implementation setup)
- **Issue:** pysnmp-sync-adapter 1.0.8 cannot be built — setup.py imports pkg_resources which is absent from pip build isolation environment. Fails on Python 3.12 and 3.14.
- **Fix:** Implemented real SNMP poll using asyncio.run(_poll_real_async()) which calls pysnmp v7's asyncio getCmd() directly. This is the documented alternative in RESEARCH.md ("Alternatively, run pysnmp inside asyncio.run()").
- **Files modified:** adapters/snmp_adapter.py
- **Verification:** All 14 SNMP adapter tests pass; mock mode and import paths verified.
- **Committed in:** f0fdd62 (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking dependency)
**Impact on plan:** No scope creep. The real SNMP poll path is functionally identical to pysnmp-sync-adapter since both ultimately call pysnmp v7's asyncio API. Mock mode (all tests) is unaffected.

## Issues Encountered

None beyond the pysnmp-sync-adapter build issue documented above.

## User Setup Required

Before running against the live printer, add to `.env`:
- `SNMP_HOST` — IP address of the Lexmark XC2235 (e.g., 192.168.1.100)
- `SNMP_COMMUNITY` — SNMP community string (default: `public`)
- `USE_MOCK_SNMP=true` — for offline testing without the printer

## Next Phase Readiness

- state_types.py is ready for import by all downstream agents (analyst, communicator, supervisor, guardrails)
- SNMPAdapter.poll() in mock mode is fully tested and functional
- Real SNMP polling requires physical device access and correct env vars — test against live XC2235 when available
- Plan 02 (JSON Lines persistence log) can consume PollResult dicts directly — QualityFlag.value is already a JSON-safe string

## Self-Check: PASSED

All files verified present:
- FOUND: state_types.py
- FOUND: adapters/snmp_adapter.py
- FOUND: tests/test_state_types.py
- FOUND: tests/test_snmp_adapter.py
- FOUND: .planning/phases/01-foundation/01-01-SUMMARY.md

All task commits verified:
- FOUND: 2301419 (test — state_types failing tests)
- FOUND: fa395f1 (feat — state_types implementation)
- FOUND: 6abe352 (test — snmp_adapter failing tests)
- FOUND: f0fdd62 (feat — snmp_adapter implementation)

---
*Phase: 01-foundation*
*Completed: 2026-03-01*
