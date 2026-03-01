# Phase 2: Monitoring Pipeline - Research

**Researched:** 2026-03-01
**Domain:** Python deterministic threshold monitoring — policy guard, alert email, suppression logging
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Threshold logic**
- Strict less-than comparison: alert fires when `toner_pct < threshold` (not ≤)
- Single global threshold for all four CMYK colors — configurable via `TONER_ALERT_THRESHOLD` env var, default 20%
- `BELOW_LOW_THRESHOLD` sentinel (SNMP -3) is treated as alert-worthy: the printer is reporting "some toner remains but unquantified" — escalate as Critical urgency, show "below low threshold (unquantified)" instead of a percentage
- When multiple colors are low in the same poll cycle, send ONE email listing all flagged colors (not one email per color)

**Alert email content**
- Two urgency levels:
  - **Warning**: `toner_pct < TONER_ALERT_THRESHOLD` (e.g., < 20%) but `>= TONER_CRITICAL_THRESHOLD` (e.g., >= 10%)
  - **Critical**: `toner_pct < TONER_CRITICAL_THRESHOLD` (e.g., < 10%), or `BELOW_LOW_THRESHOLD` sentinel
  - Both thresholds configurable via `.env`; defaults: alert=20%, critical=10%
- Subject format: `[Sentinel] CRITICAL: Printer toner low — Cyan 8%, Yellow unquantified`
  (urgency is the highest level among flagged colors; color names and values inline)
- Body: minimal, facts-only
  - Printer host/name
  - Each low color: color name, current % or "below low threshold (unquantified)", urgency level
  - Recommended action: "Order [color] toner"
- Plain text only — `SMTPAdapter.send_alert()` is used as-is, no HTML

**Rate limit tracking**
- Separate lightweight JSON state file: `logs/alert_state.json`
  - Structure: `{ "printer_host": { "last_alert_timestamp": "ISO 8601 string" } }`
  - Fast O(1) lookup — no history scanning needed
- Rolling 24-hour window: `(now - last_alert_timestamp) >= 24 hours`
- Scope: per-printer (not per-color). One alert per printer per 24h regardless of which colors are flagged
- Suppressed alerts appended to `logs/printer_history.jsonl` with:
  `reason="rate_limit"`, `last_alert_time`, `triggering_colors`, `timestamp`

**Stale data handling**
- Staleness check lives in the Policy Guard (not the SNMP adapter)
- A poll result is stale when `(now - poll_result["timestamp"]) > STALE_THRESHOLD_MINUTES`
- `STALE_THRESHOLD_MINUTES` env var, default = 2x poll interval = 120 minutes
- Stale data suppresses the alert and logs to `printer_history.jsonl`:
  `reason="stale_data"`, `poll_timestamp`, `current_time`, `age_minutes`
- `QualityFlag.STALE` is set by the Policy Guard's data quality check before deciding

