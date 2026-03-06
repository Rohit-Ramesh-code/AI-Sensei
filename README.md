# AI Sensei

> **Detect metric degradation before it causes failure — alerting the right person with enough lead time to act.**

AI Sensei is a **domain-agnostic hybrid ML/LLM orchestration engine** built on LangGraph. It ingests time-series metrics from any data source via pluggable Sensor Adapters, runs trend analysis through a local LLM Analyst Agent, gates every outbound action through a deterministic Policy Guard, and delivers alerts through pluggable Notification Adapters. A browser-based chat interface lets operators query system status, alert history, and trigger on-demand analysis cycles.

The current reference implementation monitors consumable resource levels on a networked device via SNMP. The same pipeline, unchanged, applies to any domain where metric degradation must be detected and communicated proactively.

---

## Table of Contents

1. [Core Concept](#core-concept)
2. [System Architecture](#system-architecture)
3. [Adapter Contract](#adapter-contract)
4. [Directory Structure](#directory-structure)
5. [Agent Roles](#agent-roles)
6. [Policy Guard](#policy-guard)
7. [Data Flow](#data-flow)
8. [Technology Stack](#technology-stack)
9. [Setup Instructions](#setup-instructions)
10. [Environment Variables](#environment-variables)
11. [Web Chat Interface](#web-chat-interface)
12. [Design Principles](#design-principles)
13. [Domain Applications](#domain-applications)
14. [v1 Feature Status](#v1-feature-status)
15. [Known Tech Debt](#known-tech-debt)
16. [v2 Roadmap](#v2-roadmap)

---

## Core Concept

Most monitoring tools answer: **"Is the metric below a threshold right now?"**

AI Sensei answers: **"At the current rate of change, when will this metric reach a failure state — and is that prediction reliable enough to act on?"**

This requires three layers working together:

```
┌──────────────────────────────────────────────────────┐
│  Layer 1 — Deterministic Threshold Engine            │
│  Fast, always runs. Flags metrics outside bounds.    │
│  No LLM dependency. Alert even if LLM is offline.   │
├──────────────────────────────────────────────────────┤
│  Layer 2 — LLM Trend Analyst                         │
│  Computes velocity and variance from history.        │
│  LLM synthesizes a depletion estimate + confidence.  │
│  Structured output enforced via Pydantic schema.     │
├──────────────────────────────────────────────────────┤
│  Layer 3 — Deterministic Policy Guard                │
│  Rate limiting, data quality check, confidence gate. │
│  Pure Python. Cannot be bypassed by the LLM.         │
└──────────────────────────────────────────────────────┘
```

The LLM is sandwiched between two deterministic layers. It cannot send an alert on its own — it can only influence whether an already-flagged metric is actionable and with what urgency.

---

## System Architecture

AI Sensei is a **linear LangGraph StateGraph pipeline** — not a hub-and-spoke supervisor. Data flows in one direction through fixed nodes. There is exactly one conditional edge, after the Policy Guard: send or suppress.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Scheduler  (main.py)                        │
│          APScheduler BackgroundScheduler — periodic via run_job()    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ graph.invoke(initial_state)
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     LangGraph StateGraph Pipeline                    │
│                                                                      │
│  ┌──────────────┐    ┌─────────────────┐    ┌─────────────────┐      │
│  │ run_analyst  │───▶│ run_policy_guard │───▶│run_communicator │      │
│  │ (analyst.py) │    │ (safety_logic   │    │(communicator.py)│      │
│  │              │    │     .py)        │    │                 │      │
│  └──────┬───────┘    └───────┬─────────┘    └────────┬────────┘      │
│         │                   │                        │               │
│    LLM + threshold     suppressed? ──▶ END      Notification         │
│    analysis on                              Adapter.send_alert()     │
│    flagged metrics                                                    │
└──────────────────────────────────────────────────────────────────────┘
         │
         │  compute_metric_stats() — velocity, std_dev from history
         │  call_llm_analyst()     — Ollama structured output
         ▼
┌─────────────────────┐        ┌──────────────────────────────────────┐
│   Sensor Adapter    │        │          Persistence Layer           │
│   (adapters/)       │        │  logs/metric_history.jsonl           │
│                     │        │  logs/alert_state.json               │
│  Any data source:   │        │                                      │
│  • SNMP device      │        │  Append-only JSONL — one record per  │
│  • REST API         │        │  poll cycle, alert, suppression,     │
│  • Database query   │        │  or LLM failure event.               │
│  • IoT sensor feed  │        └──────────────────────────────────────┘
│  • File / stream    │
└─────────────────────┘

                          ┌──────────────────────────────┐
                          │     Web Chat Interface        │
                          │   chat_server.py  (Flask)    │
                          │   browser  →  /chat  POST    │
                          └──────────────────────────────┘
```

### Why a Linear Pipeline

There is one real decision point: after the Policy Guard — send or suppress. Everything upstream is sequential. A dynamic supervisor agent that routes between nodes via LLM decisions would add latency, a new failure mode, and zero benefit for a deterministic pipeline.

---

## Adapter Contract

The framework is extended by implementing two adapter interfaces. Everything inside the pipeline (analyst, policy guard, communicator) is completely agnostic to the underlying data source and notification channel.

### Sensor Adapter

Responsible for polling the data source and returning a normalized `PollResult` dict. The pipeline consumes only this normalized structure — never raw protocol objects.

```python
# Minimum contract any Sensor Adapter must satisfy
class SensorAdapter:
    def poll(self) -> dict:
        """
        Returns a PollResult dict:
        {
            "asset_id": str,          # Unique identifier for the monitored entity
            "timestamp": str,         # ISO 8601 UTC timestamp of the poll
            "readings": [
                {
                    "channel": str,           # Metric channel name (e.g. "cpu", "black", "tank_a")
                    "metric_value": float,    # Normalized metric value (e.g. percentage 0–100)
                    "data_quality_ok": bool,  # False if reading is stale, null, or out of range
                    "quality_flag": str,      # Human-readable quality label
                }
            ]
        }
        """
```

**Reference implementation:** `adapters/snmp_adapter.py` — polls a networked device via SNMP v2c, handles protocol-specific sentinel values (-2, -3), and normalizes all readings to the above structure.

**Other example implementations:**
| Data Source | What poll() reads | Channel examples |
|-------------|-------------------|-----------------|
| SNMP device | MIB OID table | Consumable levels per supply slot |
| REST API | JSON endpoint | CPU %, memory %, queue depth |
| Database | SQL query result | Row counts, latency percentiles |
| IoT sensor | MQTT / HTTP feed | Temperature, pressure, vibration |
| File / stream | Log line counter | Error rate, throughput |

### Notification Adapter

Responsible for delivering a formatted alert payload through any channel.

```python
class NotificationAdapter:
    def send_alert(self, subject: str, body: str) -> None:
        """
        Deliver the alert. Raise on failure — communicator.py will log the exception.
        Channel examples: SMTP email, Slack webhook, MS Teams, SMS, PagerDuty, webhook POST.
        """
```

**Reference implementation:** `adapters/smtp_adapter.py` — sends via SMTP STARTTLS (port 587). Compatible with Gmail, Outlook, and Office 365.

---

## Directory Structure

```
AI-Sensei/
│
├── main.py                       # Entry point — APScheduler + LangGraph graph invocation
├── chat_server.py                # Flask web chat server — conversational operator interface
├── state_types.py                # AgentState TypedDict + QualityFlag enum (pipeline contract)
├── requirements.txt              # Python dependencies
├── .env                          # Runtime credentials and config (never committed)
├── .env.example                  # Template for all required variables
│
├── agents/
│   ├── supervisor.py             # LangGraph StateGraph builder — build_graph() + run_pipeline()
│   ├── analyst.py                # LLM Analyst — threshold classification, Ollama call, confidence
│   └── communicator.py          # Alert formatter and Notification Adapter dispatcher
│
├── adapters/
│   ├── snmp_adapter.py           # Sensor Adapter — SNMP v2c polling with sentinel handling
│   ├── smtp_adapter.py           # Notification Adapter — SMTP STARTTLS email delivery
│   └── persistence.py            # JSONL read/write for metric_history.jsonl
│
├── guardrails/
│   └── safety_logic.py           # Policy Guard — freshness, data quality, rate limit, confidence
│
├── logs/
│   ├── metric_history.jsonl      # Append-only event log (polls, alerts, suppressions, errors)
│   └── alert_state.json          # Per-asset last-alert timestamps (rate limit state)
│
├── templates/
│   └── chat.html                 # Browser chat UI (served by Flask)
│
└── tests/
    ├── test_state_types.py       # AgentState + QualityFlag contract
    ├── test_snmp_adapter.py      # Sensor Adapter (SNMP reference implementation)
    ├── test_persistence.py       # JSONL persistence layer
    ├── test_smtp_adapter.py      # Notification Adapter (SMTP reference implementation)
    ├── test_analyst.py           # LLM Analyst — threshold logic, LLM call, fallback
    ├── test_safety_logic.py      # Policy Guard — all four checks
    ├── test_communicator.py      # Alert formatting and dispatch
    ├── test_pipeline.py          # End-to-end pipeline integration
    ├── test_supervisor_graph.py  # LangGraph StateGraph wiring and routing
    ├── test_main.py              # Scheduler + entry point
    └── test_chat_server.py       # Chat API intent classification and handlers
```

---

## Agent Roles

### Supervisor (`agents/supervisor.py`)

The graph wiring layer. Contains no business logic — only structure.

- Defines the LangGraph `StateGraph` via `build_graph()`
- Wires nodes: `run_analyst` → `run_policy_guard` → conditional edge → `run_communicator`
- Exposes `run_pipeline()` — a single synchronous call that completes one full monitoring cycle
- Called by the APScheduler job in `main.py` on every scheduled tick, and by the chat server's on-demand trigger handler

### LLM Analyst (`agents/analyst.py`)

The intelligence layer. Runs two passes on every flagged metric: deterministic first, LLM second.

**Pass 1 — Deterministic threshold classification:**
- Compares each channel's `metric_value` against configurable WARNING and CRITICAL thresholds
- Produces `flagged_metrics` — a list of channels needing attention, each with urgency tier
- Runs even when the LLM is offline; ensures alerts always fire on severe readings

**Pass 2 — LLM trend analysis (per flagged channel):**
- Calls `compute_metric_stats()` — loads the 7-day JSONL history, computes:
  - `velocity` — rate of change in metric units per day (negative = degrading)
  - `std_dev` — variance across readings (high = erratic signal)
  - `n` — number of data points in the window
- Invokes the Ollama LLM via `langchain-openai` with a structured prompt containing the pre-computed stats
- LLM returns a `AnalystOutput` Pydantic model (enforced schema — no free-text parsing):

```python
class AnalystOutput(BaseModel):
    trend_label: str            # "Stable" | "Declining slowly" | "Declining rapidly" | "Critically low"
    depletion_estimate_days: Optional[float]  # Days until failure at current rate; None if stable
    confidence: float           # 0.0–1.0 self-reported; lower when std_dev is high or n is low
    reasoning: str              # 2–3 sentence natural language explanation
```

- Sets `state["llm_confidence"]` to the **minimum** across all flagged channels (conservative: the weakest signal governs the alert decision)
- On any LLM exception: logs an `llm_failure` event to JSONL, returns `None`, pipeline continues with deterministic urgency — never crashes

### Communicator (`agents/communicator.py`)

The output layer. Only executes when the Policy Guard clears the alert.

- Receives `flagged_metrics`, `llm_confidence`, and `llm_reasoning` from `AgentState`
- Builds a structured alert payload: asset identifier, flagged channels, urgency tiers, confidence %, natural language reasoning
- When LLM analysis is unavailable: includes a fallback note — "Analysis unavailable — alert based on threshold check only"
- Dispatches via the configured Notification Adapter (`SMTPAdapter` in the reference implementation)
- Records the alert timestamp to `logs/alert_state.json` for the rate limiter
- Raises `ValueError` on missing `ALERT_RECIPIENT` — fail-fast at the agent boundary

---

## Policy Guard

**File:** `guardrails/safety_logic.py`

The Policy Guard is a **pure Python deterministic gate** between the Analyst and the Communicator. It cannot be influenced by the LLM. It runs four checks in cheapest-first order:

| # | Check | What it verifies | Failure reason logged |
|---|-------|------------------|-----------------------|
| 1 | **Data freshness** | Poll timestamp is within `STALE_THRESHOLD_MINUTES` of now | `data_quality: stale_data` |
| 2 | **Sensor data quality** | At least one channel has `data_quality_ok = True` | `data_quality: sensor_quality_failed` |
| 3 | **Rate limit** | No alert was sent for this asset in the last 24 hours | `rate_limit: last_alert=<ISO timestamp>` |
| 4 | **LLM confidence** | `llm_confidence >= LLM_CONFIDENCE_THRESHOLD`, or `llm_confidence` is `None` | `reason=low_confidence` |

**Key design decisions:**
- Check order is cheapest-first: a stale poll is caught in Check 1 without touching disk or the rate limit file
- A `None` confidence (cold start, LLM offline, LLM failure) **passes** Check 4 — threshold-based alerts proceed unconditionally when LLM is unavailable
- All suppression events are logged to `metric_history.jsonl` with the exact reason, timestamp, and triggering data — the audit trail is complete regardless of outcome
- The Policy Guard is a graph **node**, not middleware. Its decision is a first-class state field (`suppression_reason`) that is inspectable, loggable, and testable independently

---

## Data Flow

### Successful Alert Path

```
APScheduler  run_job()
  │
  ├─ SensorAdapter.poll()              →  poll_result  (normalized metric readings)
  ├─ append_poll_result(poll_result)   →  logs/metric_history.jsonl
  └─ graph.invoke(initial_state)
       │
       ├─ run_analyst()
       │    ├─ Threshold classification     →  flagged_metrics  [WARNING / CRITICAL]
       │    ├─ compute_metric_stats()       →  velocity, std_dev, n  (from 7-day JSONL window)
       │    └─ call_llm_analyst()  (Ollama) →  trend_label, depletion_days, confidence, reasoning
       │
       ├─ run_policy_guard()
       │    ├─ check_freshness()            ✓
       │    ├─ check_data_quality()         ✓
       │    ├─ check_rate_limit()           ✓
       │    └─ check_confidence()           ✓   →  suppression_reason = None
       │
       └─ run_communicator()
            ├─ build_subject()             →  "AI Sensei Alert — [asset_id] — [channel] CRITICAL"
            ├─ build_body()               →  structured payload + confidence % + LLM reasoning
            └─ NotificationAdapter.send_alert()  →  alert delivered
```

### Suppressed Alert Path

When any Policy Guard check fails, `_route_after_policy_guard()` routes directly to `END`. The suppression reason and the full `decision_log` are persisted to `metric_history.jsonl`. No notification is sent.

### Pipeline State (AgentState TypedDict)

The shared state is a flat `TypedDict`. Nodes never import or call each other — all communication is through state.

| Field | Writer | Reader | Notes |
|-------|--------|--------|-------|
| `poll_result` | `main.py run_job()` | analyst, policy guard, communicator | Injected before `graph.invoke()` |
| `alert_needed` | `run_analyst` | routing fn, policy guard, communicator | Set by threshold classification |
| `flagged_metrics` | `run_analyst` | communicator | List of `{channel, urgency, display_value}` dicts |
| `llm_confidence` | `run_analyst` | policy guard, communicator | `None` when LLM unavailable |
| `llm_reasoning` | `run_analyst` | communicator | `None` when LLM unavailable |
| `suppression_reason` | `run_policy_guard` | routing fn | `None` means alert is approved |
| `alert_sent` | `run_communicator` | `main.py` logging | Boolean |
| `decision_log` | All agents | logging, tests | `Annotated[list, operator.add]` — accumulates across all nodes |

---

## Technology Stack

### Core Framework

| Component | Library | Version | Role |
|-----------|---------|---------|------|
| Agent pipeline | `langgraph` | ≥0.2.0 | StateGraph with nodes, edges, and conditional routing |
| LLM integration | `langchain-openai` + `openai` | ≥0.3.0 / ≥1.0.0 | OpenAI-compatible interface — works with any Ollama-hosted model |
| Local LLM runtime | Ollama | — | Hosts models locally; exposes OpenAI-compatible REST API |
| LLM model | `minimax-m2.5:cloud` | — | Current model; swap via `OLLAMA_MODEL` env var |
| Scheduling | `APScheduler` | ≥3.10.0, <4.0 | `BackgroundScheduler` + `IntervalTrigger`; pin to 3.x (4.x is alpha) |
| Web interface | `Flask` | ≥3.1.0 | Chat UI + `/chat` JSON API |
| Chat intent classifier | `ollama` (Python client) | ≥0.6.0 | Classifies natural language queries into pipeline actions |

### Reference Adapter Implementations

| Adapter | Library | Version | Notes |
|---------|---------|---------|-------|
| Sensor (SNMP) | `pysnmp` (LeXtudio fork) | 7.1.22 | Pure-Python SNMP v2c; no C compilation required |
| Notification (SMTP) | `smtplib` (stdlib) | — | STARTTLS on port 587; Gmail, Outlook, Office 365 compatible |

### Infrastructure

| Component | Library | Version | Notes |
|-----------|---------|---------|-------|
| Persistence | `jsonlines` | ≥4.0.0 | Append-only JSONL; partial writes corrupt only the last line |
| Config loading | `python-dotenv` | ≥1.0.0 | Loads `.env` into `os.environ` at startup |
| Testing | `pytest` | ≥7.0.0 | 125+ tests, all GREEN |

> **Installation note:** `langchain-openai 0.1.25` is installed instead of ≥0.3.0 due to an AppLocker/MinGW constraint that blocks `pydantic-core` Rust compilation in temp directories on the build machine. Documented in `.planning/STATE.md`.

---

## Setup Instructions

### 1. Install dependencies

```bash
git clone https://github.com/Rohit-Ramesh-code/AI-Sensei.git
cd AI-Sensei

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — see Environment Variables section below
```

### 3. Start Ollama

```bash
# Ollama auto-starts on Windows as a background service.
# Verify it is reachable:
curl http://localhost:11434/api/tags

# Pull the model if not already present:
ollama pull minimax-m2.5:cloud

# Swap to any other Ollama-hosted model:
# set OLLAMA_MODEL=llama3.2 in .env
```

### 4. Run the monitoring daemon

```bash
python main.py
# Polls immediately on startup, then every POLL_INTERVAL_MINUTES
```

### 5. Run the web chat interface

```bash
python chat_server.py
# Open http://localhost:5000
```

### 6. Run the test suite

```bash
pytest tests/ -v
```

---

## Environment Variables

All variables are loaded from `.env` via `python-dotenv`. Never commit `.env`.

### Sensor Adapter

| Variable | Default | Description |
|----------|---------|-------------|
| `SNMP_HOST` | — | Network address of the monitored asset (reference: SNMP device IP) |
| `SNMP_COMMUNITY` | `public` | Sensor authentication token (reference: SNMP community string) |

> **To add a new Sensor Adapter:** implement the adapter contract, wire it into `run_job()` in `main.py`, and add the relevant connection variables here.

### Notification Adapter

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `smtp.office365.com` | Notification server hostname (reference: SMTP server) |
| `SMTP_PORT` | `587` | Notification server port (587 = STARTTLS) |
| `SMTP_USERNAME` | — | Sender credential / login (reference: email address) |
| `SMTP_PASSWORD` | — | Sender secret / App Password |
| `ALERT_RECIPIENT` | — | Destination address for alerts (reference: recipient email) |

### Policy Guard Thresholds

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CONFIDENCE_THRESHOLD` | `0.7` | Minimum LLM confidence required to send an alert (0.0–1.0) |
| `METRIC_ALERT_THRESHOLD` | `20` | Metric value (%) below which a WARNING is raised |
| `METRIC_CRITICAL_THRESHOLD` | `10` | Metric value (%) below which a CRITICAL is raised |
| `STALE_THRESHOLD_MINUTES` | `120` | Maximum age of a poll result before it is treated as stale |

### LLM / Ollama

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible API base URL |
| `OLLAMA_MODEL` | `minimax-m2.5:cloud` | Model identifier as registered in Ollama |
| `OLLAMA_API_KEY` | `ollama` | Placeholder key (Ollama does not require auth) |

### Scheduling

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_MINUTES` | `60` | How often the scheduler invokes `run_job()` |
| `PIPELINE_TIMEOUT_SECONDS` | `120` | Timeout for on-demand pipeline trigger via chat (increase for slow LLM) |

### Development / Test Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_MOCK_SENSOR` | `false` | Return hardcoded fixture data instead of calling the real Sensor Adapter |
| `USE_MOCK_NOTIFIER` | `false` | Print alerts to stdout instead of dispatching via Notification Adapter |
| `USE_MOCK_LLM` | `false` | Return a fixed `AnalystOutput` — bypasses Ollama entirely |
| `CHAT_PORT` | `5000` | Port for the Flask chat server |

---

## Web Chat Interface

**File:** `chat_server.py` | **URL:** `http://localhost:5000`

A conversational operator interface built on Flask. The user's natural language message is classified by the Ollama LLM into one of the supported actions (with a keyword-matching fallback if Ollama is unreachable). The classified action routes to the appropriate handler, which returns a standard JSON envelope.

### Supported Intents

| Intent | Example Queries | Handler |
|--------|----------------|---------|
| `metric_status` | "What are the current readings?", "Show system metrics" | Live Sensor Adapter poll → per-channel value + status label |
| `alert_history` | "What alerts fired this week?", "Show recent alerts" | Last 7 days from `metric_history.jsonl` |
| `suppression_explanation` | "Why was the last alert suppressed?", "What blocked the alert?" | Most recent suppression event → plain-English Policy Guard reason |
| `trigger_pipeline` | "Run a check now", "Force analysis", "Execute pipeline" | Runs full LangGraph pipeline in a background thread (`PIPELINE_TIMEOUT_SECONDS` timeout) |
| `anomaly_check` | "Are there any anomalies?", "Is anything wrong?", "Any issues?" | Live Sensor Adapter poll → LLM natural-language anomaly assessment |

### Response Envelope

All responses use a consistent JSON structure:

```json
{
  "status": "ok",
  "action": "metric_status",
  "timestamp": "2026-03-06T10:00:00+00:00",
  "data": { ... }
}
```

`status` is one of: `ok` / `error` / `unknown_intent`.

### Classification Fallback

If the Ollama LLM call fails during intent classification, `_keyword_classify()` takes over using substring matching on the message. The chat interface is always functional — LLM availability is not required for basic operation.

---

## Design Principles

### Adapter Pattern — Swap Data Sources and Notification Channels Without Touching the Pipeline

`adapters/` contain all external system specifics. The pipeline (analyst, policy guard, communicator) consumes only normalized Python dicts — never raw protocol objects, connection handles, or vendor-specific types. To target a new data source: implement `SensorAdapter.poll()`. To add a new alert channel: implement `NotificationAdapter.send_alert()`. Zero pipeline changes required.

### Guardrails First — The Policy Guard is Architecturally Upstream of Every Outbound Action

`communicator.py` **never** sends without explicit Policy Guard clearance. This is enforced by the LangGraph graph structure, not by convention. The guard was implemented before the communicator as a hard project constraint. Every suppression is logged — the system's behavior is fully auditable.

### LLM is Sandwiched, Not in Control

The LLM Analyst operates between two deterministic layers. It cannot trigger an alert on its own (threshold layer must flag the metric first) and cannot suppress a valid alert if all guardrail checks pass. It influences **urgency** and **confidence** — not the fundamental send/suppress decision.

### LLM Failure is Not a Crash

`call_llm_analyst()` catches all exceptions immediately. On failure: logs an `llm_failure` event to JSONL, returns `None`, and the pipeline continues. A `None` confidence value passes Check 4 of the Policy Guard — deterministic threshold alerts always fire for severe readings even when the LLM is completely offline.

### Flat State, Explicit Reducers

`AgentState` is a flat `TypedDict`. No nested objects. Every node reads and writes top-level keys. The `decision_log` list field uses `Annotated[list, operator.add]` — LangGraph's explicit reducer syntax that accumulates entries across nodes rather than overwriting. All other fields use default overwrite semantics (each field has exactly one writer).

### Persistent, Append-Only Logging

Every system event is appended to `logs/metric_history.jsonl`. JSON Lines format: one JSON object per line, each line independent. A process crash or partial write corrupts at most one line. The log is the single source of truth for rate limiting, trend history, audit, and debugging.

### Asset-Agnostic Rate Limiting

Rate limit state is keyed by `asset_id` in `logs/alert_state.json`. Multiple assets are rate-limited independently. v1 monitors one asset; expanding to a fleet requires looping over asset IDs — no architectural changes.

---

## Domain Applications

The pipeline is domain-agnostic. The following examples use the framework unchanged, swapping only the Sensor Adapter and environment configuration.

| Domain | Sensor Adapter | Metric Channels | Alert Trigger |
|--------|---------------|-----------------|---------------|
| **Hardware consumables** (reference) | SNMP device poll | Per-supply slot remaining % | Level below threshold + depleting rapidly |
| **Cloud infrastructure** | AWS CloudWatch / REST API | CPU %, memory %, disk I/O | Sustained high utilization trending toward capacity |
| **Industrial IoT** | MQTT broker / OPC-UA | Vibration RMS, temperature, pressure | Sensor reading outside safe operating range + accelerating |
| **Database health** | SQL query / pg_stat | Table bloat %, connection pool %, query latency p99 | Metric degrading faster than normal growth rate |
| **SaaS subscription** | Billing API | API quota consumed %, seat utilization % | Quota approaching exhaustion before renewal date |
| **Supply chain inventory** | ERP REST API | Stock level per SKU (units remaining) | Inventory below reorder point + consumption velocity rising |
| **Environmental monitoring** | Sensor REST feed | Air quality index, CO₂ ppm, humidity % | Reading outside acceptable band + trend worsening |

In each case: implement `SensorAdapter.poll()` returning normalized `{channel, metric_value, data_quality_ok}` dicts, update the threshold environment variables, and the LLM Analyst, Policy Guard, and Communicator operate without modification.

---

## v1 Feature Status

All 6 phases complete. 125 tests GREEN.

| ID | Capability | Status |
|----|------------|--------|
| SENS-01 | Sensor Adapter polls asset for per-channel metrics on a schedule | ✅ Complete |
| SENS-02 | Adapter detects and handles protocol-specific sentinel / error codes as structured quality flags | ✅ Complete |
| SENS-03 | Adapter validates readings for staleness, null values, and out-of-range results | ✅ Complete |
| SENS-04 | Every poll result persisted to JSONL with timestamp and quality metadata | ✅ Complete |
| ANLZ-01 | Threshold engine flags channels below configurable WARNING / CRITICAL bounds | ✅ Complete |
| ANLZ-02 | LLM Analyst self-reports structured confidence score (0.0–1.0) | ✅ Complete |
| ANLZ-03 | LLM natural language reasoning included in outbound alert payload | ✅ Complete |
| ANLZ-04 | Trend-aware urgency — fast-declining metric flagged with higher urgency than slow decline at same level | ✅ Complete |
| GURD-01 | Rate limiting: max 1 alert per asset per 24-hour window | ✅ Complete |
| GURD-02 | Suppress alerts when LLM confidence is below configured minimum | ✅ Complete |
| GURD-03 | Suppress alerts when sensor data quality check fails | ✅ Complete |
| GURD-04 | All suppressed alerts logged with reason, timestamp, and triggering data | ✅ Complete |
| ALRT-01 | Notification Adapter delivers alert via configured channel | ✅ Complete (live delivery pending hardware validation) |
| ALRT-02 | Alert payload includes: asset ID, channel, value, urgency, confidence %, LLM reasoning | ✅ Complete |
| ALRT-03 | Suppressed alert events recorded in metric history log | ✅ Complete |
| SCHD-01 | Autonomous scheduled polling via APScheduler — no manual trigger required after startup | ✅ Complete |
| UI-01 | Browser-accessible web chat interface (Flask) | ✅ Complete |
| UI-02 | Live metric status query via chat | ✅ Complete |
| UI-03 | Alert history query (last 7 days) via chat | ✅ Complete |
| UI-04 | Plain-language suppression explanation via chat | ✅ Complete |
| UI-05 | On-demand pipeline trigger via chat (`PIPELINE_TIMEOUT_SECONDS` timeout) | ✅ Complete |

---

## Known Tech Debt

Items from the v1.0 milestone audit. None block operation.

| # | Area | Item |
|---|------|------|
| 1 | `safety_logic.py` | Dead `erratic_readings` branch: `std_dev` is never written into `flagged_metrics` items by `analyst.py`. The suppression reason always resolves via the `low_confidence` branch. Not a behavioral bug — suppression fires correctly. Fix: populate `item['std_dev']` in `run_analyst()` after urgency assignment. |
| 2 | Notification Adapter | Live delivery via SMTP unconfirmed. Requires real credentials and physical inbox verification. |
| 3 | Scheduler shutdown | Ctrl+C graceful shutdown and SIGTERM handler not confirmed in a live terminal session. |
| 4 | Hardware validation | End-to-end live run against a real sensor device, real LLM (Ollama), and real notification delivery are operational validations — not code gaps. |
| 5 | Dependency pin | `langchain-openai 0.1.25` installed instead of ≥0.3.0 due to AppLocker/MinGW constraint. Documented in `.planning/STATE.md`. |

---

## v2 Roadmap

### Intelligence Enhancements

- **ANLZ-V2-01** — Time-to-failure estimate surfaced as a standalone structured field in the alert payload (not just in LLM reasoning prose)
- **ANLZ-V2-02** — LLM call caching: skip Ollama invocation when metric values haven't changed meaningfully since the last analysis cycle
- **ANLZ-V2-03** — Multi-channel correlation: alert when multiple channels are declining simultaneously (suggests systemic degradation rather than isolated anomaly)

### Multi-Asset Support

- **MULT-V2-01** — Monitor multiple assets with per-asset rate limiting, history tracking, and independent thresholds
- **MULT-V2-02** — Alert payload includes asset location/label for fleet-scale context

### Operational Hardening

- **OPER-V2-01** — Log rotation to cap `metric_history.jsonl` growth (currently unbounded; one year of hourly polling produces ~35,000 entries)
- **OPER-V2-02** — SQLite backend for rate limit state (replaces `alert_state.json`) to support concurrent multi-asset polling without file-lock races
- **OPER-V2-03** — Additional Notification Adapter implementations: Slack webhook, MS Teams, PagerDuty, generic HTTP POST

### Explicitly Out of Scope

| Feature | Reason |
|---------|--------|
| Inbound message parsing (email, chat commands) | Fragile MIME/intent parsing for marginal value — config files or API endpoints are more reliable |
| Web dashboard with real-time charts | Alert delivery and the chat interface cover operator queries; a live dashboard is a separate product concern |
| Automatic remediation actions | Human-in-the-loop is a deliberate design choice, not a limitation |
| Sensor auto-discovery | Single known asset addresses are sufficient; discovery is a fleet-scale concern for v2+ |
| Native mobile push notifications | Alert email reaches mobile; Teams/Slack webhooks are the right escalation path |

---

*Last updated: 2026-03-06*
