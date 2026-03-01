---
phase: 01-foundation
plan: "02"
subsystem: database
tags: [jsonlines, jsonl, persistence, logging, requirements, dotenv]

# Dependency graph
requires:
  - phase: 01-01
    provides: PollResult and TonerReading TypedDicts that persistence.py logs

provides:
  - append_poll_result() appends PollResult dicts to JSONL log in mode='a' (never truncates)
  - read_poll_history() reads full log as list; returns [] if file missing
  - logs/.gitkeep tracks logs/ directory in git
  - requirements.txt with full Phase 1 dependency stack (pinned/minimum versions)
  - .env.example documenting all required env vars including mock flags

affects:
  - 01-03 (EWS adapter — will use requirements.txt)
  - Phase 2 policy guard (reads poll history via read_poll_history)
  - Phase 2 analyst (reads poll history for trend analysis)

# Tech tracking
tech-stack:
  added:
    - jsonlines==4.0.0 (JSON Lines read/write with append mode)
    - pysnmp-sync-adapter>=1.0.8 (in requirements.txt; env build isolation issue noted)
    - exchangelib>=5.6.0 (in requirements.txt)
    - langgraph>=0.2.0 (in requirements.txt for Phase 2)
    - langchain-core>=0.2.0 (in requirements.txt for Phase 2)
  patterns:
    - JSONL append-only log pattern (one JSON object per line, never truncate)
    - log_path parameter injection for test isolation (avoids global patching)
    - Lazy QualityFlag serialization (str Enum serializes as plain string without custom encoder)

key-files:
  created:
    - adapters/persistence.py
    - tests/test_persistence.py
    - logs/.gitkeep
    - .env.example
  modified:
    - requirements.txt
    - .gitignore

key-decisions:
  - "jsonlines library used for JSONL I/O — simpler than manual json.dumps per line"
  - "log_path parameter with default enables test isolation without patching globals"
  - "mode='a' is invariant — code comment reinforces this for future maintainers"
  - ".gitignore updated to ignore only logs/*.jsonl and logs/*.json instead of entire logs/"
  - "pytest added to requirements.txt as Phase 1 test dependency"

patterns-established:
  - "Adapter-level persistence: each adapter is responsible for logging its own output"
  - "Temp path injection pattern: injectable path parameter with project-root default"
  - "JSONL over JSON array: append-safe, streaming-safe, no file rewrite on each poll"

requirements-completed: [SNMP-04]

# Metrics
duration: 15min
completed: 2026-03-01
---

# Phase 01 Plan 02: Persistence Layer Summary

**JSONL persistence layer with append_poll_result()/read_poll_history() using jsonlines in mode='a', plus pinned requirements.txt and .env.example documenting all env vars including USE_MOCK_SNMP and USE_MOCK_EWS**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-01T15:25:03Z
- **Completed:** 2026-03-01T15:40:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- JSONL persistence module with append_poll_result() (always mode='a') and read_poll_history() (returns [] if file missing)
- 10 TDD tests covering file creation, append-only behavior, JSON validity, required fields, no-filter-on-failure, round-trip read, missing file, no truncation, parent dir creation, and enum string serialization
- Full Phase 1 requirements.txt with pinned/minimum versions for all adapters, LangGraph, and testing
- .env.example documenting all 9 env vars including USE_MOCK_SNMP and USE_MOCK_EWS for mock mode
- logs/.gitkeep to track logs/ directory in git while runtime .jsonl files remain ignored

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing persistence tests** - `3247022` (test)
2. **Task 1 (GREEN): JSONL persistence module** - `d0f326e` (feat)
3. **Task 2: requirements.txt, .env.example, logs/.gitkeep** - `64ac88d` (feat)

_Note: TDD task has two commits — test (RED) then implementation (GREEN)_

## Files Created/Modified
- `adapters/persistence.py` - append_poll_result() and read_poll_history() for JSONL log
- `tests/test_persistence.py` - 10 tests covering all persistence behaviors (uses tmp_path injection)
- `logs/.gitkeep` - Tracks logs/ directory in git; runtime .jsonl files are gitignored
- `.env.example` - Template for all required environment variables with inline docs
- `requirements.txt` - Full Phase 1 dependency stack with pinned/minimum versions
- `.gitignore` - Updated: logs/*.jsonl and logs/*.json ignored; logs/ directory itself is no longer blanket-ignored

## Decisions Made
- Used jsonlines library for clean JSONL I/O with context manager support — avoids manual json.dumps/newline handling
- log_path parameter with project-root default enables test isolation without patching globals (cleaner than monkeypatching)
- mode='a' is reinforced with a code comment explaining why 'w' would be catastrophic
- Updated .gitignore from blanket `logs/` to specific `logs/printer_history.jsonl` and `logs/printer_history.json` to allow `.gitkeep` to be tracked
- Added pytest to requirements.txt as an explicit Phase 1 dependency
- pysnmp-sync-adapter listed in requirements.txt despite known build-isolation issue (noted in STATE.md from Plan 01-01)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed stray `=4.0.0` file created by shell redirection error**
- **Found during:** Task 2 (verifying git status)
- **Issue:** An earlier pip install command using `>=4.0.0` syntax caused the shell to create a file named `=4.0.0` via output redirection (git reported it as untracked)
- **Fix:** Removed the stray file with `rm =4.0.0`
- **Files modified:** None (file deleted, not committed)
- **Verification:** git status no longer showed stray file
- **Committed in:** 64ac88d (included in Task 2 commit as clean working state)

**2. [Rule 3 - Blocking] Updated .gitignore to allow logs/.gitkeep to be tracked**
- **Found during:** Task 2 (git status after creating logs/.gitkeep)
- **Issue:** Original .gitignore had `logs/` (entire directory ignored), preventing `logs/.gitkeep` from being tracked
- **Fix:** Changed `logs/` to `logs/printer_history.jsonl` and `logs/printer_history.json` in .gitignore
- **Files modified:** .gitignore
- **Verification:** git status showed logs/.gitkeep as a new trackable file
- **Committed in:** 64ac88d (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes required for correct git tracking of the logs/ directory. No scope creep.

## Issues Encountered
- pysnmp-sync-adapter dry-run install fails with `No module named 'pkg_resources'` in pip build isolation (same issue as Plan 01-01). This is an environment-specific build isolation issue, not a requirements.txt problem. The package remains listed in requirements.txt for documentation; the SNMPAdapter uses asyncio.run() directly as documented in STATE.md.

## User Setup Required
None - no external service configuration required for this plan.

## Next Phase Readiness
- Persistence layer ready for Plan 01-03 (EWS adapter) and Phase 2 policy guard
- read_poll_history() provides the historical data Phase 2 analyst needs for trend analysis
- requirements.txt and .env.example provide the scaffolding for full project setup
- All 10 persistence tests pass; combined with Plan 01-01's 22 tests, Phase 1 has 32 tests

---
*Phase: 01-foundation*
*Completed: 2026-03-01*

## Self-Check: PASSED

All created files confirmed present:
- adapters/persistence.py: FOUND
- tests/test_persistence.py: FOUND
- logs/.gitkeep: FOUND
- .env.example: FOUND
- requirements.txt: FOUND
- .planning/phases/01-foundation/01-02-SUMMARY.md: FOUND

All task commits confirmed:
- 3247022 (test RED): FOUND
- d0f326e (feat GREEN): FOUND
- 64ac88d (feat Task 2): FOUND