### Claude's Discretion
- Exact format of the suppression log record fields (beyond reason, timestamp, triggering data)
- How `TONER_ALERT_THRESHOLD` and `TONER_CRITICAL_THRESHOLD` are loaded and validated from `.env`
- Internal function decomposition within `safety_logic.py` and `analyst.py`
- Error handling for corrupted or missing `alert_state.json`

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ANLZ-01 | LLM Analyst Agent triggers an alert recommendation when any toner color drops below a configurable threshold (default 20%) | Phase 2 implements this as a deterministic threshold checker in `agents/analyst.py` — no LLM. Threshold comparison pattern: `toner_pct < threshold` (strict). BELOW_LOW_THRESHOLD sentinel also triggers alert. |
| GURD-01 | Policy Guard enforces a maximum of 1 alert email per printer per 24-hour window, suppressing duplicates regardless of polling frequency | Rate limit state in `logs/alert_state.json` with per-printer ISO 8601 timestamp. Rolling 24h window check using `datetime.fromisoformat()` and `timedelta(hours=24)`. |
| GURD-03 | Policy Guard blocks alert sending if SNMP data quality check failed (stale, null, or sentinel value not resolved) | Staleness check: parse `poll_result["timestamp"]`, compare to `now()`, suppress if age > `STALE_THRESHOLD_MINUTES`. Also block if `snmp_error` is set on `PollResult`. |
| GURD-04 | Every suppressed alert is logged with its suppression reason (rate limit hit / confidence too low / data quality failed) to the history log | Use existing `append_poll_result()` from `adapters/persistence.py` with a suppression record dict. Fields: `reason`, `timestamp`, `printer_host`, plus context-specific fields. |
| ALRT-02 | Alert email includes structured content: printer name, toner color, current percentage, urgency level, LLM confidence score, and LLM reasoning | Phase 2 omits LLM confidence and LLM reasoning (Phase 3 additions). Implements: printer host, each flagged color with % or "unquantified", urgency level per color, overall urgency in subject. |
| ALRT-03 | All suppressed alert events are recorded in the history log with reason, timestamp, and the data that triggered the suppression | Suppression records written via `append_poll_result()` to `logs/printer_history.jsonl`. Record must include: `event_type="suppressed_alert"`, `reason`, `timestamp`, triggering data. |
</phase_requirements>

---

## Summary

Phase 2 builds the complete monitoring pipeline as a deterministic system — no LLM involved. The architecture is a simple sequential function chain: poll result enters `agents/analyst.py` for threshold comparison, passes to `guardrails/safety_logic.py` for policy checks (rate limit + staleness), and if cleared, `agents/communicator.py` sends the alert via the existing `SMTPAdapter`. All four stub files (`analyst.py`, `safety_logic.py`, `communicator.py`, `supervisor.py`) are empty and need to be implemented from scratch.

The codebase already has all the primitive infrastructure needed: `state_types.py` defines `AgentState`, `QualityFlag`, `PollResult`, and `TonerReading`; `adapters/smtp_adapter.py` handles email sending with mock mode; `adapters/persistence.py` handles JSONL append; `adapters/snmp_adapter.py` provides poll results with mock mode. Phase 2 wires these together with business logic — threshold comparison, two-tier urgency, per-printer rate limiting in a JSON state file, and staleness detection.

The supervisor for Phase 2 is explicitly scoped to be a simple sequential function — LangGraph graph wiring is deferred to Phase 4. This means `supervisor.py` just calls each agent function in order and passes the shared `AgentState` dict between them.

**Primary recommendation:** Implement four sequential Python functions (analyst, policy guard, communicator, supervisor) that consume the established `AgentState` TypedDict contract and reuse the existing adapter layer without modification.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `json` | builtin | Read/write `logs/alert_state.json` rate-limit state | No external dep; dict is O(1) keyed by printer_host |
| Python stdlib `datetime` | builtin | ISO 8601 timestamp parsing, 24h window arithmetic | `datetime.fromisoformat()` + `timedelta(hours=24)` |
| Python stdlib `os` / `python-dotenv` | installed | Load env vars: `TONER_ALERT_THRESHOLD`, `TONER_CRITICAL_THRESHOLD`, `STALE_THRESHOLD_MINUTES`, `ALERT_RECIPIENT` | Established project pattern |
| `adapters/smtp_adapter.py` | project | Send plain-text alert emails | Already implemented, tested, working |
| `adapters/persistence.py` | project | Append suppression records to `printer_history.jsonl` | Already implemented, tested, working |
| `state_types.py` | project | `AgentState`, `QualityFlag`, `PollResult`, `TonerReading` TypedDicts | Already defined; no redefinition allowed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `jsonlines` | >=4.0.0 | Used internally by `persistence.py` | Do NOT call directly — use `append_poll_result()` |
| Python stdlib `pathlib` | builtin | File path construction for `alert_state.json` | Follow `persistence.py` pattern: `Path("logs/alert_state.json")` |
| `logging` | builtin | Module-level logger per file | Every module already uses `logger = logging.getLogger(__name__)` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `json` stdlib for alert_state.json | SQLite | SQLite is overkill for a single-key lookup; JSON file is sufficient and simpler |
| Per-printer JSON key in alert_state.json | Separate file per printer | Per-printer key in one file is easier for v1 single-printer; multi-printer is v2 |
| Sequential function in supervisor.py | LangGraph StateGraph | LangGraph graph wiring is Phase 4; sequential function avoids dependency for now |

