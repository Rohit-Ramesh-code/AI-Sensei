---
phase: 01-foundation
verified: 2026-03-01T11:00:00Z
status: human_needed
score: 17/17 must-haves verified (automated); 1 item needs human
re_verification: false
human_verification:
  - test: "Send a real alert email through Exchange"
    expected: "Email arrives in ALERT_RECIPIENT inbox within 30 seconds with subject '[Sentinel Test] EWS Adapter Verification'"
    why_human: "Cannot verify inbox delivery programmatically; requires live Exchange credentials (EWS_SERVER, EWS_USERNAME, EWS_PASSWORD) and physical inbox access. Task 2 of Plan 01-03 is a checkpoint:human-verify gate that was explicitly deferred."
---

# Phase 1: Foundation Verification Report

**Phase Goal:** Establish the complete data-collection and communication foundation — SNMP adapter pulling live toner data, EWS adapter sending alert emails, and a persistence layer logging every poll result.
**Verified:** 2026-03-01T11:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|---------|
| 1  | Running SNMP adapter in mock mode returns a PollResult with 4 TonerReading entries (black, cyan, magenta, yellow) | VERIFIED | `test_mock_poll_returns_four_readings` passes; smoke test confirmed 4 readings |
| 2  | Sentinel values -2 and -3 in mock fixture produce QualityFlag.UNKNOWN and QualityFlag.BELOW_LOW_THRESHOLD (not raw integers) | VERIFIED | `test_classify_minus2_returns_unknown`, `test_classify_minus3_returns_below_low_threshold`, `test_no_raw_sentinel_in_quality_flag` all pass |
| 3  | A TonerReading with a valid level and max_capacity has data_quality_ok=True and a computed toner_pct between 0 and 100 | VERIFIED | `test_classify_valid_value_returns_ok_and_percentage` passes; smoke test shows black=85.0%, cyan=42.0% |
| 4  | A TonerReading with a sentinel level has data_quality_ok=False and toner_pct=None | VERIFIED | `test_mock_fixture_sentinels_produce_bad_quality` passes; magenta/yellow have pct=None |
| 5  | state_types.py can be imported by downstream agents without error | VERIFIED | `python -c "from state_types import QualityFlag, TonerReading, PollResult, AgentState"` exits 0 |
| 6  | QualityFlag enum values are JSON-serializable strings (str mixin) | VERIFIED | `test_quality_flag_json_serializable` passes; `json.dumps({"flag": QualityFlag.OK})` returns `{"flag": "ok"}` |
| 7  | append_poll_result() appends exactly one JSON line per call to logs/printer_history.jsonl | VERIFIED | `test_append_adds_one_line_per_call` passes; mode='a' confirmed in source |
| 8  | The log file is created on first write if it does not exist (parents created too) | VERIFIED | `test_append_creates_file_if_not_exist` and `test_parent_directory_created_if_missing` pass |
| 9  | Re-running append_poll_result() multiple times produces multiple lines — file is never truncated | VERIFIED | `test_append_never_truncates_existing_content` passes; `jsonlines.open(mode="a")` confirmed in source |
| 10 | Each log line is valid JSON and contains all required fields | VERIFIED | `test_each_line_is_valid_json` and `test_appended_line_contains_required_fields` pass |
| 11 | Both valid and invalid poll results are logged (no filtering) | VERIFIED | `test_failed_poll_is_logged_without_filtering` passes |
| 12 | In mock mode, EWSAdapter.send_alert() logs the email and does not raise | VERIFIED | `test_send_alert_mock_returns_without_error` and `test_mock_mode_logs_email_content` pass; smoke test confirmed log output |
| 13 | EWSAdapter.send_alert() accepts arbitrary recipient, subject, body (not hardcoded) | VERIFIED | `test_send_alert_accepts_arbitrary_strings` passes; parameters flow through to logger/Message |
| 14 | Auth type is configurable via EWS_AUTH_TYPE env var (NTLM default) | VERIFIED | `test_auth_type_defaults_to_ntlm` and `test_auth_type_read_from_env` pass |
| 15 | EWSAdapter fails fast with clear ValueError when Exchange server is missing in non-mock mode | VERIFIED | `test_missing_ews_server_raises_value_error` passes; error message explicitly mentions EWS_SERVER |
| 16 | requirements.txt lists all Phase 1 dependencies with pinned/minimum versions | VERIFIED | File contains: pysnmp==7.1.22, exchangelib>=5.6.0, jsonlines>=4.0.0, python-dotenv>=1.0.0, langgraph>=0.2.0, langchain-core>=0.2.0 |
| 17 | .env.example documents all required env vars including USE_MOCK_SNMP and USE_MOCK_EWS | VERIFIED | File contains: SNMP_HOST, SNMP_COMMUNITY, EWS_SERVER, EWS_USERNAME, EWS_PASSWORD, EWS_AUTH_TYPE, ALERT_RECIPIENT, LLM_CONFIDENCE_THRESHOLD, TONER_ALERT_THRESHOLD, USE_MOCK_SNMP, USE_MOCK_EWS |

