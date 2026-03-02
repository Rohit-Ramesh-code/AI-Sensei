# Phase 5: Web Chat Interface - Research

**Researched:** 2026-03-02
**Domain:** Flask web server, Ollama LLM intent classification, Python HTTP API
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Chat Backend — LLM Intent Classification**
- LLM backend: Ollama running LLaMA 3.1, hosted on a separate local machine (not the machine running Sentinel)
- LLM role: intent classification only — the LLM receives the raw user message and returns a structured intent (e.g., `{"action": "toner_status"}`); Python code then fetches the data and builds the JSON response
- Each query is stateless — no session history, no prior-turn context passed to the LLM
- Ollama endpoint URL configured via env var (e.g., `OLLAMA_BASE_URL`); model name via `OLLAMA_MODEL` (default: `llama3.1`)
- Unknown intent: return a help message in JSON — `{"status": "unknown_intent", "message": "I didn't understand that. Try: 'toner status', 'alert history', 'why was alert suppressed', 'run check now'"}`

**Flask — Server Setup**
- Separate entry point: `chat_server.py` (not integrated into `main.py`); runs independently from the APScheduler process
- Flask serves both: static chat HTML page at `GET /` and the JSON chat API at `POST /chat`
- Port: configurable via `CHAT_PORT` env var, default `5000`
- No authentication — local network only; acceptable for a single-engineer intranet tool

**Response Format — JSON Envelope**
- All responses use a consistent top-level envelope:
  ```json
  {
    "status": "ok | error | unknown_intent",
    "action": "toner_status | alert_history | suppression_explanation | trigger_pipeline | unknown",
    "timestamp": "<ISO 8601 UTC>",
    "data": { ... }
  }
  ```
- Toner readings in `data` are keyed by color (not an array):
  ```json
  {
    "cyan":    {"pct": 45.0, "status": "ok"},
    "magenta": {"pct": 12.0, "status": "low"},
    "yellow":  {"pct": 78.0, "status": "ok"},
    "black":   {"pct": 5.0,  "status": "critical"}
  }
  ```
- Alert history default window: last 7 days; `data` contains a list of matching log entries
- Suppression explanations: convert internal `suppression_reason` strings to plain English (e.g., `"rate_limit_exceeded"` → `"An alert was already sent in the last 24 hours."`)

**On-Demand Pipeline Trigger**
- UI waits synchronously; Flask blocks until pipeline completes before returning the JSON response
- 30-second timeout enforced server-side; returns `{"status": "error", "message": "Pipeline timed out"}` if exceeded
- `data` in a trigger response contains the full pipeline outcome: `alert_needed`, `alert_sent`, `suppression_reason` (plain-language), toner readings, and `llm_reasoning`
- On-demand runs are persisted to the JSONL history log identically to scheduled runs
- Rate limit still applies — if an alert was sent within the last 24 hours, the Policy Guard suppresses it even on manual trigger

### Claude's Discretion
- HTML/CSS design for the chat page (minimal, functional)
- Exact Ollama client library or HTTP call approach (langchain-ollama, ollama-python, or direct requests)
- Exact threshold labels for toner status (`"ok"` / `"low"` / `"critical"`) based on existing threshold env vars
- Error handling for Ollama connection failures (Ollama host unreachable)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| UI-01 | System provides a browser-accessible web chat interface (Flask or FastAPI) through which a QC engineer can interact with Sentinel conversationally | Flask 3.1.x: GET / serves HTML via render_template(); POST /chat returns JSON; app.run(port=CHAT_PORT) |
| UI-02 | QC engineer can ask for current toner status and receive a live SNMP reading per color (CMYK) in response | SNMPAdapter.poll() returns PollResult with per-color TonerReading; map to {color: {pct, status}} dict |
| UI-03 | QC engineer can query alert history ("What alerts fired this week?") and receive results drawn from the history log | read_poll_history() returns full JSONL list; filter by timestamp >= now - 7 days; return matching entries |
| UI-04 | QC engineer can ask why an alert was suppressed and receive a plain-language explanation of the Policy Guard's decision | read_poll_history() includes suppression_reason field; map internal codes to plain English strings |
| UI-05 | QC engineer can manually trigger the monitoring pipeline on-demand via the chat interface, bypassing the hourly schedule | run_pipeline() is importable from agents/supervisor.py; wrap with ThreadPoolExecutor(timeout=30) for cross-platform timeout |
</phase_requirements>