**Installation:** No new packages needed. All required libraries are in `requirements.txt` already.

---

## Architecture Patterns

### Recommended Project Structure

All new code goes into the four stub files. No new directories needed.

```
agents/
  analyst.py        # Deterministic threshold checker — reads AgentState, sets alert_needed
  communicator.py   # Email dispatch — reads AgentState, calls SMTPAdapter.send_alert()
  supervisor.py     # Sequential coordinator — calls analyst -> policy_guard -> communicator
guardrails/
  safety_logic.py   # Policy Guard — rate limit + staleness checks, sets suppression_reason
logs/
  alert_state.json  # Rate-limit state (created on first alert send; not in git)
  printer_history.jsonl  # Existing JSONL log (suppression records appended here)
```

### Pattern 1: Deterministic Threshold Checker (analyst.py)

**What:** Pure function that takes `AgentState`, inspects `poll_result.readings`, and sets `alert_needed=True` with a list of flagged colors if any reading is below threshold.

**When to use:** Entry point into the pipeline after every SNMP poll.

**Key logic:**
- Read `TONER_ALERT_THRESHOLD` and `TONER_CRITICAL_THRESHOLD` from env (with defaults 20 and 10).
- For each `TonerReading` in `poll_result["readings"]`:
  - If `quality_flag == QualityFlag.BELOW_LOW_THRESHOLD.value`: flag as Critical (toner_pct is None — unquantified)
  - If `data_quality_ok` is True and `toner_pct is not None` and `toner_pct < alert_threshold`: flag as Warning or Critical
  - If `quality_flag` is UNKNOWN, SNMP_ERROR, NULL_VALUE, NOT_SUPPORTED, OUT_OF_RANGE: skip (not alert-worthy for ANLZ-01; those are data quality issues handled by GURD-03)
- CRITICAL: `BELOW_LOW_THRESHOLD` IS alert-worthy even though `data_quality_ok=False`
- Return updated `AgentState` with `alert_needed`, and a new state field `flagged_colors` (list of dicts with color, urgency, display_value)

**Example:**
```python
# Source: state_types.py (QualityFlag definitions) + CONTEXT.md decisions
import os
from state_types import AgentState, QualityFlag

def run_analyst(state: AgentState) -> AgentState:
    """Deterministic threshold checker. Sets alert_needed and flagged_colors."""
    alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
    critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))

    poll_result = state["poll_result"]
    if poll_result is None:
        state["decision_log"] = state["decision_log"] + ["analyst: no poll_result, skipping"]
        state["alert_needed"] = False
        return state

    flagged = []
    for reading in poll_result["readings"]:
        flag = reading["quality_flag"]
        color = reading["color"]

        if flag == QualityFlag.BELOW_LOW_THRESHOLD.value:
            # Printer reports some toner remains but cannot quantify — escalate as Critical
            flagged.append({
                "color": color,
                "urgency": "CRITICAL",
                "display_value": "below low threshold (unquantified)",
            })
        elif reading["data_quality_ok"] and reading["toner_pct"] is not None:
            pct = reading["toner_pct"]
            if pct < critical_threshold:
                flagged.append({"color": color, "urgency": "CRITICAL", "display_value": f"{pct}%"})
            elif pct < alert_threshold:
                flagged.append({"color": color, "urgency": "WARNING", "display_value": f"{pct}%"})

    state["alert_needed"] = len(flagged) > 0
    state["flagged_colors"] = flagged  # New field consumed by communicator
    state["decision_log"] = state["decision_log"] + [
        f"analyst: {len(flagged)} colors flagged, alert_needed={state['alert_needed']}"
    ]
    return state
```