**Score:** 17/17 truths verified (automated)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `state_types.py` | TypedDict state definitions: TonerReading, PollResult, AgentState; QualityFlag enum | VERIFIED | 124 lines; exports QualityFlag (8 members, str+Enum mixin), TonerReading, PollResult, AgentState with Annotated decision_log reducer |
| `adapters/snmp_adapter.py` | SNMPAdapter class with poll() method; mock mode via USE_MOCK_SNMP env flag | VERIFIED | 376 lines; classify_snmp_value() pure function; MOCK_FIXTURE; SNMPAdapter with mock + asyncio.run() real path |
| `adapters/persistence.py` | append_poll_result() and read_poll_history() for JSONL log | VERIFIED | 86 lines; append uses mode='a' with jsonlines; read returns [] on missing file; log_path injection for test isolation |
| `logs/.gitkeep` | Ensures logs/ directory is tracked in git | VERIFIED | File exists (0 bytes); confirmed tracked by `git ls-files logs/` |
| `requirements.txt` | Pinned dependencies for full Phase 1 stack | VERIFIED | Lists pysnmp, exchangelib, jsonlines, python-dotenv, pytest, langgraph, langchain-core |
| `.env.example` | Template for all required environment variables | VERIFIED | Documents all 9 env vars with inline comments |
| `adapters/ews_scraper.py` | EWSAdapter class with send_alert() method; mock mode via USE_MOCK_EWS env flag | VERIFIED | 201 lines; lazy exchangelib import; Account-once pattern; configurable auth_type |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `adapters/snmp_adapter.py` | `state_types.py` | `from state_types import QualityFlag, PollResult, TonerReading` | WIRED | Line 39 of snmp_adapter.py; all three types actively used |
| `adapters/snmp_adapter.py` | prtMarkerSuppliesDescription OID | dynamic color->index map built via walk in `_poll_real_async()` | WIRED | Lines 171-192; iterates indices 1-8, maps color strings to OID indices dynamically |
| `adapters/persistence.py` | `logs/printer_history.jsonl` | `jsonlines.open(str(log_path), mode="a")` | WIRED | Line 59; mode='a' is explicit and commented as critical |
| `adapters/persistence.py` | `state_types.PollResult` | type annotation on append_poll_result parameter | WIRED | Line 42; `from state_types import PollResult` under TYPE_CHECKING; runtime duck-typed |
| `adapters/ews_scraper.py` | Exchange server (EWS endpoint) | `exchangelib Account.send(Message(...))` | WIRED (production); MOCK (mock mode) | Production path: Message(...).send() at line 195; mock path: logger.info at line 178 |
| `adapters/ews_scraper.py` | environment variables | `os.getenv` for EWS_SERVER, EWS_USERNAME, EWS_PASSWORD, EWS_AUTH_TYPE, USE_MOCK_EWS | WIRED | Lines 64, 70, 84, 93, 94; all five env vars read via os.getenv |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| SNMP-01 | 01-01 | System polls Lexmark XC2235 for toner % per color (CMYK) via SNMP on a scheduled interval | SATISFIED | SNMPAdapter.poll() returns PollResult with 4 CMYK TonerReadings; mock mode verified by 6 tests; real asyncio path implemented |
| SNMP-02 | 01-01 | SNMP adapter detects and handles Lexmark sentinel values (-2: unknown, -3: below low threshold), converts to structured quality flags | SATISFIED | classify_snmp_value() maps -2 to QualityFlag.UNKNOWN, -3 to QualityFlag.BELOW_LOW_THRESHOLD; 8 sentinel classification tests pass |
| SNMP-03 | 01-01 | SNMP adapter validates each reading for staleness, null values, and out-of-range results, setting data_quality_ok flag | SATISFIED | classify_snmp_value() handles NULL_VALUE (None), OUT_OF_RANGE, max_capacity sentinel; data_quality_ok=False on any non-OK flag; 8 classification tests + 6 mock poll tests pass |
| SNMP-04 | 01-02 | Every poll result (valid or invalid) is persisted to a JSON Lines history log with timestamp and data quality metadata | SATISFIED | append_poll_result() always logs regardless of overall_quality_ok; test_failed_poll_is_logged_without_filtering confirms no filtering; 10 persistence tests pass |
| ALRT-01 | 01-03 | Communicator Agent sends alert emails via Microsoft Exchange Web Services (EWS) using a configured service account | PARTIALLY SATISFIED | EWSAdapter implemented with mock mode (10 tests pass, mock confirmed working); live Exchange delivery deferred as explicit human checkpoint — requires physical inbox verification |

**Orphaned requirements check:** REQUIREMENTS.md traceability table maps SNMP-01, SNMP-02, SNMP-03, SNMP-04, ALRT-01 to Phase 1 — exactly matches the set declared across all three plans. No orphaned requirements.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `adapters/snmp_adapter.py` | 218, 229 | `pass` in exception handler | Info | Legitimate: silently absorbs `ValueError`/`TypeError` from `int()` conversion on SNMP varbind values; raw_level defaults to None and raw_max defaults to -2 sentinel — both handled correctly by classify_snmp_value() |
| `adapters/persistence.py` | 82 | `return []` | Info | Legitimate: correct early-return for missing file case; tested by `test_read_returns_empty_list_if_file_missing` |

