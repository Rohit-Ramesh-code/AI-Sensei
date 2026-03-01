# Phase 2: Monitoring Pipeline - Context

**Gathered:** 2026-03-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Threshold-based toner monitoring with policy-gated alert emails. When any CMYK color drops below a configurable threshold, the system detects it, checks policy rules (rate limit + data quality), and sends a plain-text alert email. No LLM dependency — this is a fully deterministic pipeline.

Creating posts, LLM-based trend analysis, and confidence scoring are out of scope for this phase.

</domain>

<decisions>
## Implementation Decisions

### Threshold logic
- Strict less-than comparison: alert fires when `toner_pct < threshold` (not ≤)
- Single global threshold for all four CMYK colors — configurable via `TONER_ALERT_THRESHOLD` env var, default 20%
- `BELOW_LOW_THRESHOLD` sentinel (SNMP -3) is treated as **alert-worthy**: the printer is reporting "some toner remains but unquantified" — escalate as Critical urgency, show "below low threshold (unquantified)" instead of a percentage
- When multiple colors are low in the same poll cycle, send **one email** listing all flagged colors (not one email per color)

### Alert email content
- Two urgency levels:
  - **Warning**: `toner_pct < TONER_ALERT_THRESHOLD` (e.g., < 20%) but `≥ TONER_CRITICAL_THRESHOLD` (e.g., ≥ 10%)
  - **Critical**: `toner_pct < TONER_CRITICAL_THRESHOLD` (e.g., < 10%), or `BELOW_LOW_THRESHOLD` sentinel
  - Both thresholds configurable via `.env`; defaults: alert=20%, critical=10%
- Subject format: `[Sentinel] CRITICAL: Printer toner low — Cyan 8%, Yellow unquantified`
  (urgency is the highest level among flagged colors; color names and values inline)
- Body: minimal, facts-only
  - Printer host/name
  - Each low color: color name, current % or "below low threshold (unquantified)", urgency level
  - Recommended action: "Order [color] toner"
- Plain text only — `SMTPAdapter.send_alert()` is used as-is, no HTML

### Rate limit tracking
- Separate lightweight JSON state file: `logs/alert_state.json`
  - Structure: `{ "printer_host": { "last_alert_timestamp": "ISO 8601 string" } }`
  - Fast O(1) lookup — no history scanning needed
- Rolling 24-hour window: `(now - last_alert_timestamp) >= 24 hours`
- Scope: **per-printer** (not per-color). One alert per printer per 24h regardless of which colors are flagged
- Suppressed alerts appended to `logs/printer_history.jsonl` with:
  `reason="rate_limit"`, `last_alert_time`, `triggering_colors`, `timestamp`

### Stale data handling
- Staleness check lives in the **Policy Guard** (not the SNMP adapter)
- A poll result is stale when `(now - poll_result["timestamp"]) > STALE_THRESHOLD_MINUTES`
- `STALE_THRESHOLD_MINUTES` env var, default = 2× poll interval = **120 minutes**
- Stale data suppresses the alert and logs to `printer_history.jsonl`:
  `reason="stale_data"`, `poll_timestamp`, `current_time`, `age_minutes`
- `QualityFlag.STALE` is set by the Policy Guard's data quality check before deciding

### Claude's Discretion
- Exact format of the suppression log record fields (beyond reason, timestamp, triggering data)
- How `TONER_ALERT_THRESHOLD` and `TONER_CRITICAL_THRESHOLD` are loaded and validated from `.env`
- Internal function decomposition within `safety_logic.py` and `analyst.py`
- Error handling for corrupted or missing `alert_state.json`

</decisions>

<specifics>
## Specific Ideas

- Phase 2 ANLZ-01 maps to a **deterministic threshold checker** (not an LLM) — the LLM analyst is Phase 3. The `agents/analyst.py` stub in Phase 2 should implement pure threshold comparison logic.
- ALRT-02 in requirements mentions "LLM confidence score and LLM reasoning" — those fields are Phase 3 additions. Phase 2 alert email omits them.
- The `AgentState` TypedDict already has `alert_needed`, `alert_sent`, `suppression_reason`, `decision_log` — use these as-is, no new state fields needed for Phase 2.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `state_types.py` → `QualityFlag`, `TonerReading`, `PollResult`, `AgentState` — import directly; no redefinition
- `adapters/smtp_adapter.py` → `SMTPAdapter.send_alert(recipient, subject, body)` — works and tested; use as-is
- `adapters/persistence.py` → `append_poll_result(result, log_path)` and `read_poll_history(log_path)` — use for suppression logging
- `adapters/snmp_adapter.py` → `SNMPAdapter.poll()` — returns `PollResult`; mock mode available via `USE_MOCK_SNMP=true`

### Established Patterns
- Mock mode via env var: `USE_MOCK_SNMP=true`, `USE_MOCK_SMTP=true` — follow the same pattern for any new mock flags
- SNMP adapter never raises — transport failures return `PollResult` with `snmp_error` set; downstream code checks `snmp_error` and `overall_quality_ok`
- `QualityFlag` is a `str` Enum — `.value` is always a plain JSON-serializable string; no custom encoder needed
- JSONL persistence: always `mode='a'`; never `mode='w'`; parent dirs created via `parents=True, exist_ok=True`

### Integration Points
- `guardrails/safety_logic.py` — stub file, implement the Policy Guard here
- `agents/analyst.py` — stub file, implement deterministic threshold checker here
- `agents/communicator.py` — stub file, implement email dispatch here
- `agents/supervisor.py` — stub file; Phase 2 can be a simple sequential function (no LangGraph graph wiring needed — that's Phase 4)
- New file: `logs/alert_state.json` — rate limit state; create on first alert send

</code_context>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-monitoring-pipeline*
*Context gathered: 2026-03-01*
