# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Project Sentinel** is a Python-based multi-agent monitoring and analysis system. It uses SNMP to pull real-time toner and supply capacity data from a Lexmark XC2235 printer, analyzes it through a LangGraph multi-agent framework, and sends proactive maintenance alerts via SMTP email (Outlook / Office 365). A Policy Guard layer enforces safety rules before any outbound action is taken.

**Core Value:** Predict printer supply depletion before it happens — alerting the right person with enough lead time to act.

## Target Hardware

- **Printer**: Lexmark XC2235 (single device for v1, architecture supports fleet)
- **Protocol**: SNMP — pulls toner percentage and supply capacity in real time
- **Polling interval**: Scheduled (e.g., hourly)

## Architecture

```
main.py                     # Entry point — orchestrates startup and scheduler
agents/
  supervisor.py             # LangGraph orchestrator — coordinates agent pipeline
  analyst.py                # LLM Analyst Agent — predicts maintenance needs
  communicator.py           # Communicator Agent — sends email alerts via SMTP
adapters/
  smtp_adapter.py           # SMTP adapter — outbound alert emails via Outlook/Office 365
  snmp_adapter.py           # SNMP adapter — pulls toner/capacity from Lexmark XC2235
guardrails/
  safety_logic.py           # Policy Guard — enforces rate limits and confidence thresholds
logs/
  printer_history.json      # Persistent log of agent decisions and actions
```

## Agent Roles

### Monitor Agent (supervisor.py)
- Polls the SNMP adapter on a schedule (e.g., hourly)
- Tracks toner level trends over time
- Triggers the LLM Analyst when data is fresh and valid

### LLM Analyst Agent (analyst.py)
- Receives current toner % and historical trend data
- Produces two outputs:
  1. **Threshold check**: Has toner dropped below a defined threshold (e.g., 20%)?
  2. **Time-to-depletion estimate**: "Toner will run out in approximately X days" (based on usage rate)
- Self-reports a confidence score (0.0–1.0) alongside its analysis
- Output is passed to the Policy Guard before any alert is sent

### Communicator Agent (communicator.py)
- Sends alert emails through a configured Outlook account via SMTP (smtp.office365.com:587)
- Email recipient: a single designated admin/manager (configurable)
- Alert email includes: current toner %, time-to-depletion estimate, confidence score, and recommended action
- Only executes after Policy Guard clears the action

## Policy Guard (guardrails/safety_logic.py)

All outbound actions from the Communicator Agent must pass through the Policy Guard. It enforces:

1. **Rate Limiting**: Maximum 1 alert email per printer per 24-hour window. Prevents alert spam regardless of how often the system polls.

2. **Confidence Threshold**: Two-part check:
   - **LLM confidence**: The Analyst's self-reported score must meet a minimum threshold (e.g., ≥ 0.7) before the alert is sent
   - **Data quality**: SNMP data must be fresh and plausible (not stale, null, or out-of-range values)

If either check fails, the alert is suppressed and the event is logged.

## Key Design Principles

- **Adapter Pattern**: `adapters/` isolate external system specifics from agent logic. Agents consume normalized data from adapters.
- **LangGraph Pipeline**: `supervisor.py` is the LangGraph graph orchestrator. Agents are nodes. Data flows: SNMP → Monitor → Analyst → Policy Guard → Communicator.
- **Guardrails First**: The Policy Guard gates ALL outbound actions. `communicator.py` never sends without clearance.
- **Persistent Logging**: Every decision (alerts sent, alerts suppressed, policy violations) is recorded to `logs/printer_history.json`.
- **Scalable by Design**: SNMP adapter and agent pipeline are designed to support multiple printers. v1 targets one device.

## v1 Scope

- [x] SNMP adapter pulling live toner/capacity data from Lexmark XC2235
- [x] LangGraph agent pipeline (Monitor → Analyst → Communicator)
- [x] Threshold-based alerts + time-to-depletion estimate in alert email
- [x] SMTP outbound email to a designated recipient (Outlook / Office 365)
- [x] Policy Guard: rate limiting (1/day/printer) + confidence threshold
- [x] Scheduled polling (hourly via scheduler in main.py)
- [x] Persistent logging of all decisions

## Out of Scope (v1)

- Inbound email reading
- Web dashboard or status UI
- Multi-printer fleet management UI
- Mobile notifications

## Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

Environment variables go in `.env` (loaded via `python-dotenv`). Do not commit `.env`.

Required `.env` keys (to be documented as implemented):
- `SNMP_HOST` — IP address of the Lexmark XC2235
- `SNMP_COMMUNITY` — SNMP community string
- `SMTP_HOST` — SMTP server hostname (default: smtp.office365.com)
- `SMTP_PORT` — SMTP port (default: 587)
- `SMTP_USERNAME` — Your Outlook email address
- `SMTP_PASSWORD` — Your Outlook password or App Password
- `ALERT_RECIPIENT` — Email address of the designated admin
- `LLM_CONFIDENCE_THRESHOLD` — Minimum confidence score (e.g., 0.7)

## Implementation Order

1. `adapters/snmp_adapter.py` — no dependencies, start here
2. `adapters/smtp_adapter.py` — no dependencies
3. `guardrails/safety_logic.py` — depends only on config/logs
4. `agents/analyst.py` — depends on SNMP data shape
5. `agents/communicator.py` — depends on SMTP adapter + guardrails
6. `agents/supervisor.py` — LangGraph graph wiring all agents
7. `main.py` — scheduler + startup orchestration
