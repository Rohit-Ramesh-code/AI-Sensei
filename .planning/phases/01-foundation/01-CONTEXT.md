# Phase 1: Foundation - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the infrastructure layer that all later phases depend on: an SNMP adapter that polls the Lexmark XC2235 for per-color (CMYK) toner data, an EWS adapter that sends email through Exchange, Python state type definitions (the data contract for all downstream nodes), and a JSON Lines persistence log that records every poll result.

Creating posts, running agents, and scheduling are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Sentinel value encoding
- SNMP sentinel values (-2, -3) are represented as a typed Python **enum**: `QualityFlag.NOT_INSTALLED`, `QualityFlag.NOT_SUPPORTED`, `QualityFlag.OK`, etc.
- Downstream nodes pattern-match on the enum, not on raw integers or magic strings
- The adapter never passes raw sentinel integers to callers

### Persistence log fields
- Format: JSON Lines (one JSON object per line, newline-delimited)
- Each entry includes: toner percentage per color, quality flag per color, ISO 8601 timestamp, raw SNMP integer value per color, printer IP/hostname, and any SNMP error message
- Both valid and invalid poll results are logged (quality flag distinguishes them)

### State type approach
- Use Python **TypedDict** for all state definitions
- No Pydantic, no dataclasses — TypedDict is native to LangGraph and adds zero dependencies
- Types must be importable by downstream modules (agents, guardrails)

### Dev/test strategy
- Env-flag stub mode: `USE_MOCK_SNMP=true` in `.env` causes the SNMP adapter to return hardcoded fixture data instead of querying the real printer
- Similarly `USE_MOCK_EWS=true` for the EWS adapter (logs the email instead of sending)
- Without mock flags, adapters fail fast with a clear error message if the target is unreachable

### Claude's Discretion
- Exact OIDs used to query toner levels from the Lexmark XC2235
- Internal SNMP library choice (pysnmp, easysnmp, etc.)
- EWS library choice (exchangelib, etc.)
- Exact field names and Python module layout within adapters/
- Stub fixture values used in mock mode
- Log file location and rotation behavior

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- None yet — all source files are empty stubs. Everything in this phase is built from scratch.

### Established Patterns
- Architecture is defined in CLAUDE.md: adapters/ isolate external systems, agents/ consume normalized data from adapters, guardrails/ gate outbound actions
- Entry point: main.py; adapter modules: adapters/snmp_adapter.py and adapters/ews_scraper.py

### Integration Points
- State types defined here are imported by agents/analyst.py, agents/communicator.py, and agents/supervisor.py in later phases
- JSON Lines log at logs/printer_history.json is read by the policy guard and supervisor in Phase 2+
- The mock env flags (USE_MOCK_SNMP, USE_MOCK_EWS) must be documented in .env.example for other phases to rely on

</code_context>

<specifics>
## Specific Ideas

- No specific references — open to standard SNMP and EWS library approaches
- The QualityFlag enum should be expressive enough that the Phase 2 policy guard can reason about data validity without re-parsing raw values

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-02-28*