---

## Summary

Phase 5 adds a Flask-based web chat interface on top of the existing pipeline without modifying any existing code. The architecture is a new standalone entry point (`chat_server.py`) that imports and reuses three already-complete components: `SNMPAdapter.poll()`, `read_poll_history()`, and `run_pipeline()`. Flask 3.1.x (current stable: 3.1.3 as of 2026-02-18) is the locked framework and serves both the static chat HTML at `GET /` and a JSON API at `POST /chat`.

The Ollama integration uses the `ollama` Python library (current: v0.6.1) with a `Client(host=...)` pointing to the remote machine. The LLM's sole job is intent classification — it receives the raw user message and returns a JSON object with an `action` field. All data fetching is done by Python after intent is determined. Stateless requests mean no session management is needed. The `format='json'` parameter in `client.chat()` constrains Ollama to return valid JSON output for the intent response.

The most critical implementation detail is the 30-second pipeline timeout for `UI-05`. This project runs on Windows, which means `signal.alarm()` is not available. The correct cross-platform approach is `concurrent.futures.ThreadPoolExecutor` with `future.result(timeout=30)`, catching `TimeoutError`. The Flask dev server with `threaded=True` is appropriate for this single-engineer local tool — no Gunicorn/production deployment is needed for v1.

**Primary recommendation:** Build `chat_server.py` as a self-contained Flask app that calls existing project functions; use `ollama` Python library for LLM intent classification; use `ThreadPoolExecutor` for the 30-second pipeline timeout.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask | 3.1.3 (2026-02-18) | Web server: GET / HTML, POST /chat JSON | Locked by CONTEXT.md; lightweight, minimal deps, perfect for single-endpoint local tools |
| ollama (Python) | 0.6.1 (2025-11-13) | LLM client for remote Ollama instance | Official Ollama library; `Client(host=...)` supports remote host; `format='json'` enforces structured output |
| python-dotenv | >=1.0.0 | Load `.env` before project imports | Already in requirements.txt; consistent with all other entry points in the project |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| concurrent.futures (stdlib) | Python 3.9+ stdlib | 30-second pipeline timeout (Windows-compatible) | Required for UI-05 on-demand trigger; signal.alarm() not available on Windows |
| datetime (stdlib) | Python stdlib | ISO 8601 UTC timestamps in JSON envelope | Already used throughout the project |
| logging (stdlib) | Python stdlib | Consistent log format matching existing modules | All existing modules use it |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ollama Python library | `requests` direct HTTP to Ollama REST API | Direct HTTP works but requires manual response parsing; ollama library provides typed response objects and handles host resolution |
| ollama Python library | `langchain-ollama` | langchain-ollama is heavier; CONTEXT.md marks this as Claude's discretion; ollama library is lighter and purpose-built |
| Flask `render_template()` | `render_template_string()` | render_template_string embeds HTML in Python — messy for anything beyond a few lines; render_template() with a `templates/` folder is cleaner and maintainable |
| ThreadPoolExecutor timeout | `signal.alarm()` context manager | signal.alarm() is Unix-only — NOT available on Windows (project OS); ThreadPoolExecutor.result(timeout=30) is the correct cross-platform approach |

**Installation:**
```bash
pip install flask>=3.1.0 ollama>=0.6.0
```

---

## Architecture Patterns

### Recommended Project Structure

```
chat_server.py            # New standalone Flask entry point
templates/
└── chat.html             # Minimal chat HTML page (served at GET /)
tests/
└── test_chat_server.py   # Flask test client tests for all 4 intents + unknown
```

No new `adapters/` or `agents/` files are needed. `chat_server.py` imports directly from existing modules.

### Pattern 1: Flask App Factory with create_app()

**What:** Define a `create_app()` function that returns the Flask `app` instance. `chat_server.py` calls `create_app()` in `if __name__ == '__main__':`. Tests import `create_app()` and use `app.test_client()` — no live server needed.

**When to use:** Required for testability. Without `create_app()`, tests must import at module scope which triggers `load_dotenv()` side effects and makes port binding happen at import time.

