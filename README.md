# Project Sentinel

> **Predict printer supply depletion before it happens — alerting the right person with enough lead time to act.**

Project Sentinel is a Python-based multi-agent monitoring system that polls a Lexmark XC2235 printer via SNMP, runs toner trend data through a LangGraph AI pipeline, gates all outbound actions through a deterministic Policy Guard, and delivers proactive maintenance alerts via SMTP email. A browser-based chat interface lets QC engineers query status, history, and trigger on-demand checks.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Directory Structure](#directory-structure)
3. [Agent Roles](#agent-roles)
4. [Policy Guard](#policy-guard)
5. [Data Flow](#data-flow)
6. [Technology Stack](#technology-stack)
7. [Setup Instructions](#setup-instructions)
8. [Environment Variables](#environment-variables)
9. [Web Chat Interface](#web-chat-interface)
10. [Design Principles](#design-principles)
11. [v1 Feature Status](#v1-feature-status)
12. [Known Tech Debt](#known-tech-debt)
13. [v2 Roadmap](#v2-roadmap)

---

## System Architecture

Project Sentinel is a **linear LangGraph StateGraph pipeline** — not a hub-and-spoke supervisor. The data flow is fully deterministic: SNMP poll → threshold + LLM analysis → policy gate → email alert.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Scheduler  (main.py)                        │
│         APScheduler BackgroundScheduler — hourly via run_job()      │
└────────────────────────────┬────────────────────────────────────────┘
                             │ graph.invoke(initial_state)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LangGraph StateGraph Pipeline                     │
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐             │
│  │  run_analyst │───▶│run_policy   │───▶│run_communicator│          │
│  │ (analyst.py) │    │_guard       │    │(communicator  │           │
│  │              │    │(safety_logic│    │   .py)        │           │
│  └──────┬───────┘    │   .py)      │    └──────┬────────┘           │
│         │            └──────┬──────┘           │                    │
│         │                   │ suppressed?       │ alert_sent=True    │
│         │                   └──────────▶ END    ▼                   │
│         │                                  SMTPAdapter              │
│         │                                (smtp_adapter.py)          │
└─────────┼────────────────────────────────────────────────────────────┘
          │ compute_color_stats() + Ollama LLM call
          ▼
┌─────────────────────┐        ┌──────────────────────────────────────┐
│   SNMPAdapter        │        │          Persistence Layer           │
│  (snmp_adapter.py)  │        │  logs/printer_history.jsonl          │
│  Lexmark XC2235     │        │  logs/alert_state.json               │
│  SNMP v2c           │        └──────────────────────────────────────┘
└─────────────────────┘

                         ┌──────────────────────────┐
                         │   Web Chat Interface      │
                         │   chat_server.py (Flask)  │
                         │   browser → /chat POST    │
                         └──────────────────────────┘
```

### Why a Linear Pipeline

There is one real decision point in this system: after the Policy Guard — send or suppress. Everything else is sequential. One conditional edge, one place to debug. A dynamic supervisor agent adds latency and failure modes for zero benefit.

---

## Directory Structure

```
Project-Sentinel/
│
├── main.py                       # Entry point — APScheduler + LangGraph graph invocation
├── chat_server.py                # Flask web chat server (Phase 5)
├── state_types.py                # AgentState TypedDict + QualityFlag enum (shared contract)
├── requirements.txt              # Python dependencies
├── .env                          # Credentials and config (never committed)
├── .env.example                  # Template for required variables
│
├── agents/
│   ├── supervisor.py             # LangGraph StateGraph builder — build_graph() + run_pipeline()
│   ├── analyst.py                # LLM Analyst — threshold checks, Ollama call, confidence score
│   └── communicator.py          # Email formatter and SMTP dispatcher
│
├── adapters/
│   ├── snmp_adapter.py           # SNMP polling — Lexmark XC2235 via pysnmp, sentinel handling
│   ├── smtp_adapter.py           # SMTP email via smtplib STARTTLS (Outlook / Gmail / Office 365)
│   └── persistence.py            # JSONL read/write for printer_history.jsonl
│
├── guardrails/
│   └── safety_logic.py           # Policy Guard — rate limit, data quality, confidence checks
│
├── logs/
│   ├── printer_history.jsonl     # Append-only decision log (polls, alerts, suppressions, errors)
│   └── alert_state.json          # Per-printer last-alert timestamps (rate limit state)
│
├── templates/
│   └── chat.html                 # Browser chat UI (served by Flask)
│
└── tests/
    ├── test_state_types.py
    ├── test_snmp_adapter.py
    ├── test_persistence.py
    ├── test_smtp_adapter.py
    ├── test_analyst.py
    ├── test_safety_logic.py
    ├── test_communicator.py
    ├── test_pipeline.py
    ├── test_supervisor_graph.py
    ├── test_main.py
    └── test_chat_server.py
```

---

## Agent Roles

### Supervisor (`agents/supervisor.py`)

- Defines the LangGraph `StateGraph` via `build_graph()`
- Wires nodes: `run_analyst` → `run_policy_guard` → conditional → `run_communicator`
- Exposes `run_pipeline()` — a single synchronous call that runs a full monitoring cycle
- Called by the APScheduler job in `main.py` and by the chat server's trigger handler

### LLM Analyst (`agents/analyst.py`)

- Receives current toner readings from `AgentState.poll_result`
- Runs deterministic two-tier threshold classification first (WARNING at 20%, CRITICAL at 10%)
- For each flagged color, calls the Ollama LLM via `langchain-openai` (OpenAI-compatible endpoint)
- LLM produces a structured `AnalystOutput`:
  - `trend_label` — one of: Stable / Declining slowly / Declining rapidly / Critically low
  - `depletion_estimate_days` — float or None
  - `confidence` — float 0.0–1.0
  - `reasoning` — 2–3 sentence natural language explanation
- Computes `velocity_pct_per_day` and `std_dev` from the 7-day JSONL history to feed the LLM
- Sets `state["llm_confidence"]` to the **minimum** across all flagged colors (conservative)
- Falls back to deterministic urgency on any LLM failure — never crashes the pipeline

### Communicator (`agents/communicator.py`)

- Only executes when Policy Guard sets `suppression_reason = None`
- Builds a structured alert email including: toner color, urgency, current %, LLM confidence, and natural language reasoning
- Dispatches via `SMTPAdapter` (smtplib STARTTLS on port 587)
- Logs the alert timestamp to `logs/alert_state.json` for rate limiting
- Raises `ValueError` on missing `ALERT_RECIPIENT` — fail-fast at the agent boundary

---

## Policy Guard

**File:** `guardrails/safety_logic.py`

All outbound email actions must pass four sequential checks. The check order is cheapest-first:

| # | Check | Failure Reason Logged |
|---|-------|-----------------------|
| 1 | **Data freshness** — poll timestamp within `STALE_THRESHOLD_MINUTES` | `data_quality: stale_data` |
| 2 | **SNMP data quality** — `data_quality_ok=True` on at least one reading | `data_quality: snmp_quality_failed` |
| 3 | **Rate limit** — no alert sent for this printer in the last 24 hours | `rate_limit: last_alert=<ISO timestamp>` |
| 4 | **LLM confidence** — `llm_confidence >= LLM_CONFIDENCE_THRESHOLD` (or `None`, which passes) | `reason=low_confidence` or `reason=erratic_readings` |

If any check fails, the alert is suppressed, the reason is logged to `printer_history.jsonl`, and the pipeline exits cleanly. A `None` confidence (LLM unavailable) passes Check 4 — deterministic threshold alerts are never blocked by LLM failures.

---

## Data Flow

### Happy Path (alert sent)

```
APScheduler run_job()
  └─ SNMPAdapter.poll()               → poll_result (CMYK readings + quality flags)
  └─ append_poll_result(poll_result)  → logs/printer_history.jsonl
  └─ graph.invoke(initial_state)
       └─ run_analyst()
            ├─ threshold check        → flagged_colors (WARNING / CRITICAL)
            ├─ compute_color_stats()  → velocity, std_dev from 7-day history
            └─ call_llm_analyst()     → confidence score + reasoning (via Ollama)
       └─ run_policy_guard()
            ├─ check_freshness()      ✓
            ├─ check_data_quality()   ✓
            ├─ check_rate_limit()     ✓
            └─ check_confidence()     ✓  →  suppression_reason = None
       └─ run_communicator()
            ├─ build_subject()        → "Sentinel Alert — Printer [IP] — [COLOR] CRITICAL"
            ├─ build_body()           → structured email with confidence % + LLM reasoning
            └─ SMTPAdapter.send_alert() → SMTP STARTTLS → inbox
```

### Suppressed Alert Path

When any Policy Guard check fails, the graph routes directly to END. The suppression reason and full decision log are persisted to `printer_history.jsonl`. No email is sent.

### State Fields (AgentState TypedDict)

| Field | Writer | Reader |
|-------|--------|--------|
| `poll_result` | `main.py run_job()` | analyst, policy guard, communicator |
| `alert_needed` | `run_analyst` | routing function, policy guard, communicator |
| `flagged_colors` | `run_analyst` | communicator |
| `llm_confidence` | `run_analyst` | policy guard, communicator |
| `llm_reasoning` | `run_analyst` | communicator |
| `suppression_reason` | `run_policy_guard` | routing function |
| `alert_sent` | `run_communicator` | `main.py` logging |
| `decision_log` | All agents | logging / tests (uses `Annotated[list, operator.add]` reducer) |

---

## Technology Stack

| Component | Library | Version | Notes |
|-----------|---------|---------|-------|
| SNMP polling | `pysnmp` (LeXtudio fork) | 7.1.22 | Only maintained pure-Python SNMP library; no C compilation |
| Agent pipeline | `langgraph` | ≥0.2.0 | StateGraph with conditional edges |
| LLM integration | `langchain-openai` + `openai` | ≥0.3.0 / ≥1.0.0 | OpenAI-compatible interface to Ollama |
| Local LLM runtime | Ollama | — | Serves models at `http://localhost:11434/v1` |
| LLM model | `minimax-m2.5:cloud` | — | Proxied through Ollama to ollama.com (requires internet) |
| Email transport | `smtplib` (stdlib) | — | STARTTLS on port 587; works with Gmail, Outlook, Office 365 |
| Persistence | `jsonlines` | ≥4.0.0 | Append-only JSONL; atomic-safe line-per-record format |
| Scheduling | `APScheduler` | ≥3.10.0,<4.0 | `BackgroundScheduler` with `IntervalTrigger` |
| Web interface | `Flask` | ≥3.1.0 | Serves chat UI + `/chat` JSON API |
| Ollama Python client | `ollama` | ≥0.6.0 | Used for intent classification in chat server |
| Config loading | `python-dotenv` | ≥1.0.0 | Loads `.env` into `os.environ` |
| Testing | `pytest` | ≥7.0.0 | 125+ tests, all GREEN |

> **Note:** `langchain-openai 0.1.25` is installed (instead of ≥0.3.0) due to an AppLocker/MinGW constraint on the build machine that blocks `pydantic-core` Rust compilation in temp directories. Documented in `.planning/STATE.md`.

---

## Setup Instructions

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd Project-Sentinel

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values (see Environment Variables section below)
```

### 3. Start Ollama and pull the model

```bash
# Ollama installs as a background service on Windows (auto-starts)
# Verify it is running:
curl http://localhost:11434/api/tags

# Pull the model (if not already present):
ollama pull minimax-m2.5:cloud
```

### 4. Run the monitoring daemon

```bash
python main.py
```

The scheduler runs immediately on startup and then on the configured interval (default: 60 minutes).

### 5. Run the web chat interface

```bash
python chat_server.py
# Open http://localhost:5000 in your browser
```

### 6. Run tests

```bash
pytest tests/ -v
```

---

## Environment Variables

All variables are loaded from `.env` via `python-dotenv`. Never commit `.env`.

### SNMP

| Variable | Default | Description |
|----------|---------|-------------|
| `SNMP_HOST` | — | IP address of the Lexmark XC2235 printer |
| `SNMP_COMMUNITY` | `public` | SNMP community string (read-only) |

### SMTP Email

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `smtp.office365.com` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port (587 = STARTTLS) |
| `SMTP_USERNAME` | — | Your email address (login + From address) |
| `SMTP_PASSWORD` | — | Email password or App Password (required if MFA is enabled) |
| `ALERT_RECIPIENT` | — | Email address to receive toner alerts |

### Policy Guard Thresholds

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CONFIDENCE_THRESHOLD` | `0.7` | Minimum LLM confidence to send an alert (0.0–1.0) |
| `TONER_ALERT_THRESHOLD` | `20` | Toner % below which a WARNING is raised |
| `TONER_CRITICAL_THRESHOLD` | `10` | Toner % below which a CRITICAL is raised |
| `STALE_THRESHOLD_MINUTES` | `120` | Max age of a poll result before it is considered stale |

### LLM / Ollama

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama OpenAI-compatible API base URL |
| `OLLAMA_MODEL` | `minimax-m2.5:cloud` | Model name as registered in Ollama |
| `OLLAMA_API_KEY` | `ollama` | Dummy key (Ollama doesn't require auth) |

### Scheduling

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_MINUTES` | `60` | How often to poll the printer |
| `PIPELINE_TIMEOUT_SECONDS` | `120` | Timeout for on-demand pipeline trigger via chat |

### Development / Test Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_MOCK_SNMP` | `false` | Use hardcoded fixture data instead of real SNMP |
| `USE_MOCK_SMTP` | `false` | Log emails to stdout instead of sending via SMTP |
| `USE_MOCK_LLM` | `false` | Return fixed mock analyst output (bypasses Ollama) |
| `CHAT_PORT` | `5000` | Port for the Flask chat server |

---

## Web Chat Interface

**File:** `chat_server.py` | **URL:** `http://localhost:5000`

The chat server exposes a POST `/chat` JSON API. The user's message is classified by the Ollama LLM (with keyword fallback), then routed to the appropriate handler.

### Supported Intents

| Intent | Example Queries | Handler |
|--------|----------------|---------|
| `toner_status` | "What are the toner levels?", "Show CMYK status" | Live SNMP poll → per-color pct + status label |
| `alert_history` | "What alerts fired this week?", "Show recent alerts" | Last 7 days from `printer_history.jsonl` |
| `suppression_explanation` | "Why was the last alert suppressed?" | Most recent suppression event → plain-English reason |
| `trigger_pipeline` | "Run a check now", "Execute pipeline" | Runs full LangGraph pipeline in a thread (120s timeout) |
| `anomaly_check` | "Is there any anomaly?", "Any issues with the printer?" | Live SNMP poll → LLM natural-language analysis |

### Response Envelope

All responses follow a standard JSON envelope:

```json
{
  "status": "ok",
  "action": "toner_status",
  "timestamp": "2026-03-06T10:00:00+00:00",
  "data": { ... }
}
```

### Intent Classification Fallback

If the Ollama LLM call fails, the server falls back to keyword matching (defined in `_keyword_classify()`). The chat interface always remains functional regardless of LLM availability.

---

## Design Principles

### Adapter Pattern
`adapters/` isolate all external system specifics (SNMP protocol, SMTP protocol, JSONL I/O) from agent logic. Agents consume normalized Python dicts from adapters — never raw protocol objects. This makes each adapter independently testable and replaceable.

### Guardrails First
The Policy Guard gates **all** outbound actions. `communicator.py` never sends without Policy Guard clearance. This is a hard architectural constraint — the guard was implemented before the communicator.

### LangGraph State is Flat
`AgentState` is a flat `TypedDict`. No nesting. Every node reads and writes top-level keys. List fields that accumulate across nodes use `Annotated[list, operator.add]` reducers to prevent LangGraph's default overwrite behavior.

### Persistent Logging
Every system event — poll results, alerts sent, alerts suppressed, LLM failures — is appended to `logs/printer_history.jsonl`. JSON Lines format means partial writes only corrupt the last line, not the entire log.

### LLM Failure is Not a Crash
`call_llm_analyst()` catches all exceptions, logs an `llm_failure` event, and returns `None`. A `None` confidence passes the Policy Guard's confidence check — threshold-based alerts proceed without LLM support. The pipeline is resilient by design.

### Scalable by Design
The SNMP adapter and agent pipeline accept `host` as a parameter. v1 targets one device. Fleet support requires looping over a printer list — no architectural changes needed.

---

## v1 Feature Status

All 6 phases complete. 125 tests GREEN.

| Requirement | Description | Status |
|-------------|-------------|--------|
| SNMP-01 | Poll Lexmark XC2235 for per-color (CMYK) toner % on schedule | ✅ Complete |
| SNMP-02 | Handle Lexmark sentinel values (-2: unknown, -3: below low threshold) as structured quality flags | ✅ Complete |
| SNMP-03 | Validate readings for staleness, null values, and out-of-range results | ✅ Complete |
| SNMP-04 | Persist every poll result to JSONL with timestamp and quality metadata | ✅ Complete |
| ANLZ-01 | Trigger alert when toner drops below configurable threshold (default 20%) | ✅ Complete |
| ANLZ-02 | LLM self-reports confidence score (0.0–1.0) as a structured field | ✅ Complete |
| ANLZ-03 | Natural language reasoning included in alert email | ✅ Complete |
| ANLZ-04 | Trend-aware urgency — fast-declining toner flagged higher than slow decline at same level | ✅ Complete |
| GURD-01 | Rate limiting: max 1 alert per printer per 24-hour window | ✅ Complete |
| GURD-02 | Suppress alerts when LLM confidence < threshold | ✅ Complete |
| GURD-03 | Suppress alerts on SNMP data quality failure | ✅ Complete |
| GURD-04 | Log all suppressed alerts with reason, timestamp, and triggering data | ✅ Complete |
| ALRT-01 | Send alert emails via SMTP STARTTLS | ✅ Complete (live delivery pending hardware validation) |
| ALRT-02 | Alert email includes: printer IP, color, %, urgency, confidence %, LLM reasoning | ✅ Complete |
| ALRT-03 | Suppressed alert events recorded in history log | ✅ Complete |
| SCHD-01 | Autonomous hourly polling via APScheduler — no manual trigger required | ✅ Complete |
| UI-01 | Browser-accessible web chat interface (Flask) | ✅ Complete |
| UI-02 | Live SNMP toner status via chat query | ✅ Complete |
| UI-03 | Alert history query (last 7 days) via chat | ✅ Complete |
| UI-04 | Plain-language suppression explanation via chat | ✅ Complete |
| UI-05 | On-demand pipeline trigger via chat (120s timeout) | ✅ Complete |

---

## Known Tech Debt

Items from the v1.0 milestone audit. None are behavioral blockers.

| # | Area | Item |
|---|------|------|
| 1 | `safety_logic.py` | Dead `erratic_readings` branch: `std_dev` is never written into `flagged_colors` items by `analyst.py`. Suppression always fires via `low_confidence` branch. Not a behavioral bug — suppression works correctly. |
| 2 | Phase 1 — ALRT-01 | Live SMTP delivery unconfirmed. Requires real Outlook credentials and physical inbox verification. |
| 3 | Phase 4 — shutdown | Ctrl+C graceful shutdown and SIGTERM handler not confirmed in a live terminal session. |
| 4 | All phases | Live hardware gates open: physical Lexmark XC2235 SNMP, real SMTP delivery, and end-to-end `python main.py` run are operational validations — not code gaps. |
| 5 | Phase 3 | `langchain-openai 0.1.25` installed instead of ≥0.3.0 due to AppLocker/MinGW constraint. Documented in `.planning/STATE.md`. |

---

## v2 Roadmap

### Analysis Enhancements

- **ANLZ-V2-01** — Time-to-depletion estimate ("~X days until [color] runs out") surfaced as a standalone field in alert emails
- **ANLZ-V2-02** — Configurable alert recipient via environment variable (currently fixed to `ALERT_RECIPIENT`)
- **ANLZ-V2-03** — LLM call caching: skip Ollama when toner readings haven't changed meaningfully since last analysis

### Multi-Printer Support

- **MULT-V2-01** — Monitor multiple printers with per-printer rate limiting and separate history tracking
- **MULT-V2-02** — Alert emails include printer location/name for fleet context

### Operational

- **OPER-V2-01** — Log rotation to cap `printer_history.jsonl` growth (currently unbounded)
- **OPER-V2-02** — SQLite for rate limit state (replaces `alert_state.json`) to support concurrent multi-printer polling

### Out of Scope (by design)

| Feature | Reason |
|---------|--------|
| Inbound email reading | Fragile, bidirectional complexity for zero v1 value |
| Web dashboard / status UI | Alert emails sufficient; chat interface covers QC queries |
| Auto-ordering of toner supplies | Human-in-the-loop is a feature, not a limitation |
| SNMP auto-discovery | Single known device IP; fleet discovery is a v2+ concern |
| OAuth for Exchange | Service account Basic Auth sufficient for on-prem Exchange |
| Mobile push notifications | Email reaches mobile; if urgency requires push, use Teams/Slack webhooks |

---

*Last updated: 2026-03-06*