**AgentState extension note:** `AgentState` in `state_types.py` does not have a `flagged_colors` field. The CONTEXT.md says "no new state fields needed for Phase 2" — interpret this as: use `AgentState` as the carrier but pass `flagged_colors` as a regular Python dict value alongside state, OR add it as an Optional field to `AgentState`. The cleanest approach is to add `flagged_colors: list` as Optional to `AgentState` in `state_types.py` since it flows analyst → communicator.

### Pattern 2: Policy Guard (safety_logic.py)

**What:** Two independent checks — staleness check and rate limit check. Both must pass for alert to proceed.

**Staleness check:**
```python
# Source: CONTEXT.md decisions + state_types.py
from datetime import datetime, timezone, timedelta
import os

def check_data_freshness(poll_result: "PollResult") -> tuple[bool, str | None]:
    """Returns (is_fresh, reason_if_stale). Stale when age > STALE_THRESHOLD_MINUTES."""
    stale_minutes = float(os.getenv("STALE_THRESHOLD_MINUTES", "120"))
    poll_ts = datetime.fromisoformat(poll_result["timestamp"])
    now = datetime.now(timezone.utc)
    age_minutes = (now - poll_ts).total_seconds() / 60.0
    if age_minutes > stale_minutes:
        return False, f"stale_data: age={age_minutes:.1f}min > threshold={stale_minutes}min"
    return True, None
```

**Rate limit check:**
```python
# Source: CONTEXT.md decisions
import json
from pathlib import Path

ALERT_STATE_PATH = Path("logs/alert_state.json")

def check_rate_limit(printer_host: str) -> tuple[bool, str | None]:
    """Returns (can_send, reason_if_blocked). Blocks if last alert < 24h ago."""
    state = _load_alert_state()
    host_state = state.get(printer_host, {})
    last_ts_str = host_state.get("last_alert_timestamp")
    if last_ts_str:
        last_ts = datetime.fromisoformat(last_ts_str)
        now = datetime.now(timezone.utc)
        if (now - last_ts) < timedelta(hours=24):
            return False, f"rate_limit: last_alert={last_ts_str}"
    return True, None

def record_alert_sent(printer_host: str) -> None:
    """Update alert_state.json with current timestamp after a successful send."""
    state = _load_alert_state()
    state[printer_host] = {"last_alert_timestamp": datetime.now(timezone.utc).isoformat()}
    _save_alert_state(state)

def _load_alert_state() -> dict:
    if not ALERT_STATE_PATH.exists():
        return {}
    try:
        return json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Corrupted or unreadable — treat as no prior state (safe default)
        return {}

def _save_alert_state(state: dict) -> None:
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
```

### Pattern 3: Suppression Logging

**What:** Every suppressed alert appended to `printer_history.jsonl` via existing `append_poll_result()`.

**Key insight:** `append_poll_result()` accepts any dict — not just `PollResult`. Use it for suppression records too.

```python
# Source: adapters/persistence.py — append_poll_result accepts any dict
from adapters.persistence import append_poll_result
from pathlib import Path
from datetime import datetime, timezone

def log_suppression(printer_host: str, reason: str, extra: dict) -> None:
    """Append a suppression event to printer_history.jsonl."""
    record = {
        "event_type": "suppressed_alert",
        "printer_host": printer_host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        **extra,  # reason-specific fields (last_alert_time, age_minutes, etc.)
    }
    append_poll_result(record)
```

### Pattern 4: Alert Email Construction (communicator.py)

