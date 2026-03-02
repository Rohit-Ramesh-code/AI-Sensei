# Phase 5: Web Chat Interface - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

A QC engineer opens a browser to a local URL and queries Sentinel conversationally. The interface handles four interactions: current toner status (live SNMP read), alert history (last 7 days from log), suppression explanation (plain-language Policy Guard decision), and on-demand pipeline trigger. Scheduling, alerting, and analysis logic remain in the existing pipeline — this phase adds a web layer on top.

</domain>

<decisions>
## Implementation Decisions

### Chat Backend — LLM Intent Classification
- LLM backend: Ollama running LLaMA 3.1, hosted on a separate local machine (not the machine running Sentinel)
- LLM role: intent classification only — the LLM receives the raw user message and returns a structured intent (e.g., `{"action": "toner_status"}`); Python code then fetches the data and builds the JSON response
- Each query is stateless — no session history, no prior-turn context passed to the LLM
- Ollama endpoint URL configured via env var (e.g., `OLLAMA_BASE_URL`); model name via `OLLAMA_MODEL` (default: `llama3.1`)
- Unknown intent: return a help message in JSON — `{"status": "unknown_intent", "message": "I didn't understand that. Try: 'toner status', 'alert history', 'why was alert suppressed', 'run check now'"}`

### Flask — Server Setup
- Separate entry point: `chat_server.py` (not integrated into `main.py`); runs independently from the APScheduler process
- Flask serves both: static chat HTML page at `GET /` and the JSON chat API at `POST /chat`
- Port: configurable via `CHAT_PORT` env var, default `5000`
- No authentication — local network only; acceptable for a single-engineer intranet tool

### Response Format — JSON Envelope
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

### On-Demand Pipeline Trigger
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

</decisions>

<specifics>
## Specific Ideas

- No specific UI reference — minimal functional HTML is fine; the QC engineer needs utility, not polish
- The JSON-only response format was an explicit requirement — the chat HTML page sends POST requests and renders the JSON inline or in a code block

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `adapters/persistence.py` → `read_poll_history(log_path)`: reads full JSONL history as a list of PollResult dicts — use this directly to serve history queries and suppression lookups
- `agents/supervisor.py` → `run_pipeline(poll_result=None)`: callable function that runs the full LangGraph pipeline and returns a final `AgentState` — use this directly for on-demand trigger endpoint
- `adapters/snmp_adapter.py` → `SNMPAdapter(host, community).poll()`: returns a `PollResult` with per-color `TonerReading` entries — use this for live toner status queries
- `state_types.py` → `AgentState`, `PollResult`, `TonerReading`, `QualityFlag`: all data shapes are defined and importable

### Established Patterns
- Env vars loaded via `python-dotenv` in `main.py`; `chat_server.py` should call `load_dotenv()` before any project imports (same pattern)
- Mock mode: `USE_MOCK_SNMP=true` env var bypasses real hardware — `chat_server.py` should respect this for local dev/testing
- All external configuration via env vars (consistent with `SNMP_HOST`, `SMTP_PORT`, etc.)

### Integration Points
- `chat_server.py` imports `run_pipeline` from `agents/supervisor.py` — connects to the full LangGraph graph
- `chat_server.py` imports `read_poll_history` from `adapters/persistence.py` — connects to the JSONL log
- `chat_server.py` imports `SNMPAdapter` from `adapters/snmp_adapter.py` — connects to SNMP hardware
- New env vars needed: `CHAT_PORT`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-web-chat-interface*
*Context gathered: 2026-03-02*
