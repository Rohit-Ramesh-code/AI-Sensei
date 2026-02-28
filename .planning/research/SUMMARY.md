# Project Research Summary

**Project:** Project Sentinel
**Domain:** SNMP Printer Monitoring + LLM Multi-Agent Analysis + EWS Email Alerting
**Researched:** 2026-02-28
**Confidence:** MEDIUM-HIGH

## Executive Summary

Project Sentinel is a single-printer toner monitoring system that uses SNMP polling, LLM-powered trend analysis, and Exchange email alerts. The expert approach for this domain is a linear pipeline -- not a hub-and-spoke supervisor -- built on LangGraph's StateGraph. The system polls a Lexmark XC2235 printer hourly via SNMP, feeds toner data through an LLM analyst for time-to-depletion prediction, gates alerts through a deterministic policy guard (rate limiting, confidence checks, data quality), and delivers actionable emails via EWS. The stack is well-established: pysnmp 7.x (LeXtudio fork), LangGraph 1.0, exchangelib 5.x, APScheduler 3.x, and pydantic-settings for configuration.

The recommended approach is to build in two major phases: first a working monitoring-and-alert system with no LLM dependency (threshold-based alerts only), then layer on the AI-driven prediction and confidence scoring. This phasing is critical because the AI layer's value depends on accumulated historical data from Phase 1 polling, and because the core monitoring pipeline must be reliable before adding LLM complexity. The two-phase approach also means the system delivers value immediately -- even Phase 1 alone is more useful than checking the printer's LCD panel.

The key risks are: (1) Lexmark SNMP returns sentinel values (-3) below 20% toner, breaking predictions at exactly the moment they matter most -- this must be handled in the adapter layer before anything else; (2) LLM confidence self-scores are poorly calibrated and cannot be trusted as a sole guardrail -- a two-layer system (deterministic data quality + LLM reasoning) is required; (3) Exchange Basic Auth may be blocked if the target server is Office 365 -- this must be validated with IT before writing any EWS code, as it could require OAuth and significantly change the auth setup.

## Key Findings

### Recommended Stack

The stack is mature and well-verified. All core libraries have recent stable releases (late 2025 to Feb 2026) and are actively maintained. There are no risky or experimental dependencies. See `.planning/research/STACK.md` for full rationale and version pins.

**Core technologies:**
- **pysnmp 7.1** (LeXtudio fork): SNMP polling -- the only maintained pure-Python SNMP library, no C compilation needed on Windows
- **LangGraph 1.0**: Agent pipeline orchestration -- graph-based architecture maps directly to the poll-analyze-gate-alert pipeline, supports conditional edges for the policy guard
- **langchain-anthropic 1.3**: Claude LLM integration for the Analyst agent
- **exchangelib 5.6**: EWS email delivery -- the only serious Python EWS client, handles on-prem Exchange and O365
- **APScheduler 3.11**: Hourly polling scheduler -- pin to <4.0 (4.x is alpha with breaking changes)
- **pydantic-settings 2.13**: Type-safe configuration from .env -- eliminates manual os.getenv() with type validation
- **structlog 24.4**: Structured JSON logging for audit trails and printer_history.json

**Critical version pins:** APScheduler <4.0, pysnmp >=7.0, LangGraph >=1.0, Pydantic v2 only.

### Expected Features

**Must have (table stakes):**
- SNMP toner level polling with per-color (CMYK) tracking
- SNMP data validation (handle Lexmark -3 sentinel, timeouts, out-of-range values)
- Threshold-based low toner alerts with configurable threshold (default 20%)
- Actionable alert emails (printer name, supply color, current %, recommended action)
- Alert rate limiting (1 alert per printer per 24 hours)
- Persistent history logging (every poll result stored)
- Scheduled autonomous polling (hourly)

