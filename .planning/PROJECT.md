# Project Sentinel

## What This Is

Project Sentinel is a Python-based AI monitoring system that uses SNMP to pull real-time toner and supply capacity data from a Lexmark XC2235 printer, analyzes it through a LangGraph multi-agent pipeline, and sends proactive maintenance alerts via Microsoft Exchange (EWS). It is built to scale to a fleet but starts with a single printer.

## Core Value

Predict printer supply depletion before it happens — alerting the right person with enough lead time to act.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] SNMP adapter pulls live toner % and supply capacity from Lexmark XC2235
- [ ] Monitor Agent tracks toner level trends over time
- [ ] LLM Analyst Agent produces threshold-based alert + time-to-depletion estimate
- [ ] LLM Analyst self-reports confidence score alongside analysis
- [ ] Communicator Agent sends alert email via EWS to a designated recipient
- [ ] Alert email includes: toner %, time-to-depletion estimate, confidence score, recommended action
- [ ] Policy Guard enforces rate limiting (1 alert/day/printer)
- [ ] Policy Guard enforces confidence threshold (LLM self-score ≥ threshold AND data quality check)
- [ ] Suppressed alerts are logged with reason
- [ ] System runs on a scheduled polling interval (e.g., hourly)
- [ ] All agent decisions and actions logged to printer_history.json

### Out of Scope

- Inbound email reading / EWS command processing — not needed for v1
- Web dashboard or status UI — alerts are sufficient for v1
- Multi-printer fleet management UI — architecture supports it, UI deferred
- OAuth/external auth for Exchange — service account credentials sufficient

## Context

- **Existing scaffolding**: All source files exist as empty scaffolds. No implementation yet.
- **Framework**: LangGraph for multi-agent orchestration. Agents are graph nodes; data flows SNMP → Monitor → Analyst → Policy Guard → Communicator.
- **Target device**: Lexmark XC2235 via SNMP community string.
- **Email transport**: Microsoft Exchange Web Services (EWS) — outbound only via service account.
- **Alert recipient**: Single designated admin/manager (configurable via env var).
- **Scalability**: SNMP adapter and agent pipeline designed to support multiple printers; v1 is one device.

## Constraints

- **Tech Stack**: Python, LangGraph, pysnmp (or equivalent), exchangelib (EWS) — no rewrite of existing scaffold structure
- **Security**: Credentials in `.env` only — never committed. Exchange uses service account.
- **Guardrails**: Policy Guard must be implemented before Communicator is wired up
- **Implementation Order**: adapters → guardrails → agents → main.py (dependencies flow this direction)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LangGraph for agent orchestration | Structured graph-based pipeline with clear node boundaries | — Pending |
| EWS outbound only (no inbound) | v1 only needs to send alerts; reading email adds complexity | — Pending |
| 1 alert/day/printer rate limit | Prevent alert fatigue; one actionable alert per day is sufficient | — Pending |
| Confidence threshold = LLM score + data quality | Two-layer check catches both bad reasoning and bad data | — Pending |
| Single alert recipient (env var) | Simple for v1; fleet/multi-recipient can be v2 | — Pending |

---
*Last updated: 2026-02-28 after initialization*