**What:** Builds subject and body from `flagged_colors`, calls `SMTPAdapter.send_alert()`.

```python
# Source: CONTEXT.md decisions + adapters/smtp_adapter.py
from adapters.smtp_adapter import SMTPAdapter
import os

def build_subject(flagged_colors: list[dict]) -> str:
    """[Sentinel] CRITICAL: Printer toner low — Cyan 8%, Yellow unquantified"""
    overall_urgency = "CRITICAL" if any(c["urgency"] == "CRITICAL" for c in flagged_colors) else "WARNING"
    color_parts = ", ".join(f"{c['color'].capitalize()} {c['display_value']}" for c in flagged_colors)
    return f"[Sentinel] {overall_urgency}: Printer toner low — {color_parts}"

def build_body(printer_host: str, flagged_colors: list[dict]) -> str:
    lines = [
        f"Printer: {printer_host}",
        "",
        "Low toner detected:",
    ]
    for c in flagged_colors:
        lines.append(f"  {c['color'].capitalize()}: {c['display_value']} [{c['urgency']}]")
        lines.append(f"  Recommended action: Order {c['color']} toner")
        lines.append("")
    return "\n".join(lines)
```

### Pattern 5: Sequential Supervisor (supervisor.py)

**What:** Simple sequential Python function — NOT a LangGraph graph (that is Phase 4).

```python
# Source: CONTEXT.md — "Phase 2 can be a simple sequential function (no LangGraph wiring)"
from state_types import AgentState, PollResult
from agents.analyst import run_analyst
from agents.communicator import run_communicator
from guardrails.safety_logic import run_policy_guard

def run_pipeline(poll_result: PollResult) -> AgentState:
    """Sequential pipeline: analyst -> policy_guard -> communicator."""
    state: AgentState = {
        "poll_result": poll_result,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
    }
    state = run_analyst(state)
    if state["alert_needed"]:
        state = run_policy_guard(state)
    if state["alert_needed"] and not state["suppression_reason"]:
        state = run_communicator(state)
    return state
```

### Anti-Patterns to Avoid

- **Calling `jsonlines` directly in new code:** Always use `append_poll_result()` from `adapters/persistence.py`. Direct `jsonlines` usage bypasses the established pattern.
- **Opening `alert_state.json` with `mode='w'`:** Like JSONL, use read-modify-write with `json.loads` / `json.dumps`. Never truncate.
- **Treating BELOW_LOW_THRESHOLD as a data quality failure for alerting:** `data_quality_ok=False` for this sentinel, but the analyst must explicitly handle it as alert-worthy. Do not gate on `data_quality_ok` alone.
- **Using `QualityFlag.STALE` in the SNMP adapter:** The staleness check belongs in the Policy Guard, not the adapter (CONTEXT.md locked decision).
- **Sending one email per flagged color:** CONTEXT.md locked: one email per poll cycle listing ALL flagged colors.
- **Checking `overall_quality_ok` to gate alerts:** A poll with yellow=BELOW_LOW_THRESHOLD has `overall_quality_ok=False`, but that reading IS alert-worthy. Check `quality_flag` per reading, not the aggregate flag.
- **Adding LangGraph StateGraph wiring:** Phase 2 supervisor is a plain Python function. LangGraph graph is Phase 4.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSONL append to history | Custom file writer | `append_poll_result()` from `adapters/persistence.py` | Already handles parent mkdir, append mode, jsonlines encoding |
| Email sending | SMTP connection code | `SMTPAdapter.send_alert(recipient, subject, body)` | Already handles STARTTLS, mock mode, connection-per-send |
| Rate-limit state storage | Database, Redis | Plain JSON file `logs/alert_state.json` | O(1) dict lookup sufficient for single-printer v1; no external dep |
| Timezone-aware datetime | `time.time()` | `datetime.now(timezone.utc)` | All existing timestamps use UTC ISO 8601; maintain consistency |
| QualityFlag string comparison | Raw string `== "below_low_threshold"` | `QualityFlag.BELOW_LOW_THRESHOLD.value` | Enum ensures typo safety; pattern used throughout codebase |

