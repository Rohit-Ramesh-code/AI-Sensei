# Roadmap: Project Sentinel

## Overview

Project Sentinel delivers a printer toner monitoring system in five phases, following the dependency chain: adapters (no dependencies) -> deterministic pipeline (guardrails before communicator) -> LLM intelligence layer -> full orchestration -> interactive web interface. Phase 2 delivers a working threshold-based alerting system with no LLM dependency. Each subsequent phase layers capability on a verified foundation. The web chat interface comes last because it depends on every other subsystem being operational.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - SNMP and EWS adapters, state types, and persistence layer
- [x] **Phase 2: Monitoring Pipeline** - Threshold-based alerts with policy guard and email delivery (completed 2026-03-01)
- [x] **Phase 3: LLM Analyst** - AI-powered trend analysis, confidence scoring, and natural language reasoning (completed 2026-03-02)
- [ ] **Phase 4: Orchestration** - LangGraph wiring and scheduled autonomous operation
- [ ] **Phase 5: Web Chat Interface** - Browser-based conversational interface for QC engineers

## Phase Details

### Phase 1: Foundation
**Goal**: Adapters can talk to real hardware and Exchange, data is persisted reliably, and state types define the contract for all downstream nodes
**Depends on**: Nothing (first phase)
**Requirements**: SNMP-01, SNMP-02, SNMP-03, SNMP-04, ALRT-01
**Success Criteria** (what must be TRUE):
  1. Running the SNMP adapter against the Lexmark XC2235 returns toner percentages for all four colors (CMYK) with data quality flags
  2. SNMP sentinel values (-2, -3) are converted to structured quality flags instead of crashing or returning raw error values
  3. Every poll result (valid or invalid) is appended to a JSON Lines log file with timestamp and quality metadata
  4. Running the EWS adapter sends a test email to the configured recipient through the Exchange service account
  5. State type definitions exist and are importable by downstream modules
**Plans**: 3 plans

Plans:
- [ ] 01-01-PLAN.md — State types (TypedDict + QualityFlag enum) and SNMP adapter with sentinel handling and mock mode
- [ ] 01-02-PLAN.md — JSONL persistence layer, requirements.txt, and .env.example scaffolding
- [ ] 01-03-PLAN.md — EWS adapter with exchangelib, mock mode, and live Exchange verification checkpoint

### Phase 2: Monitoring Pipeline
**Goal**: System detects low toner via threshold comparison and delivers actionable alert emails, gated by deterministic policy checks -- a complete working product with no LLM dependency
**Depends on**: Phase 1
**Requirements**: ANLZ-01, GURD-01, GURD-03, GURD-04, ALRT-02, ALRT-03
**Success Criteria** (what must be TRUE):
  1. When any toner color drops below the configured threshold (default 20%), the system flags it for alerting
  2. Alert emails include printer name, toner color, current percentage, and urgency level
  3. A second alert for the same printer within 24 hours is suppressed (rate limiting works)
  4. Alerts are suppressed when SNMP data quality is bad (stale, null, or unresolved sentinel), and the suppression reason is logged
  5. Every suppressed alert is recorded in the history log with reason, timestamp, and triggering data
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md — Extend AgentState with flagged_colors, implement deterministic threshold checker in analyst.py
- [x] 02-02-PLAN.md — Implement Policy Guard in safety_logic.py: rate limiting, staleness check, suppression logging
- [x] 02-03-PLAN.md — Implement communicator.py (email construction + dispatch) and supervisor.py (sequential pipeline)

### Phase 3: LLM Analyst
**Goal**: An LLM analyst produces trend-aware predictions with confidence scores, and the policy guard uses confidence to gate alerts -- transforming threshold alerts into intelligent analysis
**Depends on**: Phase 2
**Requirements**: ANLZ-02, ANLZ-03, ANLZ-04, GURD-02
**Success Criteria** (what must be TRUE):
  1. The LLM analyst outputs a structured confidence score (0.0-1.0) alongside every analysis
  2. Alert emails now include a natural language explanation of the analyst's reasoning
  3. Fast-dropping toner (high depletion velocity) is flagged with higher urgency than slow decline at the same level
  4. Alerts are suppressed when the LLM confidence score falls below the configured minimum (default 0.7), with the reason logged
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — AgentState extension (llm_confidence, llm_reasoning), requirements.txt (langchain-openai, openai), and failing test stubs for all Phase 3 acceptance criteria (completed 2026-03-02)
- [x] 03-02-PLAN.md — LLM analyst rewrite in agents/analyst.py: AnalystOutput schema, compute_color_stats(), call_llm_analyst() with fallback, cold start detection, USE_MOCK_LLM mode
- [x] 03-03-PLAN.md — Policy guard 4th check (check_confidence) and communicator Analysis email section (build_body llm_reasoning param)

### Phase 4: Orchestration
**Goal**: All nodes are wired into a LangGraph StateGraph that runs autonomously on a schedule, requiring no manual trigger after startup
**Depends on**: Phase 3
**Requirements**: SCHD-01
**Success Criteria** (what must be TRUE):
  1. Running `python main.py` starts the system and it polls automatically on the configured hourly interval
  2. The full pipeline (SNMP poll -> analyst -> policy guard -> communicator) executes end-to-end without manual intervention
  3. The system continues running across multiple polling cycles without crashing or leaking state
**Plans**: 2 plans

Plans:
- [x] 04-01-PLAN.md — LangGraph StateGraph wiring in supervisor.py (build_graph + conditional edges), APScheduler dependency, POLL_INTERVAL_MINUTES env var (completed 2026-03-02)
- [ ] 04-02-PLAN.md — main.py entry point: env validation, startup banner, BackgroundScheduler with immediate first poll, error boundary, graceful shutdown; tests/test_main.py

### Phase 5: Web Chat Interface
**Goal**: A QC engineer can interact with Sentinel through a browser-based chat, querying status, history, and triggering actions conversationally
**Depends on**: Phase 4
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05
**Success Criteria** (what must be TRUE):
  1. A QC engineer can open a browser to a local URL and see a chat interface
  2. Asking "What are the current toner levels?" returns a live SNMP reading with per-color (CMYK) percentages
  3. Asking "What alerts fired this week?" returns results drawn from the history log
  4. Asking "Why was the last alert suppressed?" returns a plain-language explanation of the Policy Guard decision (rate limit / confidence / data quality)
  5. The QC engineer can type "Run a check now" and the monitoring pipeline executes on-demand, bypassing the hourly schedule
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 2/3 | In Progress (checkpoint) | - |
| 2. Monitoring Pipeline | 3/3 | Complete    | 2026-03-01 |
| 3. LLM Analyst | 3/3 | Complete    | 2026-03-02 |
| 4. Orchestration | 1/2 | In Progress | - |
| 5. Web Chat Interface | 0/? | Not started | - |
