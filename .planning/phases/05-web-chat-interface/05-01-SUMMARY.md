---
phase: 05-web-chat-interface
plan: "01"
subsystem: web-chat
tags: [flask, ollama, intent-classification, tdd, scaffold]
dependency_graph:
  requires: []
  provides: [chat_server.create_app, chat_server.classify_intent, chat_server._envelope, chat_server._plain_english, chat_server._toner_dict_from_poll, templates/chat.html]
  affects: [requirements.txt, .env.example]
tech_stack:
  added: [flask==3.1.3, ollama==0.6.1]
  patterns: [Flask app factory (create_app), Ollama Client(host=...) explicit remote URL, TDD RED/GREEN cycle, module-level project imports for test patchability]
key_files:
  created: [chat_server.py, templates/chat.html, tests/test_chat_server.py]
  modified: [requirements.txt, .env.example]
decisions:
  - load_dotenv() called as first line inside create_app() — prevents test isolation issues when monkeypatch sets env before create_app() runs
  - Project imports (SNMPAdapter, read_poll_history, run_pipeline) placed at module top level so tests can patch chat_server.SNMPAdapter etc. at module scope
  - Client(host=os.getenv("OLLAMA_BASE_URL", ...)) always explicit — never relies on library's implicit OLLAMA_HOST env var (different name from project convention)
  - _plain_english() uses prefix/substring matching not exact match — suppression_reason strings are dynamic (e.g. "rate_limit: last_alert=2026-03-01T...")
  - classify_intent() catches all exceptions and returns "unknown" — Ollama unreachable is treated as unknown intent, not a server error
  - Stub handlers for all 4 action types — Plans 02 and 03 replace these with real implementations
metrics:
  duration: "~4 min"
  completed_date: "2026-03-02"
  tasks: 2
  files: 5
---

# Phase 05 Plan 01: Flask Chat Server Skeleton Summary

Flask app factory, Ollama intent classifier, JSON envelope builder, suppression reason translator, minimal HTML chat page, and test scaffold for the web chat interface.

## What Was Built

**chat_server.py** — Standalone Flask entry point with:
- `create_app()` factory returning a configured Flask app (GET `/`, POST `/chat`)
- `classify_intent(message)` — sends user message to Ollama via `Client(host=OLLAMA_BASE_URL)`, parses JSON response, validates against `VALID_ACTIONS` frozenset, returns `"unknown"` on any failure
- `_envelope(status, action, data)` — consistent JSON response wrapper with UTC ISO timestamp
- `_plain_english(reason)` — maps dynamic suppression_reason strings to human-readable text using prefix/substring matching
- `_toner_dict_from_poll(poll)` — converts `PollResult.readings` to `{color: {pct, status}}` dict using `TONER_ALERT_THRESHOLD` / `TONER_CRITICAL_THRESHOLD` env vars
- Stub handlers for `toner_status`, `alert_history`, `suppression_explanation`, `trigger_pipeline` (Plans 02/03 fill these)
- POST `/chat` routing: empty message → 400 error; unknown intent → 200 with help text; valid intent → stub response

**templates/chat.html** — Minimal functional chat UI:
- Fixed-height scrollable message history with user/response labeling
- Input field with Enter key support and Send button
- `fetch()` based JS posting JSON to `/chat`, rendering response as formatted JSON `<pre>` blocks
- Clean sans-serif, max-width 700px centered layout

**tests/test_chat_server.py** — 5 scaffold tests covering all `must_haves.truths`:
1. GET / returns 200 with `text/html` content-type
2. POST /chat with missing message key returns 400 with `status=error`
3. POST /chat with empty message returns 400 with `status=error`
4. POST /chat with unknown intent (patched classify_intent) returns 200 with `status=unknown_intent` and help text containing "toner status"
5. `classify_intent()` returns `"unknown"` when Ollama raises `ConnectionError`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | cb58d7c | chore(05-01): add Flask and ollama Phase 5 dependencies |
| Task 2 RED | 6b135de | test(05-01): add failing scaffold tests for chat_server.py |
| Task 2 GREEN | 6ba32f8 | feat(05-01): implement chat_server.py skeleton and templates/chat.html |

## Test Results

- New scaffold tests: **5/5 passed**
- Full test suite: **113 passed** (108 existing + 5 new) — no regressions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Flask and ollama packages not installed**
- **Found during:** Task 2 GREEN phase — `py -m pytest` failed with `ModuleNotFoundError: No module named 'flask'`
- **Issue:** flask and ollama were declared in requirements.txt but not yet installed in the active Python environment
- **Fix:** Ran `py -m pip install "flask>=3.1.0" "ollama>=0.6.0"` to install both packages (flask 3.1.3, ollama 0.6.1 installed)
- **Files modified:** None (environment change only)

## Self-Check: PASSED