**Key insight:** Phase 2 is almost entirely wiring — connecting existing, tested primitives with new business logic. The only genuinely new state is `logs/alert_state.json`.

---

## Common Pitfalls

### Pitfall 1: BELOW_LOW_THRESHOLD Treated as Non-Alert

**What goes wrong:** Code checks `data_quality_ok` before alerting. Since BELOW_LOW_THRESHOLD readings have `data_quality_ok=False`, they are silently skipped — no alert fires even though the printer is reporting critically low toner.

**Why it happens:** `data_quality_ok=False` looks like a bad reading. But BELOW_LOW_THRESHOLD is a well-defined state (some toner remains, unquantified) that is explicitly listed in CONTEXT.md as alert-worthy.

**How to avoid:** In the analyst, handle `QualityFlag.BELOW_LOW_THRESHOLD.value` as a special case BEFORE checking `data_quality_ok`. Only skip readings with UNKNOWN, SNMP_ERROR, NULL_VALUE, NOT_SUPPORTED, OUT_OF_RANGE flags.

**Warning signs:** Mock fixture has `yellow` with sentinel -3 (BELOW_LOW_THRESHOLD). If tests with mock data never trigger an alert for yellow, this pitfall has occurred.

### Pitfall 2: Timezone-Naive Datetime Comparison

**What goes wrong:** `datetime.fromisoformat(timestamp)` on the poll result returns a timezone-aware datetime (UTC). `datetime.now()` without `timezone.utc` returns a naive datetime. Subtracting them raises `TypeError: can't subtract offset-naive and offset-aware datetimes`.

**Why it happens:** Python's `datetime.now()` is naive by default. The existing codebase always uses `datetime.now(timezone.utc)` — easy to miss.

**How to avoid:** Always use `datetime.now(timezone.utc)` in all new code. Pattern established in `snmp_adapter.py` line: `timestamp = datetime.now(timezone.utc).isoformat()`.

**Warning signs:** `TypeError` in staleness check or rate limit check at runtime.

### Pitfall 3: alert_state.json Race Condition (not critical for v1)

**What goes wrong:** If two poll cycles somehow run concurrently, both could read the state file before either writes, sending two emails within 24h.

**Why it happens:** Read-modify-write without a lock.

**How to avoid:** Acceptable for v1 — the scheduler is single-threaded (Phase 4). Document the assumption. Do NOT add file locking complexity.

### Pitfall 4: snmp_error Set But Readings Present

**What goes wrong:** When `PollResult.snmp_error` is set, `readings` still contains placeholder error readings with `quality_flag=SNMP_ERROR`. If the analyst iterates over readings without checking `snmp_error` first, it will see four SNMP_ERROR readings and not flag an alert — which is correct. But if `snmp_error` alone should suppress the alert, the policy guard must check it explicitly.

**Why it happens:** PollResult contract: adapter never raises, always returns readings. The `snmp_error` field is the signal.

**How to avoid:** Policy guard should check `poll_result["snmp_error"] is not None` as a data quality failure condition. Log and suppress.

### Pitfall 5: alert_state.json Corrupted by Concurrent Write

**What goes wrong:** `alert_state.json` is written with `write_text()` (atomic on most OS but not guaranteed). A crash mid-write could corrupt the JSON.

**Why it happens:** No atomic rename pattern used.

**How to avoid:** In `_load_alert_state()`, wrap `json.loads()` in `try/except (json.JSONDecodeError, OSError)` and return `{}` on failure. This treats corruption as "no prior alerts" — safe default that may result in one extra email, not silence.

### Pitfall 6: AgentState Missing flagged_colors Field