**Should have (differentiators -- these justify the AI architecture):**
- Time-to-depletion estimate from historical trend data (core differentiator)
- LLM confidence scoring with two-layer validation
- Natural language alert reasoning (human-readable analysis for procurement staff)
- Trend-aware alerting (velocity-weighted urgency, not just absolute level)
- Suppression logging with reasons (builds trust in the AI layer)

**Defer to v2+:**
- Multi-supply depletion correlation
- Web dashboard / status UI
- Multi-printer fleet management
- Inbound email command processing
- SNMP auto-discovery
- OAuth for Exchange (unless required by the target server)

See `.planning/research/FEATURES.md` for the full feature dependency tree and anti-features list.

### Architecture Approach

The system is a linear LangGraph StateGraph pipeline with four nodes: monitor -> analyst -> policy_guard -> communicator, plus one conditional edge after the policy guard (send or suppress). Adapters (SNMP, EWS) are plain Python modules called by graph nodes -- they are NOT graph nodes themselves. State flows through a flat TypedDict with explicit reducers for accumulating fields. There is no supervisor agent; the deterministic graph wiring replaces it entirely.

**Major components:**
1. **snmp_adapter** -- Polls Lexmark XC2235 via pysnmp, returns normalized dicts with data quality flags
2. **ews_adapter** -- Sends formatted alert emails via exchangelib, explicit server config (no autodiscover)
3. **monitor_node** -- Calls SNMP adapter, validates data, manages trend history, sets data_quality_ok flag
4. **analyst_node** -- LLM-powered analysis with structured output (Pydantic model), produces confidence score and time-to-depletion
5. **policy_guard_node** -- Deterministic gate: rate limit + confidence threshold + data quality check. Pure Python, no LLM.
6. **communicator_node** -- Formats and sends alert email if approved; logs suppression if not
7. **graph.py** -- StateGraph definition, separate from main.py for testability
8. **main.py** -- APScheduler entry point, loads config, invokes compiled graph on interval

**Key architectural decisions:**
- `supervisor.py` from the scaffold should be repurposed as graph.py or monitor.py -- a separate supervisor agent adds no value in a linear pipeline
- `state.py` lives at project root to avoid circular imports
- Adapters return typed dicts, never raw protocol objects
- Policy guard is a graph node (not middleware), making its decisions visible and testable

See `.planning/research/ARCHITECTURE.md` for full state schema, graph wiring code, and anti-patterns.

### Critical Pitfalls

1. **Lexmark SNMP sentinel values below 20% toner** -- Probe the real device with snmpwalk before writing any parsing code. Handle -2 (unknown) and -3 (low threshold) as structured signals with data quality flags. Check for "SNMP Compatibility Mode" setting on the printer.

2. **LLM confidence scores are unreliable** -- Do not rely solely on LLM self-reported confidence. Implement deterministic data quality scoring (data freshness, value range, history depth) alongside LLM reasoning. Use structured output to force specific fields rather than free-text confidence claims.

3. **Exchange Basic Auth may be blocked** -- Confirm with IT whether the Exchange server is on-prem or O365 and whether Basic Auth/NTLM is enabled BEFORE writing any EWS code. If O365, OAuth is mandatory and requires Azure AD app registration.

4. **LangGraph state overwrites instead of accumulating** -- Use `Annotated[list, add]` reducers on list fields (log_entries, reading_history). Without explicit reducers, returning a list from a node replaces the previous value instead of appending.

5. **JSON log file corruption and unbounded growth** -- Use JSON Lines format (.jsonl) instead of a single JSON array. Implement atomic writes (write to temp file, then rename). Add log rotation to cap history size.

See `.planning/research/PITFALLS.md` for all 14 pitfalls with full prevention strategies.

## Implications for Roadmap

Based on combined research, the project should be built in 5 phases following the dependency chain identified in ARCHITECTURE.md and the two-stage MVP recommendation from FEATURES.md.

### Phase 1: Foundation -- State Types, Adapters, and Persistence

