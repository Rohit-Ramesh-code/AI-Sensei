---
phase: 02-monitoring-pipeline
plan: 02
subsystem: guardrails
tags: [policy-guard, rate-limiting, data-quality, jsonl, alert-state, tdd]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: adapters/persistence.py — append_poll_result() and LOG_PATH used for suppression logging
  - phase: 02-monitoring-pipeline
    plan: 01
    provides: state_types.AgentState, state_types.PollResult — data contracts consumed by policy guard
provides:
  - guardrails/safety_logic.py exporting run_policy_guard() and record_alert_sent()
  - Rate limiting: 1 alert per printer per 24-hour window via logs/alert_state.json
  - Staleness check: suppresses polls older than STALE_THRESHOLD_MINUTES (default 120)
  - SNMP quality check: suppresses when poll_result.snmp_error is set
  - Suppression audit trail: every blocked alert appended to printer_history.jsonl
  - tests/test_safety_logic.py: 10-test TDD suite covering all guard behaviors
affects:
  - agents/communicator.py — must call run_policy_guard() before sending; check alert_needed after
  - agents/supervisor.py — must call record_alert_sent() after communicator succeeds
  - main.py — no direct dependency but pipeline integrity depends on guard being wired

# Tech tracking
tech-stack:
  added: []  # No new packages — uses json/pathlib/datetime stdlib + existing adapters.persistence
  patterns:
    - TDD (RED → GREEN) — test suite committed before implementation
    - Injectable file paths (state_path, log_path keyword args) enable test isolation without patching globals
    - Timezone-aware datetime (timezone.utc) throughout to avoid naive/aware TypeError
    - Graceful degradation: corrupted or missing alert_state.json returns {} (never crashes)
    - Short-circuit evaluation: freshness → quality → rate limit; first failure skips remaining checks

key-files:
  created:
    - guardrails/safety_logic.py
    - tests/test_safety_logic.py
  modified: []

key-decisions:
  - "check_data_freshness() uses timezone.utc explicitly — avoids naive/aware TypeError when subtracting datetime objects"
  - "state_path and log_path are keyword-only parameters on all helpers — test isolation without monkeypatching globals"
  - "Check order is freshness → SNMP quality → rate limit — most likely failures first, cheapest checks first"
  - "log_suppression() calls adapters.persistence.append_poll_result() reusing existing JSONL infrastructure"
  - "_load_alert_state() catches both json.JSONDecodeError and OSError — handles corrupted files and permission errors"

patterns-established:
  - "Policy guard pattern: check returns (bool, Optional[str]) tuple — caller decides suppression action"
  - "Injectable path pattern: default=MODULE_CONSTANT in signature, pass tmp_path in tests"
  - "Suppression record schema: {event_type, printer_host, timestamp, reason} — consistent audit format"

requirements-completed: [GURD-01, GURD-03, GURD-04, ALRT-03]

# Metrics
duration: 18min
completed: 2026-03-01
---

# Phase 2 Plan 02: Policy Guard Summary

**Rate-limiting and data-quality Policy Guard in guardrails/safety_logic.py — suppresses alerts within 24h windows, stale polls, and SNMP errors, with full JSONL audit trail via alert_state.json**

## Performance

- **Duration:** 18 min
- **Started:** 2026-03-01T18:13:37Z
- **Completed:** 2026-03-01T18:31:00Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- Policy Guard with three independent gating checks: data freshness, SNMP quality, rate limit
- alert_state.json read-modify-write pattern with graceful fallback on corruption or missing file
- Every suppressed alert appended to printer_history.jsonl with event_type, reason, timestamp, and printer_host
- 10-test TDD suite covers all behaviors; 59/59 full suite tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Write test_safety_logic.py test suite (RED)** - `6342e60` (test)
2. **Task 2: Implement guardrails/safety_logic.py Policy Guard (GREEN)** - `e3955c5` (feat)

_Note: TDD tasks — test suite committed RED before implementation. Implementation committed GREEN after all 10 tests passed._

## Files Created/Modified
- `guardrails/safety_logic.py` - Policy Guard: run_policy_guard(), record_alert_sent(), check_data_freshness(), check_snmp_quality(), check_rate_limit(), log_suppression(), _load_alert_state(), _save_alert_state()
- `tests/test_safety_logic.py` - 10-test TDD suite: rate limit (within/after 24h), no state file, corrupted state file, stale data, fresh data, snmp_error, JSONL suppression record, record_alert_sent file creation, alert_needed=False no-op

## Decisions Made
- `timezone.utc` used explicitly in all datetime operations to avoid naive/aware TypeError
- `state_path` and `log_path` are keyword-only parameters — eliminates need to monkeypatch globals in tests
- Check order (freshness → quality → rate limit) runs cheapest/most common failures first
- `_load_alert_state()` catches `(json.JSONDecodeError, OSError)` — handles both corrupted content and file system errors
- `log_suppression()` reuses `adapters.persistence.append_poll_result()` — no new JSONL code needed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing jsonlines package in py (Python 3.14) environment**
- **Found during:** Task 2 (GREEN phase test run)
- **Issue:** `py -m pytest` used Python 3.14 environment which lacked jsonlines; `adapters/persistence.py` import failed with ModuleNotFoundError
- **Fix:** Ran `py -m pip install jsonlines python-dotenv` to install required packages in the test environment
- **Files modified:** None (runtime environment fix only)
- **Verification:** All 10 tests passed after install; full suite 59/59 green
- **Committed in:** e3955c5 (part of Task 2 commit — no code change required)

---

**Total deviations:** 1 auto-fixed (1 blocking environment issue)
**Impact on plan:** Environment-only fix, no code or scope changes.

## Issues Encountered
- Python 3.14 (`py` launcher) environment lacked `jsonlines` package — existing tests for persistence also rely on it. Installed via `py -m pip install jsonlines`. No code changes required.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Policy Guard is fully implemented and tested; ready for wiring into LangGraph supervisor
- agents/communicator.py must call `run_policy_guard(state)` before sending; check `state["alert_needed"]` after
- agents/supervisor.py must call `record_alert_sent(printer_host)` after communicator sends successfully
- `logs/alert_state.json` will be created on first production alert send

## Self-Check: PASSED

- FOUND: guardrails/safety_logic.py
- FOUND: tests/test_safety_logic.py
- FOUND: .planning/phases/02-monitoring-pipeline/02-02-SUMMARY.md
- FOUND: 6342e60 (test RED commit)
- FOUND: e3955c5 (feat GREEN commit)
- All 59 tests pass (py -m pytest tests/ -v)

---
*Phase: 02-monitoring-pipeline*
*Completed: 2026-03-01*