**Example:**
```python
# Source: Flask official docs https://flask.palletsprojects.com/en/stable/testing/
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

def create_app() -> Flask:
    load_dotenv()  # BEFORE project imports — matches main.py pattern
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("chat.html")

    @app.post("/chat")
    def chat():
        data = request.get_json(force=True)
        message = data.get("message", "")
        # ... classify intent, fetch data, build envelope ...
        return jsonify(envelope)

    return app

if __name__ == "__main__":
    import os
    app = create_app()
    port = int(os.getenv("CHAT_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
```

### Pattern 2: Ollama Intent Classification

**What:** Send the raw user message to Ollama with a strict system prompt. Use `format='json'` to force JSON output. Parse the `action` field from the response to route to the correct data-fetching function.

**When to use:** Every `POST /chat` request before any data fetching happens.

**Example:**
```python
# Source: ollama-python README https://github.com/ollama/ollama-python
# Source: Ollama structured outputs https://ollama.com/blog/structured-outputs
import os
from ollama import Client

SYSTEM_PROMPT = """
You are an intent classifier for a printer monitoring system.
Classify the user's message into exactly one of these actions:
- toner_status: user wants current toner levels
- alert_history: user wants to see recent alerts
- suppression_explanation: user wants to know why an alert was suppressed
- trigger_pipeline: user wants to run a check now
- unknown: message doesn't match any supported action

Respond with ONLY a JSON object: {"action": "<action_name>"}
No explanation, no additional text.
""".strip()

def classify_intent(message: str) -> str:
    """Returns one of: toner_status, alert_history, suppression_explanation, trigger_pipeline, unknown"""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")

    try:
        client = Client(host=base_url)
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            format="json",
            options={"temperature": 0},  # deterministic for classification
        )
        content = response.message.content
        parsed = json.loads(content)
        action = parsed.get("action", "unknown")
        if action not in {"toner_status", "alert_history", "suppression_explanation", "trigger_pipeline"}:
            return "unknown"
        return action
    except Exception:
        # Ollama unreachable or malformed response — treat as unknown
        return "unknown"
```

### Pattern 3: 30-Second Pipeline Timeout (Windows-Compatible)

**What:** Use `concurrent.futures.ThreadPoolExecutor` to run `run_pipeline()` in a background thread with a 30-second timeout. Catch `TimeoutError` (built-in Python exception) and return the error envelope.

**When to use:** The `trigger_pipeline` action handler in `POST /chat`.

**Example:**
```python
# Source: Python docs https://docs.python.org/3/library/concurrent.futures.html
import concurrent.futures
from agents.supervisor import run_pipeline

def handle_trigger_pipeline() -> dict:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_pipeline)
        try:
            state = future.result(timeout=30)
            return {
                "alert_needed": state.get("alert_needed"),
                "alert_sent": state.get("alert_sent"),
                "suppression_reason": _plain_english(state.get("suppression_reason")),
                "toner": _toner_from_state(state),
                "llm_reasoning": state.get("llm_reasoning"),
            }
        except TimeoutError:
            return None  # caller returns error envelope
```

### Pattern 4: JSON Envelope Builder

**What:** A single helper builds the consistent top-level response envelope for all actions.

**When to use:** All responses from `POST /chat`.

**Example:**
```python
from datetime import datetime, timezone

def _envelope(status: str, action: str, data: dict) -> dict:
    return {
        "status": status,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
```

### Pattern 5: Toner Status → Color-Keyed Dict

**What:** Convert `PollResult.readings` (list of `TonerReading`) to the locked response format: `{color: {pct, status}}`. Status label derived from `toner_pct` against existing env var thresholds.

**When to use:** UI-02 toner status response AND the `data.toner` field in trigger_pipeline responses.

**Example:**
```python
import os
from state_types import PollResult

def _toner_dict_from_poll(poll: PollResult) -> dict:
    alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
    critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))
    result = {}
    for reading in poll["readings"]:
        pct = reading.get("toner_pct")
        if pct is None:
            status = reading.get("quality_flag", "unknown")
        elif pct <= critical_threshold:
            status = "critical"
        elif pct <= alert_threshold:
            status = "low"
        else:
            status = "ok"
        result[reading["color"]] = {"pct": pct, "status": status}
    return result
```