**Rationale:** Everything depends on the state schema and adapters. Adapters have zero internal dependencies and can be tested against real hardware immediately. The SNMP adapter is where the most critical pitfall (sentinel values) must be resolved. EWS connectivity must be validated to confirm the email pipeline is viable.
**Delivers:** Validated SNMP polling with data quality flags, validated EWS email sending, state type definitions, JSON Lines persistence layer with atomic writes.
**Addresses features:** SNMP toner level polling, per-color tracking, SNMP data validation, persistent history logging.
**Avoids pitfalls:** Lexmark sentinel values (Pitfall 1), wrong pysnmp package (Pitfall 3), Exchange Basic Auth blocked (Pitfall 4), SNMP timeouts (Pitfall 7), autodiscover failures (Pitfall 12), community string exposure (Pitfall 11), JSON corruption (Pitfall 10).

### Phase 2: Monitoring Pipeline -- Monitor Node, Policy Guard, Communicator

**Rationale:** With adapters validated, build the deterministic pipeline nodes. The policy guard must exist before the communicator (project constraint from CLAUDE.md). This phase delivers a working threshold-based alerting system with no LLM dependency.
**Delivers:** Complete monitoring pipeline: poll -> threshold check -> rate limit -> email alert. Working system that provides immediate value.
**Addresses features:** Threshold-based low toner alerts, alert rate limiting, actionable alert content, email alert delivery, scheduled polling.
**Avoids pitfalls:** Rate limiting state lost on restart (Pitfall 8), timezone bugs (Pitfall 13).

### Phase 3: LLM Analyst Integration

**Rationale:** The AI layer depends on historical data accumulated by Phase 2 polling. This phase adds the LLM analyst node with structured output, confidence scoring, and the change-detection gate to avoid unnecessary LLM calls.
**Delivers:** LLM-powered trend analysis, time-to-depletion estimates, natural language reasoning in alerts.
**Addresses features:** Time-to-depletion estimate, LLM confidence scoring, natural language alert reasoning, trend-aware alerting.
**Avoids pitfalls:** LLM confidence miscalibration (Pitfall 2), LangGraph state overwrites (Pitfall 5), unnecessary LLM calls (Pitfall 9).

### Phase 4: Graph Wiring and Orchestration

**Rationale:** All nodes exist and are individually tested. Wire them into the LangGraph StateGraph, add the conditional edge at the policy guard, and integrate with APScheduler in main.py.
**Delivers:** Complete end-to-end pipeline running on a schedule. Full suppression logging with reasons.
**Addresses features:** Suppression logging with reasons, autonomous scheduled operation.
**Avoids pitfalls:** Graph compilation errors (Pitfall 14), APScheduler missed jobs (Pitfall 6).

### Phase 5: Hardening and Optimization

**Rationale:** With the system running end-to-end, add production hardening: LLM call caching/change detection, log rotation, error recovery, and monitoring of the monitor itself.
**Delivers:** Production-ready system with cost optimization, error resilience, and operational visibility.
**Addresses features:** Remaining robustness concerns from pitfalls research.

### Phase Ordering Rationale

- Adapters first because they have zero internal dependencies and contain the highest-risk unknowns (Lexmark SNMP behavior, Exchange auth type)
- Policy guard before communicator because CLAUDE.md explicitly requires guardrails to exist before outbound actions
- LLM analyst after monitor because trend analysis requires accumulated historical data and because Phase 2 delivers standalone value without AI
- Graph wiring last because it imports all nodes -- all pieces must exist first
- This ordering means Phase 2 delivers a working product; Phases 3-5 are incremental improvements

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (SNMP Adapter):** Must do a live snmpwalk of the Lexmark XC2235 to document actual OID values and sentinel behavior. Research alone cannot resolve device-specific behavior.
- **Phase 1 (EWS Adapter):** Must confirm Exchange server type and auth requirements with IT. If OAuth is required, the EWS adapter design changes significantly.
- **Phase 3 (LLM Analyst):** Prompt engineering for structured output and confidence calibration will require iteration. The two-layer confidence system needs design-time research into what "data quality" metrics to compute.

