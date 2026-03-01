---
phase: 01-foundation
plan: "03"
subsystem: adapter
tags: [ews, exchangelib, email, mock, ntlm, exchange]

# Dependency graph
requires: []
provides:
  - "EWSAdapter class in adapters/ews_scraper.py with send_alert() method"
  - "Mock mode for offline development (no Exchange server required)"
  - "Configurable auth type (NTLM/BASIC) via EWS_AUTH_TYPE env var"
  - "10 passing unit tests covering all mock behaviours and error paths"
affects: [agents/communicator.py, agents/supervisor.py]

# Tech tracking
tech-stack:
  added: [exchangelib, pytest, python-dotenv]
  patterns:
    - "Lazy import pattern: exchangelib imported only in production code path, allowing mock mode without the library installed"
    - "Mock-first adapter: env var or kwarg activates mock; tests never require live services"
    - "Account-once pattern: exchangelib Account built once in __init__, not per send_alert call"

key-files:
  created:
    - adapters/ews_scraper.py
    - tests/__init__.py
    - tests/test_ews_adapter.py
  modified:
    - requirements.txt
    - .gitignore

key-decisions:
  - "exchangelib is imported lazily (only in the production code path) so the module can be imported in mock mode without the library installed"
  - "Account is constructed once in __init__ to avoid repeated TLS handshakes on every send_alert() call"
  - "auth_type stored as a string attribute on the adapter (not as the exchangelib constant) so tests can assert on it without importing exchangelib"
  - "MSAL auth type raises NotImplementedError in v1 scope (out of scope per CLAUDE.md)"
  - "Live Exchange verification is a human checkpoint — deferred to when Exchange credentials are available"

patterns-established:
  - "Mock-first adapters: all external adapters must support mock mode via use_mock kwarg and USE_MOCK_<ADAPTER> env var"
  - "Lazy external imports: expensive or unavailable libraries imported only on the live code path"

requirements-completed: [ALRT-01]

# Metrics
duration: 5min
completed: 2026-03-01
---

# Phase 1 Plan 03: EWS Adapter Summary

**EWSAdapter class wrapping exchangelib for Exchange email alerts, with lazy import and mock mode — 10 unit tests pass without a live server**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-01T02:16:47Z
- **Completed:** 2026-03-01T02:21:56Z
- **Tasks:** 1 of 2 (Task 2 is checkpoint:human-verify — awaiting user action)
- **Files modified:** 5

## Accomplishments
- EWSAdapter class implemented with send_alert(recipient, subject, body) API
- Mock mode activated by use_mock=True kwarg or USE_MOCK_EWS=true env var; logs email to Python logger, never touches exchangelib
- Production mode builds exchangelib Account once in __init__, then reuses it per send_alert call to avoid repeated TLS handshakes
- Auth type (NTLM/BASIC) configurable via EWS_AUTH_TYPE env var, defaults to NTLM
- Clear ValueError raised when EWS_SERVER is missing in production mode
- Lazy import of exchangelib means mock mode works even without the library installed
- 10 unit tests written and passing (TDD RED → GREEN cycle)
- pytest and .venv set up for the project; .gitignore updated

## Task Commits

Each task was committed atomically following TDD RED-GREEN cycle:

1. **Task 1 RED: Failing tests for EWS adapter** - `66161de` (test)
2. **Task 1 GREEN: EWSAdapter implementation** - `53858a5` (feat)

_Task 2 is checkpoint:human-verify — no commit yet_

## Files Created/Modified
- `adapters/ews_scraper.py` - EWSAdapter class with send_alert() and mock mode
- `tests/__init__.py` - Makes tests/ a Python package
- `tests/test_ews_adapter.py` - 10 unit tests covering mock mode and error paths
- `requirements.txt` - Added exchangelib, python-dotenv, pytest
- `.gitignore` - Added .venv/ and .pytest_cache/

## Decisions Made
- Lazy import of exchangelib (only in production code path) allows mock mode to work without the library installed in CI/development environments
- Account built once in `__init__` — the plan explicitly called this out as a critical anti-pattern to avoid
- MSAL auth type deferred (NotImplementedError) — out of scope for v1 per CLAUDE.md
- auth_type stored as a string on the adapter rather than as the exchangelib constant, making it testable without importing exchangelib

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Set up Python venv and install pytest**
- **Found during:** Task 1 RED phase (test infrastructure check)
- **Issue:** No tests/ directory existed; pytest not installed; MSYS2 Python is externally managed (cannot pip install globally)
- **Fix:** Created `.venv/` with `python -m venv .venv`, installed pytest inside venv, created `tests/__init__.py`
- **Files modified:** .gitignore (added .venv/, .pytest_cache/)
- **Verification:** `pytest --version` returns pytest 9.0.2
- **Committed in:** `53858a5` (feat commit for Task 1)

---

**Total deviations:** 1 auto-fixed (1 blocking - test infrastructure setup)
**Impact on plan:** Necessary prerequisite for all testing. No scope creep.

## Issues Encountered
- MSYS2 Python is externally managed — global pip install blocked. Resolved by creating a project-local virtualenv (`.venv/`). All subsequent test runs use `.venv/bin/python -m pytest`.

## User Setup Required

**External services require manual configuration before live Exchange email can be tested (Task 2 checkpoint).**

Set these environment variables in `.env`:

| Variable | Description | Source |
|----------|-------------|--------|
| `EWS_SERVER` | Exchange EWS endpoint URL | Ask IT (e.g., `https://mail.company.com/EWS/Exchange.asmx`) |
| `EWS_USERNAME` | Service account email | IT / Exchange Admin |
| `EWS_PASSWORD` | Service account password | IT / Exchange Admin |
| `EWS_AUTH_TYPE` | Auth type (NTLM or BASIC) | Ask IT — NTLM for on-prem Exchange 2016 |
| `ALERT_RECIPIENT` | Admin email to receive toner alerts | Your choice |

Verify with:
```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from adapters.ews_scraper import EWSAdapter
import os
adapter = EWSAdapter()
adapter.send_alert(
    recipient=os.getenv('ALERT_RECIPIENT'),
    subject='[Sentinel Test] EWS Adapter Verification',
    body='This is a test email from Project Sentinel Phase 1.'
)
print('Email sent successfully')
"
```

## Next Phase Readiness
- EWSAdapter is ready for use by `agents/communicator.py` (Phase 2)
- Mock mode means communicator.py can be developed and tested without Exchange access
- Live Exchange test pending human verification (Task 2 checkpoint)
- Plan 01-02 (SNMP adapter) still needs to be executed — check plan ordering

---
*Phase: 01-foundation*
*Completed: 2026-03-01*