**What goes wrong:** `state_types.AgentState` TypedDict does not have a `flagged_colors` field. If the analyst sets `state["flagged_colors"] = [...]`, mypy will flag it as an error, and the communicator can't type-check it either.

**Why it happens:** CONTEXT.md says "use these as-is, no new state fields needed for Phase 2" — but in practice the analyst must communicate the flagged color list to the communicator.

**How to avoid:** Add `flagged_colors: list` (or `Optional[list]`) to `AgentState` in `state_types.py`. This is a controlled change to the data contract, not a new state "concept". The CONTEXT.md intent is to avoid adding high-level business state fields (confidence scores, LLM reasoning); a list of flagged colors is a core pipeline carrier.

---

## Code Examples

Verified patterns from existing codebase:

### Reading env vars with defaults (established pattern)
```python
# Source: adapters/smtp_adapter.py — lines 76-77
self._host = host or os.getenv("SMTP_HOST", "smtp.office365.com")
self._port = int(port or os.getenv("SMTP_PORT", "587"))

# Apply same pattern for thresholds:
alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))
stale_minutes = float(os.getenv("STALE_THRESHOLD_MINUTES", "120"))
```

### QualityFlag comparison (established pattern)
```python
# Source: state_types.py — QualityFlag is str Enum, .value is plain str
from state_types import QualityFlag

# Correct:
if reading["quality_flag"] == QualityFlag.BELOW_LOW_THRESHOLD.value:
    ...

# Also correct (QualityFlag is str, so direct comparison works):
if reading["quality_flag"] == "below_low_threshold":
    ...

# Prefer the enum form — typo-safe
```

### Mock mode env var pattern (established pattern)
```python
# Source: adapters/snmp_adapter.py — lines 271-273
# Source: adapters/smtp_adapter.py — lines 64-65
# Both adapters check use_mock kwarg OR env var:
env_mock = os.getenv("USE_MOCK_SMTP", "false").lower() == "true"
self._use_mock = use_mock or env_mock

# If supervisor.py needs a mock mode for testing, follow same pattern
```

### decision_log append (established pattern)
```python
# Source: state_types.py — Annotated[list[str], operator.add] for LangGraph merge
# For Phase 2 sequential function, plain list concatenation is sufficient:
state["decision_log"] = state["decision_log"] + ["analyst: 2 colors flagged"]
# DO NOT use state["decision_log"].append() — TypedDict mutation may cause issues with LangGraph later
```

### UTC timestamp creation and parsing
```python
# Source: adapters/snmp_adapter.py — line 287
from datetime import datetime, timezone, timedelta

# Create:
timestamp = datetime.now(timezone.utc).isoformat()

# Parse and compare for staleness:
poll_ts = datetime.fromisoformat(poll_result["timestamp"])
now = datetime.now(timezone.utc)
age_minutes = (now - poll_ts).total_seconds() / 60.0
```