Phases with standard patterns (skip deeper research):
- **Phase 2 (Monitor, Guard, Communicator):** Well-documented patterns. Threshold comparison, rate limiting, and email formatting are straightforward.
- **Phase 4 (Graph Wiring):** LangGraph StateGraph wiring is well-documented with examples in the architecture research. Build incrementally.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All libraries verified on PyPI with recent releases. No experimental dependencies. Version pins are well-justified. |
| Features | MEDIUM-HIGH | Table stakes are clear from domain analysis. Differentiators (AI prediction) are the novel part with less precedent. |
| Architecture | HIGH | Linear pipeline pattern is well-documented in LangGraph. State schema and graph wiring have concrete code examples. |
| Pitfalls | HIGH | Critical pitfalls backed by official docs, academic papers, and community reports. Lexmark-specific behavior needs device validation. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Lexmark XC2235 actual SNMP behavior:** Research confirms sentinel values exist for Lexmark printers generally, but the exact behavior of the XC2235 model (which OIDs return useful data, whether SNMP Compatibility Mode is available) must be validated against the physical device during Phase 1.
- **Exchange server auth type:** Whether Basic Auth or OAuth is required is an IT infrastructure question, not a research question. Must be answered before Phase 1 EWS work begins.
- **LLM confidence calibration strategy:** The research establishes that LLM self-scores are unreliable but does not prescribe a specific calibration approach for this domain. Phase 3 planning should research calibration techniques specific to structured numeric prediction tasks.
- **Trend data volume needed for useful predictions:** How many hourly data points does the LLM need before time-to-depletion estimates become meaningful? This is an empirical question that Phase 2 operation will answer, informing Phase 3 design.

## Sources

### Primary (HIGH confidence)
- [LangGraph PyPI v1.0.10](https://pypi.org/project/langgraph/) -- stable release, graph API
- [LangGraph GitHub and documentation](https://docs.langchain.com/oss/python/langgraph/graph-api) -- StateGraph patterns, conditional edges
- [pysnmp PyPI v7.1.22](https://pypi.org/project/pysnmp/) -- LeXtudio maintained fork
- [PySNMP 7.1 Documentation](https://docs.lextudio.com/pysnmp/v7.1/index.html) -- hlapi usage
- [exchangelib PyPI v5.6.0](https://pypi.org/project/exchangelib/) -- EWS client
- [APScheduler PyPI v3.11.2](https://pypi.org/project/APScheduler/) -- scheduler with persistence
- [On Verbalized Confidence Scores for LLMs (arXiv 2412.14737)](https://arxiv.org/pdf/2412.14737) -- LLM calibration research
- [exchangelib GitHub discussions #1021, #1050](https://github.com/ecederstrand/exchangelib/discussions/1021) -- Auth issues

### Secondary (MEDIUM confidence)
- [ManageEngine OpManager](https://www.manageengine.com/network-monitoring/printer-monitoring.html) -- feature landscape baseline
- [Lexmark SNMP MIBs and OID Values](https://support.lexmark.com/en_us/printers/printer/E462/article/FA615.html) -- sentinel value documentation (not XC2235-specific)
- [LangGraph State Management best practices](https://medium.com/@bharatraj1918/langgraph-state-management-part-1-how-langgraph-manages-state-for-multi-agent-workflows-da64d352c43b) -- reducer patterns
- [5 Methods for Calibrating LLM Confidence Scores](https://latitude.so/blog/5-methods-for-calibrating-llm-confidence-scores) -- practical calibration

### Tertiary (needs validation)
- Lexmark XC2235 specific SNMP behavior -- must be validated against physical device
- Exchange server auth requirements -- must be confirmed with IT

---
*Research completed: 2026-02-28*
*Ready for roadmap: yes*