### Pattern 6: Alert History Filter

**What:** Use `read_poll_history()` and filter to entries within the last 7 days by comparing ISO 8601 timestamps.

**When to use:** UI-03 alert history handler.

**Example:**
```python
from datetime import datetime, timezone, timedelta
from adapters.persistence import read_poll_history

def _get_alert_history(days: int = 7) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    history = read_poll_history()
    results = []
    for entry in history:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts >= cutoff:
                results.append(entry)
        except ValueError:
            pass  # skip malformed entries
    return results
```

### Pattern 7: Suppression Reason Translation

**What:** Map internal `suppression_reason` strings to plain English. Find the most recent suppressed entry from history and translate its reason.

**When to use:** UI-04 suppression explanation handler.

**Example:**
```python
SUPPRESSION_MESSAGES = {
    "rate_limit_exceeded": "An alert was already sent in the last 24 hours.",
    "low_confidence": "The LLM's confidence score was too low to trigger an alert reliably.",
    "erratic_readings": "Toner readings were inconsistent — alert withheld to avoid a false alarm.",
    "data_quality_failed": "The SNMP data quality check failed (stale, null, or invalid readings).",
    "confidence_below_threshold": "The LLM's confidence score was below the minimum threshold.",
}

def _plain_english(reason: str | None) -> str | None:
    if reason is None:
        return None
    return SUPPRESSION_MESSAGES.get(reason, reason)
```

### Anti-Patterns to Avoid

- **Module-level `load_dotenv()` call in chat_server.py:** This runs at import time in tests, potentially overwriting monkeypatched env vars before test setup. Use `create_app()` factory pattern — call `load_dotenv()` inside the factory. This is the same pattern used in `main.py`.
- **Compiling `build_graph()` inside the request handler:** `build_graph()` is expensive. If `chat_server.py` must call it, compile once at `create_app()` time and reuse. But note: `run_pipeline()` already calls `build_graph()` internally — for a single-engineer local tool this is acceptable since the trigger is rare.
- **Using `signal.alarm()` for the 30-second timeout:** `signal.alarm()` is Unix-only and will raise `AttributeError` on Windows. Always use `ThreadPoolExecutor.future.result(timeout=30)`.
- **Passing the raw Ollama response string to the client without validation:** Ollama with `format='json'` usually returns valid JSON, but not always. Always wrap `json.loads()` in a try/except and fall back to `"unknown"` intent on parse failure.
- **Storing any request state in module-level globals:** Flask handles concurrent requests in threads when `threaded=True`. The intent classifier and data handlers must be stateless functions using only local variables.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Serving HTML and JSON from the same server | Custom HTTP server with `http.server` | Flask 3.1.x | Flask handles routing, content-type headers, error responses, and test client — hand-rolled HTTP misses dozens of edge cases |
| Intent classification parsing | Custom regex pattern matching on message strings | Ollama LLaMA 3.1 with `format='json'` | Natural language is ambiguous; regex breaks on phrasing variations; LLM handles "toner" vs "ink" vs "cartridge" gracefully |
| Cross-platform 30-second timeout | `signal.alarm()` SIGALRM context manager | `ThreadPoolExecutor.future.result(timeout=30)` | signal.alarm() is POSIX-only; Python docs confirm TimeoutError from future.result() is the cross-platform answer |
| JSONL history date filtering | Parse custom timestamp format | `datetime.fromisoformat()` on existing ISO 8601 strings | All PollResult timestamps are already ISO 8601 UTC from existing pipeline code |
| Toner percentage → status label | Hardcode strings like "low" | Read `TONER_ALERT_THRESHOLD` and `TONER_CRITICAL_THRESHOLD` env vars | These thresholds already exist in the project; duplicating them creates drift |

**Key insight:** All data sources already exist — this phase is a thin web layer over `SNMPAdapter`, `read_poll_history()`, and `run_pipeline()`. The implementation risk is in integration correctness, not data modeling.

---

## Common Pitfalls

### Pitfall 1: load_dotenv() Order in chat_server.py