### Path and JSON for alert_state.json
```python
# Consistent with adapters/persistence.py pattern (Path, mkdir parents=True)
from pathlib import Path
import json

ALERT_STATE_PATH = Path("logs/alert_state.json")

def _load_alert_state() -> dict:
    if not ALERT_STATE_PATH.exists():
        return {}
    try:
        return json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}  # Safe default on corruption

def _save_alert_state(state: dict) -> None:
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| EWS/exchangelib for email | smtplib STARTTLS | Phase 1 (01-03) | smtp_adapter.py already handles Office 365; no Exchange server needed |
| pysnmp-sync-adapter | asyncio.run() with pysnmp v7 | Phase 1 (01-01) | asyncio.run() is the correct approach; pysnmp-sync-adapter may still be installed |
| LangGraph StateGraph nodes | Sequential Python function for Phase 2 | Deferred to Phase 4 | supervisor.py is a plain function that calls agents directly |
| LLM-based analysis | Deterministic threshold check | Phase 2 scope | ANLZ-01 is implemented without LLM; LLM is Phase 3 |

**Deprecated/outdated:**
- `GURD-02` (LLM confidence threshold check): Out of scope for Phase 2 — this is a Phase 3 requirement. Do not stub or partially implement it.
- `ALRT-02` LLM confidence/reasoning fields in email: Phase 3 additions. Phase 2 email body omits them entirely.

---

## Open Questions

1. **`flagged_colors` field in `AgentState`**
   - What we know: `AgentState` currently has 5 fields; analyst computes flagged colors that communicator needs
   - What's unclear: CONTEXT.md says "no new state fields needed" — literal interpretation prevents adding it; pragmatic interpretation allows it as a pipeline carrier
   - Recommendation: Add `flagged_colors: Optional[list]` to `AgentState` in `state_types.py`. This is a minimal, controlled addition to the data contract that avoids global variable anti-patterns. The CONTEXT.md intent is to avoid high-level semantic additions (confidence scores, LLM output), not to prevent pipeline data flow.

2. **`ALERT_RECIPIENT` validation at startup**
   - What we know: `ALERT_RECIPIENT` must be set for communicator to send emails; `SMTPAdapter` doesn't validate it
   - What's unclear: Should communicator raise on missing `ALERT_RECIPIENT`, or log and skip?
   - Recommendation: Follow `SMTPAdapter` pattern — raise `ValueError` with a clear message pointing to the env var. Fail fast is better than silent suppression.

3. **First-run behavior with no `alert_state.json`**
   - What we know: `_load_alert_state()` returns `{}` if file doesn't exist
   - What's unclear: Is there a need to pre-create `logs/alert_state.json`?
   - Recommendation: No pre-creation needed. `_save_alert_state()` creates it with `mkdir(parents=True, exist_ok=True)` on first write. This is the same pattern as `persistence.py`.

---

## Sources

### Primary (HIGH confidence)
- `C:/Users/rohit/ROHIT/Project-Sentinel/state_types.py` — TypedDict definitions: `AgentState`, `QualityFlag`, `TonerReading`, `PollResult`
- `C:/Users/rohit/ROHIT/Project-Sentinel/adapters/snmp_adapter.py` — Mock mode pattern, `asyncio.run()`, sentinel classification, timestamp creation
- `C:/Users/rohit/ROHIT/Project-Sentinel/adapters/smtp_adapter.py` — `send_alert()` API, mock mode env var pattern
- `C:/Users/rohit/ROHIT/Project-Sentinel/adapters/persistence.py` — `append_poll_result()` API, JSONL append pattern, Path usage
- `C:/Users/rohit/ROHIT/Project-Sentinel/.planning/phases/02-monitoring-pipeline/02-CONTEXT.md` — All locked implementation decisions

### Secondary (MEDIUM confidence)
- `C:/Users/rohit/ROHIT/Project-Sentinel/.planning/REQUIREMENTS.md` — ANLZ-01, GURD-01, GURD-03, GURD-04, ALRT-02, ALRT-03 requirement text
- `C:/Users/rohit/ROHIT/Project-Sentinel/tests/test_snmp_adapter.py` — Test patterns, fixture data shape (yellow=BELOW_LOW_THRESHOLD)
- `C:/Users/rohit/ROHIT/Project-Sentinel/tests/test_persistence.py` — `append_poll_result()` accepts any dict (not just `PollResult`)

### Tertiary (LOW confidence)
- None — all findings verified against codebase source

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are already installed and used in Phase 1 code
- Architecture: HIGH — patterns verified directly from existing `adapters/` source; decisions locked in CONTEXT.md
- Pitfalls: HIGH — derived from code inspection of `state_types.py`, `snmp_adapter.py`, and CONTEXT.md decisions; no speculation

**Research date:** 2026-03-01
**Valid until:** 2026-04-01 (stable Python stdlib patterns; no fast-moving dependencies for this phase)
