# Requirements: Project Sentinel

**Defined:** 2026-02-28
**Core Value:** Predict printer supply depletion before it happens — alerting the right person with enough lead time to act.

## v1 Requirements

### SNMP Data Collection

- [ ] **SNMP-01**: System polls Lexmark XC2235 for toner percentage per color (Cyan, Magenta, Yellow, Black) via SNMP on a scheduled interval
- [ ] **SNMP-02**: SNMP adapter detects and handles Lexmark sentinel values (-2: unknown, -3: below low threshold) and converts them to structured data quality flags rather than raw error values
- [ ] **SNMP-03**: SNMP adapter validates each reading for staleness, null values, and out-of-range results, setting a `data_quality_ok` flag on the output
- [ ] **SNMP-04**: Every poll result (valid or invalid) is persisted to a JSON Lines history log with timestamp and data quality metadata

### LLM Analysis

- [ ] **ANLZ-01**: LLM Analyst Agent triggers an alert recommendation when any toner color drops below a configurable threshold (default 20%)
- [ ] **ANLZ-02**: LLM Analyst Agent self-reports a confidence score (0.0–1.0) alongside its analysis output as a structured field
- [ ] **ANLZ-03**: LLM Analyst Agent produces a natural language explanation of its reasoning that is included in the outbound alert email
- [ ] **ANLZ-04**: LLM Analyst Agent applies trend-aware urgency — fast-dropping toner (high depletion velocity) is flagged with higher urgency than slow decline at the same level

### Policy Guard

- [ ] **GURD-01**: Policy Guard enforces a maximum of 1 alert email per printer per 24-hour window, suppressing duplicates regardless of polling frequency
- [ ] **GURD-02**: Policy Guard blocks alert sending if the LLM Analyst's confidence score falls below the configured minimum threshold (default 0.7)
- [ ] **GURD-03**: Policy Guard blocks alert sending if the SNMP data quality check failed (stale, null, or sentinel value not resolved)
- [ ] **GURD-04**: Every suppressed alert is logged with its suppression reason (rate limit hit / confidence too low / data quality failed) to the history log

### Alerting & Communication

- [ ] **ALRT-01**: Communicator Agent sends alert emails via Microsoft Exchange Web Services (EWS) using a configured service account
- [ ] **ALRT-02**: Alert email includes structured content: printer name, toner color, current percentage, urgency level, LLM confidence score, and LLM reasoning
- [ ] **ALRT-03**: All suppressed alert events are recorded in the history log with reason, timestamp, and the data that triggered the suppression

### Scheduling & Orchestration

- [ ] **SCHD-01**: System runs autonomously on an hourly polling schedule via APScheduler 3.x, requiring no manual trigger after startup

### User Interface

- [ ] **UI-01**: System provides a browser-accessible web chat interface (Flask or FastAPI) through which a Quality Controls engineer can interact with Sentinel conversationally
- [ ] **UI-02**: QC engineer can ask for current toner status and receive a live SNMP reading per color (CMYK) in response
- [ ] **UI-03**: QC engineer can query alert history ("What alerts fired this week?") and receive results drawn from the history log
- [ ] **UI-04**: QC engineer can ask why an alert was suppressed and receive a plain-language explanation of the Policy Guard's decision (rate limit / confidence / data quality)
- [ ] **UI-05**: QC engineer can manually trigger the monitoring pipeline on-demand via the chat interface, bypassing the hourly schedule

## v2 Requirements

### Analysis Enhancements

- **ANLZ-V2-01**: Time-to-depletion estimate ("~X days until [color] runs out") based on historical usage rate, included in alert emails
- **ANLZ-V2-02**: Configurable alert recipient email address via environment variable (v1 uses hardcoded .env value)
- **ANLZ-V2-03**: Configurable polling interval via environment variable (v1 is fixed at hourly)

### Multi-Printer Support

- **MULT-V2-01**: System monitors multiple printers, with per-printer rate limiting and history tracking
- **MULT-V2-02**: Alert emails include printer location/identifier for fleet context

### Operational

- **OPER-V2-01**: Log rotation to cap history file growth
- **OPER-V2-02**: LLM call caching to avoid redundant API calls when toner levels haven't changed

## Out of Scope

| Feature | Reason |
|---------|--------|
| Inbound email reading / EWS command processing | Not needed for v1; adds significant complexity |
| Web dashboard or status UI | Alert emails are sufficient; UI deferred to future |
| Multi-printer fleet management UI | Architecture supports fleet; UI is a separate concern |
| OAuth for Exchange | Use service account Basic Auth/NTLM for on-prem; O365 OAuth if forced by IT |
| Mobile push notifications | Email is the chosen channel for v1 |
| SNMP auto-discovery of printers | Single known device; discovery is a fleet-scale concern |
| Auto-ordering of supplies | Out of scope — alerts inform humans who order |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SNMP-01 | Phase 1 | Pending |
| SNMP-02 | Phase 1 | Pending |
| SNMP-03 | Phase 1 | Pending |
| SNMP-04 | Phase 1 | Pending |
| ALRT-01 | Phase 1 | Pending |
| GURD-01 | Phase 2 | Pending |
| GURD-02 | Phase 3 | Pending |
| GURD-03 | Phase 2 | Pending |
| GURD-04 | Phase 2 | Pending |
| ANLZ-01 | Phase 2 | Pending |
| ANLZ-02 | Phase 3 | Pending |
| ANLZ-03 | Phase 3 | Pending |
| ANLZ-04 | Phase 3 | Pending |
| ALRT-02 | Phase 2 | Pending |
| ALRT-03 | Phase 2 | Pending |
| SCHD-01 | Phase 4 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| UI-04 | Phase 5 | Pending |
| UI-05 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-28*
*Last updated: 2026-02-28 after adding web chat UI requirements*