**What goes wrong:** `chat_server.py` calls `load_dotenv()` at module top level. When pytest imports the module, `load_dotenv()` runs before test fixtures can monkeypatch env vars. The test sees real `.env` values, not mocked ones. Tests either fail (missing `.env`) or hit real hardware.

**Why it happens:** Module-level side effects run at import time, before pytest fixtures execute.

**How to avoid:** Put `load_dotenv()` inside `create_app()`. Tests call `create_app()` inside the fixture after patching env vars with `monkeypatch`. This is identical to the Phase 4 lesson documented in STATE.md: "load_dotenv() called before project imports at module top level in main.py."

**Warning signs:** Tests pass locally (real `.env` present) but fail in CI (no `.env`); monkeypatched env vars have no effect on behavior inside routes.

### Pitfall 2: Ollama Client host vs. OLLAMA_HOST env var

**What goes wrong:** The `ollama` Python library reads `OLLAMA_HOST` (not `OLLAMA_BASE_URL`) as its default env var. CONTEXT.md locked the variable name as `OLLAMA_BASE_URL`. If `chat_server.py` relies on the library's implicit env var, it will use the wrong var name.

**Why it happens:** The project defined its own env var name (`OLLAMA_BASE_URL`) before the library's convention was established.

**How to avoid:** Always construct the client explicitly: `Client(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))`. Never rely on the library's auto-detection of `OLLAMA_HOST`.

**Warning signs:** Classification calls always go to localhost even when `OLLAMA_BASE_URL` is set to a remote host.

### Pitfall 3: Ollama `format='json'` Does Not Guarantee Correct Intent Keys

**What goes wrong:** `format='json'` ensures the output is valid JSON but does not enforce the schema. The model might return `{"intent": "toner_status"}` instead of `{"action": "toner_status"}`, or `{"action": "check_toner"}` instead of `{"action": "toner_status"}`.

**Why it happens:** `format='json'` constrains syntax, not semantics. The system prompt must be precise and few-shot examples improve accuracy.

**How to avoid:** (1) Be explicit in the system prompt about exact key names and allowed values. (2) Validate the parsed `action` field against the whitelist `{"toner_status", "alert_history", "suppression_explanation", "trigger_pipeline"}`. (3) Any unrecognized value → `"unknown"`. (4) Set `options={"temperature": 0}` for deterministic outputs.

**Warning signs:** Tests pass with mock LLM but fail with real Ollama; unexpected action values appear in logs.

### Pitfall 4: 30-Second Timeout Leaves Thread Running After TimeoutError

**What goes wrong:** `ThreadPoolExecutor` with `future.result(timeout=30)` raises `TimeoutError` in the Flask request handler, allowing the Flask endpoint to return. However, the background thread running `run_pipeline()` continues executing. If it completes and persists to the JSONL log, the log entry is still written — this is actually the correct behavior per CONTEXT.md ("always persist to log"). The pitfall is if the caller expects the thread to be cancelled.

**Why it happens:** Python threads cannot be forcefully cancelled once started. `TimeoutError` only stops waiting, not the thread.

**How to avoid:** Accept this behavior — CONTEXT.md explicitly says "always persist to log." Document in code comments that the timeout stops waiting, not execution. The 30-second window is the maximum the HTTP client waits, not the maximum the pipeline runs.

**Warning signs:** Expecting `suppression_reason` to never appear after a timeout response — it can, if the thread completes after the HTTP response was already sent.

### Pitfall 5: Flask Default Dev Server Is Single-Threaded Without threaded=True

**What goes wrong:** Without `threaded=True` in `app.run()`, a blocking `POST /chat` request (e.g., the pipeline trigger taking 25 seconds) prevents any other request from being served during that time. The chat HTML page itself cannot even be reloaded.

**Why it happens:** Flask's development server defaults to single-threaded mode.

**How to avoid:** Always pass `app.run(threaded=True)` in `chat_server.py`. This is appropriate for a single-engineer local tool.

**Warning signs:** Browser appears to hang when clicking "Run check now" and then reloading the page while the check is running.

### Pitfall 6: Suppression Reason May Not Match Any Known String

**What goes wrong:** The `suppression_reason` field in `AgentState` is set by `guardrails/safety_logic.py`. If new suppression reasons are added in future phases, the `SUPPRESSION_MESSAGES` translation dict in `chat_server.py` will be incomplete. The `_plain_english()` helper returns the raw internal string for unknown reasons.