No blockers or warnings. Both flagged patterns are intentional and correct.

---

## Human Verification Required

### 1. Live Exchange Email Delivery (ALRT-01 — Task 2 of Plan 01-03)

**Test:** Configure `.env` with real Exchange credentials (`EWS_SERVER`, `EWS_USERNAME`, `EWS_PASSWORD`, `EWS_AUTH_TYPE`, `ALERT_RECIPIENT`), then run:

```python
from dotenv import load_dotenv; load_dotenv()
from adapters.ews_scraper import EWSAdapter
import os
adapter = EWSAdapter()
adapter.send_alert(
    recipient=os.getenv('ALERT_RECIPIENT'),
    subject='[Sentinel Test] EWS Adapter Verification',
    body='This is a test email from Project Sentinel Phase 1. If received, EWS is working correctly.'
)
print('Email sent successfully')
```

**Expected:** Email arrives within ~30 seconds in the ALERT_RECIPIENT inbox with the subject `[Sentinel Test] EWS Adapter Verification`.

**Why human:** Inbox receipt cannot be verified programmatically. Requires live Exchange server access, valid service account credentials, and physical inbox inspection. The plan explicitly marks this as `checkpoint:human-verify` with gate `blocking`. Common failure modes to check: 401 Unauthorized (wrong `EWS_AUTH_TYPE` — try NTLM vs BASIC), connection refused (wrong `EWS_SERVER` URL or EWS not enabled on server).

**Note:** This checkpoint was explicitly deferred in the 01-03-SUMMARY. ALRT-01 is partially satisfied — the adapter code is implemented and unit-tested, but the live delivery path has not been confirmed end-to-end.

---

## Test Suite Summary

All 42 automated tests pass in 0.89s:

| Module | Tests | Result |
|--------|-------|--------|
| `tests/test_state_types.py` | 8 | PASSED |
| `tests/test_snmp_adapter.py` | 14 | PASSED |
| `tests/test_persistence.py` | 10 | PASSED |
| `tests/test_ews_adapter.py` | 10 | PASSED |
| **Total** | **42** | **42 PASSED** |

---

## Commit Verification

All 9 task commits documented in the SUMMARYs are confirmed present in git history:

| Commit | Description | Verified |
|--------|-------------|---------|
| `2301419` | test(01-01): state_types failing tests | FOUND |
| `fa395f1` | feat(01-01): state_types.py implementation | FOUND |
| `6abe352` | test(01-01): snmp_adapter failing tests | FOUND |
| `f0fdd62` | feat(01-01): SNMPAdapter implementation | FOUND |
| `3247022` | test(01-02): persistence failing tests | FOUND |
| `d0f326e` | feat(01-02): JSONL persistence module | FOUND |
| `64ac88d` | feat(01-02): requirements.txt, .env.example, logs/.gitkeep | FOUND |
| `66161de` | test(01-03): EWS adapter failing tests | FOUND |
| `53858a5` | feat(01-03): EWSAdapter implementation | FOUND |

---

## Deviations Noted

1. **pysnmp-sync-adapter not usable** (documented in 01-01-SUMMARY): The plan specified `from pysnmp_sync_adapter import get_cmd_sync` for the real SNMP path. Implementation uses `asyncio.run(_poll_real_async())` instead — functionally equivalent and fully documented as an auto-fix. Mock mode (all tests) is unaffected.

2. **printer_history.json exists in logs/** (unexpected): A file `logs/printer_history.json` is present in the working directory (not the `.jsonl` file the persistence layer writes). This appears to be a pre-existing fixture or leftover file. It is not committed (`.gitignore` excludes `logs/printer_history.json`) and does not affect operation.

3. **Plan execution order** (cosmetic): Plan 01-03 (EWS) was executed before Plan 01-02 (persistence), despite 01-03 being Wave 1 and 01-02 being Wave 2. The 01-03-SUMMARY contains an erroneous note "Plan 01-02 (SNMP adapter) still needs to be executed" — this was written before 01-02 ran and refers to the persistence plan, not the SNMP adapter. No code impact.

---

## Summary

Phase 1 has achieved its data-collection and communication foundation goal. All three adapter modules are substantive, tested, and wired correctly:

- **SNMP adapter**: Classifies all RFC 3805 sentinel values, returns structured PollResult, never raises.
- **Persistence layer**: Appends every poll result as a JSONL line in mode='a'; read_poll_history() enables Phase 2 history analysis.
- **EWS adapter**: Mock mode works without Exchange; production mode builds Account once and supports configurable NTLM/BASIC auth.

The single outstanding item is human confirmation of live Exchange email delivery (ALRT-01 Task 2 checkpoint). All other requirements are fully satisfied by 42 passing tests.

---

_Verified: 2026-03-01T11:00:00Z_
_Verifier: Claude (gsd-verifier)_