**Why it happens:** The chat server is a separate entry point with no shared constant for suppression reason strings.

**How to avoid:** Implement `_plain_english()` with a fallback: `SUPPRESSION_MESSAGES.get(reason, reason)` — unknown reasons show the raw string rather than crashing. Log unknown reason strings so they can be added to the mapping.

---

## Code Examples

Verified patterns from official sources:

### Flask App Factory (create_app pattern)

```python
# Source: Flask official docs https://flask.palletsprojects.com/en/stable/testing/
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import os

def create_app() -> Flask:
    load_dotenv()  # Inside factory — safe for test isolation
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("chat.html")

    @app.post("/chat")
    def chat():
        body = request.get_json(force=True, silent=True) or {}
        message = str(body.get("message", "")).strip()
        if not message:
            return jsonify(_envelope("error", "unknown", {"message": "Empty message"})), 400
        # ... route by intent ...
        return jsonify(result)

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("CHAT_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
```

### Flask Test Client Pattern

```python
# Source: Flask official docs https://flask.palletsprojects.com/en/stable/testing/
import pytest
from chat_server import create_app

@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mock-ollama:11434")
    monkeypatch.setenv("USE_MOCK_SNMP", "true")
    return create_app()

@pytest.fixture()
def client(app):
    return app.test_client()

def test_chat_toner_status(client, monkeypatch):
    # Patch classify_intent to return known intent without real Ollama
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "toner_status")
    response = client.post("/chat", json={"message": "What are toner levels?"})
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "ok"
    assert data["action"] == "toner_status"
    assert "cyan" in data["data"]
```

### Ollama Client with Remote Host

```python
# Source: ollama-python README https://github.com/ollama/ollama-python
# Source: Ollama structured outputs https://ollama.com/blog/structured-outputs
import json, os
from ollama import Client

def classify_intent(message: str) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    client = Client(host=base_url)  # explicit host — never rely on OLLAMA_HOST env var
    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            format="json",
            options={"temperature": 0},
        )
        parsed = json.loads(response.message.content)
        action = parsed.get("action", "unknown")
        return action if action in VALID_ACTIONS else "unknown"
    except Exception:
        return "unknown"
```

### ThreadPoolExecutor Timeout (Windows-compatible)

```python
# Source: Python stdlib docs https://docs.python.org/3/library/concurrent.futures.html
import concurrent.futures
from agents.supervisor import run_pipeline

def handle_trigger_pipeline() -> tuple[dict | None, str | None]:
    """Returns (state_dict, error_message). error_message is None on success."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_pipeline)
        try:
            state = future.result(timeout=30)
            return state, None
        except TimeoutError:
            return None, "Pipeline timed out after 30 seconds"
        except Exception as exc:
            return None, f"Pipeline error: {exc}"
```

### ISO 8601 Timestamp in Response Envelope

```python
# Source: project pattern from state_types.py and main.py
from datetime import datetime, timezone

def _envelope(status: str, action: str, data: dict) -> dict:
    return {
        "status": status,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flask `jsonify()` required for dict responses | Return dict directly from view — Flask auto-jsonifies | Flask 1.1.0 (2019) | Can return `{"key": "value"}` without wrapping in `jsonify()` — but `jsonify()` is still valid and more explicit |
| `app.run(threaded=False)` default | `threaded=True` now common for local tools | Flask 1.0+ | Single-threaded default blocks all requests during a slow handler; always pass `threaded=True` for a chat tool |
| Ollama Python library v0.1.x | v0.6.1 with typed response objects | 2024-2025 | `response.message.content` is now typed; `format='json'` and structured outputs are stable |
| `signal.alarm()` for timeouts | `ThreadPoolExecutor.future.result(timeout=N)` | Always correct on Windows | Never use signal-based timeouts in Windows projects |
| `render_template_string()` for inline HTML | `render_template('file.html')` with `templates/` folder | Flask early days | Inline HTML in Python strings is hard to maintain; use a proper template file |

**Deprecated/outdated:**
- `flask.Flask.run(use_reloader=True)` in tests: causes double-execution in test environments; `TESTING=True` in `app.config` disables the reloader automatically.
- `request.json` property (without parentheses): still works but `request.get_json(force=True, silent=True)` is safer — `force=True` ignores Content-Type header (useful when browser JS sends without exact header), `silent=True` returns `None` instead of raising `BadRequest` on malformed JSON.

---

## Open Questions

1. **Ollama LLaMA 3.1 availability on the remote machine**
   - What we know: CONTEXT.md assumes Ollama is running on a separate local machine at `OLLAMA_BASE_URL`; model name defaults to `llama3.1`
   - What's unclear: Whether `llama3.1` is already pulled on the remote host, or if `ollama pull llama3.1` needs to run first
   - Recommendation: Document in `.env.example` that `ollama pull llama3.1` must be run on the remote Ollama host before starting `chat_server.py`; handle `ConnectionError` from the client as a graceful "unknown intent" fallback

2. **`run_pipeline()` builds a fresh graph on every call**
   - What we know: `run_pipeline()` calls `build_graph()` internally (from supervisor.py); this compiles the LangGraph StateGraph each time
   - What's unclear: Performance impact on each on-demand trigger
   - Recommendation: For a single-engineer tool with rare on-demand triggers, this is acceptable. If latency becomes an issue, compile `build_graph()` once in `create_app()` and pass it to a custom pipeline wrapper — but this adds complexity not worth it for v1.

3. **suppression_reason string values from safety_logic.py**
   - What we know: STATE.md documents some suppression reason strings (`"rate_limit_exceeded"`, `"low_confidence"`, `"erratic_readings"`, `"data_quality_failed"`)
   - What's unclear: The exact canonical set of strings written by `run_policy_guard()`
   - Recommendation: Read `guardrails/safety_logic.py` before implementing `_plain_english()` to enumerate all strings; implement with a fallback dict that returns the raw string for any unknown reason.

---

## Sources

### Primary (HIGH confidence)

- Flask official docs https://flask.palletsprojects.com/en/stable/changes/ — confirmed version 3.1.3 (2026-02-18), Python 3.9+ minimum requirement
- Flask official docs https://flask.palletsprojects.com/en/stable/quickstart/ — GET/POST route patterns, jsonify(), render_template()
- Flask official docs https://flask.palletsprojects.com/en/stable/testing/ — create_app() factory pattern, app.test_client(), json= parameter for test client POST
- Python stdlib docs https://docs.python.org/3/library/concurrent.futures.html — ThreadPoolExecutor, future.result(timeout=N), TimeoutError on timeout
- ollama-python GitHub README https://github.com/ollama/ollama-python — confirmed v0.6.1, Client(host=...) usage, format='json' parameter, response.message.content
- Ollama structured outputs blog https://ollama.com/blog/structured-outputs — format parameter accepts 'json' string or JSON schema dict; temperature=0 recommendation

### Secondary (MEDIUM confidence)

- deepwiki.com ollama-python configuration https://deepwiki.com/ollama/ollama-python/5.2-configuration-and-options — confirmed OLLAMA_HOST (not OLLAMA_BASE_URL) is the library's default env var; Client(host=...) explicit override confirmed
- Python signal docs https://docs.python.org/3/library/signal.html — signal.alarm() is Unix-only; confirmed via WebSearch cross-reference with Windows compatibility requirement

### Tertiary (LOW confidence)

- WebSearch: "Flask threaded=True single engineer local tool" — confirmed `threaded=True` is acceptable for local single-user tools; not from official Flask docs specifically

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Flask version confirmed from PyPI/changelog (2026-02-18 release); ollama version confirmed from GitHub releases; Python stdlib concurrent.futures from official docs
- Architecture: HIGH — create_app() factory pattern from Flask official testing docs; Ollama Client usage from official README; ThreadPoolExecutor timeout from Python stdlib docs
- Pitfalls: HIGH for load_dotenv ordering (documented pattern from Phase 4 STATE.md decisions), Windows signal limitation (confirmed by Python signal docs), Ollama env var name (confirmed by deepwiki source). MEDIUM for LLM output variability (known LLM behavior, no official source needed)

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (Flask and ollama-python are stable; concurrent.futures is stdlib — no expiry)
