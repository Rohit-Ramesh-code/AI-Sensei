# Phase 1: Foundation - Research

**Researched:** 2026-02-28
**Domain:** SNMP polling (Printer-MIB), Microsoft Exchange Web Services (EWS), Python state typing, JSON Lines persistence
**Confidence:** HIGH (stack) / HIGH (patterns) / MEDIUM (Lexmark OID index ordering)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Sentinel value encoding**
- SNMP sentinel values (-2, -3) are represented as a typed Python **enum**: `QualityFlag.NOT_INSTALLED`, `QualityFlag.NOT_SUPPORTED`, `QualityFlag.OK`, etc.
- Downstream nodes pattern-match on the enum, not on raw integers or magic strings
- The adapter never passes raw sentinel integers to callers

**Persistence log fields**
- Format: JSON Lines (one JSON object per line, newline-delimited)
- Each entry includes: toner percentage per color, quality flag per color, ISO 8601 timestamp, raw SNMP integer value per color, printer IP/hostname, and any SNMP error message
- Both valid and invalid poll results are logged (quality flag distinguishes them)

**State type approach**
- Use Python **TypedDict** for all state definitions
- No Pydantic, no dataclasses — TypedDict is native to LangGraph and adds zero dependencies
- Types must be importable by downstream modules (agents, guardrails)

**Dev/test strategy**
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

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SNMP-01 | System polls Lexmark XC2235 for toner percentage per color (CMYK) via SNMP on a scheduled interval | Printer-MIB OIDs confirmed: prtMarkerSuppliesLevel (1.3.6.1.2.1.43.11.1.1.9.1.x) and prtMarkerSuppliesMaxCapacity (1.3.6.1.2.1.43.11.1.1.8.1.x) where x=1–4; pysnmp v7 asyncio or pysnmp-sync-adapter identified |
| SNMP-02 | SNMP adapter detects and handles Lexmark sentinel values (-2: unknown, -3: below low threshold) and converts them to structured data quality flags | RFC 3805 Printer-MIB defines: -1=other, -2=unknown, -3=present-but-unquantified; QualityFlag enum maps these directly |
| SNMP-03 | SNMP adapter validates each reading for staleness, null values, and out-of-range results, setting a `data_quality_ok` flag on the output | Validation logic is custom but straightforward: check for None, sentinel values, and range [0, max_capacity]; flag per color |
| SNMP-04 | Every poll result (valid or invalid) is persisted to a JSON Lines history log with timestamp and data quality metadata | `jsonlines` library (wbolster) provides append-mode context manager; standard stdlib `json` + `open('a')` is viable alternative |
| ALRT-01 | Communicator Agent sends alert emails via Microsoft Exchange Web Services (EWS) using a configured service account | `exchangelib` 5.6.0 confirmed; Message + send() pattern verified; Basic Auth/NTLM for on-prem; MSAL extra for O365 |
</phase_requirements>

---

## Summary

Phase 1 establishes the infrastructure foundation: SNMP polling from a real Lexmark printer, email delivery via Exchange, a persistent JSON Lines log, and the Python type definitions that all downstream agents depend on. All four areas have well-established Python libraries; the main research finding is a **critical SNMP library decision** — pysnmp v7 (the current release) is asyncio-only and removed the synchronous HLAPI in v6.2. This forces a choice between adopting asyncio for SNMP (adding complexity) or using `pysnmp-sync-adapter` (a thin blocking wrapper around v7) or switching to `ezsnmp` (a maintained fork of easysnmp, which requires Net-SNMP system library but is fully synchronous and 4x faster).

The Lexmark XC2235 uses the standard RFC 3805 Printer-MIB, not a proprietary MIB, which means OIDs are predictable and well-documented. Toner levels are obtained by walking `prtMarkerSuppliesLevel` (OID `1.3.6.1.2.1.43.11.1.1.9.1.x`) and `prtMarkerSuppliesMaxCapacity` (`.8.1.x`) and computing a percentage. Sentinel values -2 and -3 are standard RFC-defined codes — **not** Lexmark-specific; -2 means "unknown" and -3 means "present but not quantified."

exchangelib 5.6.0 is actively maintained, supports Basic Auth and NTLM for on-prem Exchange out of the box, and has a straightforward `Message(...).send()` pattern. The only confirmed blocker is that the Exchange server's auth type (Basic vs NTLM vs OAuth) must be confirmed with IT before the EWS adapter can be finalized — the library supports all three but they require different `Configuration` setup.

**Primary recommendation:** Use `pysnmp` v7 with `pysnmp-sync-adapter` for SNMP (pure Python, no system lib dependency, runs on Windows without compilation); use `exchangelib` 5.6.0 for EWS; use `jsonlines` for log persistence; use Python `TypedDict` + `Enum` for all state and quality flag types.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pysnmp | 7.1.22 | SNMP engine — sends GET requests, decodes responses | Pure Python, no C compilation, Windows-compatible, actively maintained by LeXtudio Inc. |
| pysnmp-sync-adapter | 1.0.8 | Blocking wrapper around pysnmp v7 asyncio API | Required because pysnmp v7 removed synchronous HLAPI in v6.2; provides drop-in sync functions |
| exchangelib | 5.6.0 | Microsoft EWS client — sends emails via Exchange | Only maintained Python EWS library; supports on-prem and O365; Basic Auth + NTLM out of box |
| jsonlines | latest | JSON Lines file read/write with context manager | Thin wrapper around stdlib json that handles newlines, append mode, and type coercion |
| python-dotenv | latest | Load `.env` file into `os.environ` | Project already uses this pattern (in CLAUDE.md); zero-dependency env management |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dateutil | latest | ISO 8601 timestamp parsing and generation | Use for `datetime.now(timezone.utc).isoformat()` in log entries |
| typing_extensions | latest | Backport `TypedDict`, `Annotated` for older Python | Only needed if Python < 3.11; use stdlib `typing` on 3.11+ |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pysnmp + pysnmp-sync-adapter | ezsnmp | ezsnmp is 4x faster but requires Net-SNMP C library installed system-wide — problematic on Windows development machines; pysnmp is pure Python |
| pysnmp + pysnmp-sync-adapter | easysnmp 0.2.6 | easysnmp is unmaintained (no releases in 12+ months), same C dependency issue as ezsnmp |
| exchangelib | zeep + raw SOAP | exchangelib abstracts all SOAP/XML complexity; hand-rolling EWS SOAP is extremely error-prone |
| jsonlines library | stdlib json + open('a') | stdlib approach works fine; jsonlines adds type coercion, reader, and explicit JSONL mode — low-risk choice either way |

**Installation:**
```bash
pip install pysnmp==7.1.22 pysnmp-sync-adapter exchangelib jsonlines python-dotenv
```

---

## Architecture Patterns

### Recommended Project Structure

The project structure is already defined in CLAUDE.md. Phase 1 populates these files:

```
adapters/
├── __init__.py              # Already exists (empty stub)
├── snmp_adapter.py          # SNMP polling — SNMPAdapter class
└── ews_scraper.py           # EWS email — EWSAdapter class
guardrails/
└── (Phase 2)
agents/
└── (Phase 2+)
logs/
└── printer_history.jsonl    # JSON Lines log (created on first poll)
state_types.py               # TypedDict state definitions (new file)
.env.example                 # Documents all env vars including mock flags
```

### Pattern 1: QualityFlag Enum

**What:** A Python `Enum` that encodes all possible states of a single toner reading — valid percentage, Printer-MIB sentinel values, and data collection errors.

**When to use:** Everywhere a toner reading's validity needs to be communicated. The adapter returns it; the policy guard consumes it; the log persists its name.

```python
# adapters/snmp_adapter.py
from enum import Enum

class QualityFlag(str, Enum):
    """
    Encodes toner reading validity. str mixin means .value is JSON-serializable.
    Standard RFC 3805 Printer-MIB sentinel values:
      -2 = unknown (device cannot measure the supply level)
      -3 = present but not quantified (below low threshold, some remains)
    """
    OK = "ok"                        # Valid percentage in [0, 100]
    UNKNOWN = "unknown"              # Sentinel -2: device reports unknown
    BELOW_LOW_THRESHOLD = "below_low_threshold"  # Sentinel -3: some remains, unquantified
    NOT_SUPPORTED = "not_supported"  # Sentinel -1: no restriction / not applicable
    STALE = "stale"                  # Timestamp too old (future use)
    NULL_VALUE = "null_value"        # None or missing from SNMP response
    OUT_OF_RANGE = "out_of_range"    # Value outside [0, max_capacity]
    SNMP_ERROR = "snmp_error"        # SNMP transport/protocol failure
```

**Why `str` mixin:** Makes `flag.value` a plain string, so `json.dumps({"flag": flag})` works without a custom encoder.

### Pattern 2: TypedDict State Contract

**What:** Shared state definitions using Python `TypedDict`. Every field the LangGraph pipeline passes between nodes is declared here.

**When to use:** Import from any agent, adapter, or guardrail that needs to construct or consume pipeline state.

```python
# state_types.py — importable by all downstream modules
from __future__ import annotations
from typing import TypedDict, Optional
from adapters.snmp_adapter import QualityFlag

class TonerReading(TypedDict):
    """Single-color toner reading from one SNMP poll."""
    color: str                    # "cyan" | "magenta" | "yellow" | "black"
    raw_value: int                # Raw SNMP integer (may be -2, -3, etc.)
    max_capacity: int             # prtMarkerSuppliesMaxCapacity value
    toner_pct: Optional[float]    # Computed percentage; None if quality flag != OK
    quality_flag: str             # QualityFlag.value (string)
    data_quality_ok: bool         # True only if quality_flag == QualityFlag.OK

class PollResult(TypedDict):
    """Output of one complete SNMP poll cycle."""
    printer_host: str             # IP/hostname polled
    timestamp: str                # ISO 8601 UTC, e.g. "2026-02-28T10:00:00+00:00"
    readings: list[TonerReading]  # One entry per CMYK color
    snmp_error: Optional[str]     # Error message if SNMP transport failed; None on success
    overall_quality_ok: bool      # True only if ALL four readings are QualityFlag.OK

class AgentState(TypedDict):
    """LangGraph graph state — flows through all agent nodes."""
    poll_result: Optional[PollResult]
    alert_needed: bool
    alert_sent: bool
    suppression_reason: Optional[str]
```

### Pattern 3: SNMP GET with pysnmp-sync-adapter

**What:** Use the blocking sync wrapper around pysnmp v7's asyncio engine to retrieve SNMP values without managing event loops.

**When to use:** In the SNMP adapter's `poll()` method — called from the scheduler, which is synchronous.

```python
# adapters/snmp_adapter.py — SNMP GET pattern
# Source: pysnmp-sync-adapter PyPI + pysnmp v7 docs
from pysnmp_sync_adapter import get_cmd_sync, walk_cmd_sync
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity, SnmpEngine
)

# OIDs from RFC 3805 Printer-MIB (verified standard)
# prtMarkerSuppliesDescription: 1.3.6.1.2.1.43.11.1.1.6.1.{index}
# prtMarkerSuppliesMaxCapacity: 1.3.6.1.2.1.43.11.1.1.8.1.{index}
# prtMarkerSuppliesLevel:       1.3.6.1.2.1.43.11.1.1.9.1.{index}
# index 1=Black, 2=Cyan, 3=Magenta, 4=Yellow (typical; verify against device)

TONER_OIDS = {
    "black":   {"level": "1.3.6.1.2.1.43.11.1.1.9.1.1", "max": "1.3.6.1.2.1.43.11.1.1.8.1.1"},
    "cyan":    {"level": "1.3.6.1.2.1.43.11.1.1.9.1.2", "max": "1.3.6.1.2.1.43.11.1.1.8.1.2"},
    "magenta": {"level": "1.3.6.1.2.1.43.11.1.1.9.1.3", "max": "1.3.6.1.2.1.43.11.1.1.8.1.3"},
    "yellow":  {"level": "1.3.6.1.2.1.43.11.1.1.9.1.4", "max": "1.3.6.1.2.1.43.11.1.1.8.1.4"},
}

def _snmp_get(host: str, community: str, oid: str) -> int:
    """Single SNMP GET. Returns integer value or raises on error."""
    error_indication, error_status, error_index, var_binds = get_cmd_sync(
        SnmpEngine(),
        CommunityData(community, mpModel=1),  # mpModel=1 → SNMPv2c
        UdpTransportTarget((host, 161), timeout=5, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    if error_indication:
        raise RuntimeError(f"SNMP error: {error_indication}")
    if error_status:
        raise RuntimeError(f"SNMP status error: {error_status}")
    _, value = var_binds[0]
    return int(value)
```

### Pattern 4: EWS Email Send with exchangelib

**What:** Configure an Account with service account credentials and send a Message.

**When to use:** In `ews_scraper.py` — called by the Communicator Agent after Policy Guard clears.

```python
# adapters/ews_scraper.py — EWS send pattern
# Source: https://ecederstrand.github.io/exchangelib/
from exchangelib import Credentials, Configuration, Account, DELEGATE, Message, Mailbox
from exchangelib import NTLM  # For on-prem Exchange; use BASIC if server requires it

def build_account(server: str, username: str, password: str, email: str) -> Account:
    """Build an exchangelib Account for a service account."""
    credentials = Credentials(username=username, password=password)
    config = Configuration(
        server=server,
        credentials=credentials,
        auth_type=NTLM,  # Switch to BASIC or OAuth if IT requires
    )
    return Account(
        primary_smtp_address=email,
        config=config,
        autodiscover=False,
        access_type=DELEGATE,
    )

def send_alert_email(account: Account, recipient: str, subject: str, body: str) -> None:
    """Send alert email. Does NOT save a local copy."""
    m = Message(
        account=account,
        subject=subject,
        body=body,
        to_recipients=[Mailbox(email_address=recipient)],
    )
    m.send()
```

### Pattern 5: JSON Lines Append

**What:** Append a single `PollResult` dict to the JSONL log file atomically per record.

**When to use:** After every SNMP poll, regardless of result quality.

```python
# In snmp_adapter.py or a dedicated persistence module
import jsonlines
from pathlib import Path

LOG_PATH = Path("logs/printer_history.jsonl")

def append_poll_result(result: dict) -> None:
    """Append one PollResult to the JSONL log. Creates file if absent."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with jsonlines.open(str(LOG_PATH), mode="a") as writer:
        writer.write(result)
```

### Pattern 6: Mock Mode via Env Flag

**What:** Check `USE_MOCK_SNMP` / `USE_MOCK_EWS` at adapter init and branch to a stub that returns fixture data or logs instead of sending.

**When to use:** Always check the env flag before attempting real I/O — allows offline development and testing.

```python
# adapters/snmp_adapter.py — mock branch
import os

USE_MOCK = os.getenv("USE_MOCK_SNMP", "false").lower() == "true"

MOCK_FIXTURE = {
    "black":   {"level": 85, "max": 100},
    "cyan":    {"level": 42, "max": 100},
    "magenta": {"level": -2, "max": 100},  # Unknown sentinel
    "yellow":  {"level": -3, "max": 100},  # Below threshold sentinel
}

def poll(host: str, community: str) -> dict:
    if USE_MOCK:
        return _build_result_from_fixture(host, MOCK_FIXTURE)
    return _poll_real(host, community)
```

### Anti-Patterns to Avoid

- **Passing raw SNMP integers to callers:** The adapter must convert -2, -3, and other sentinel values to `QualityFlag` before returning. Never let raw integers escape the adapter.
- **Using pysnmp <= 6.1 "synchronous" iterator style:** The `next(getCmd(...))` pattern was removed in pysnmp v6.2. Code copied from old tutorials will fail silently (returns coroutine, not value).
- **Hardcoding OID indices without device verification:** The CMYK index order (1=Black, 2=Cyan, etc.) is typical but not guaranteed. Phase 1 task must walk `prtMarkerSuppliesDescription` to confirm actual index-to-color mapping on the physical XC2235.
- **Opening the JSONL file in write mode (`'w'`):** This truncates the log on every poll. Always use append mode `'a'`.
- **Building exchangelib Account on every email send:** Account construction involves TLS handshake and potentially autodiscover. Build once at startup, reuse the instance.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SNMP protocol implementation | Custom socket-based SNMP client | pysnmp + pysnmp-sync-adapter | SNMP has PDU encoding, OID encoding, community string auth, error codes, and retry logic — all handled by pysnmp |
| EWS SOAP XML construction | Raw SOAP envelope building with requests | exchangelib | EWS SOAP is verbose and brittle; exchangelib handles WSDL negotiation, NTLM auth handshake, and retry on 503 |
| JSON Lines file handling | Manual `json.dumps() + '\n'` with file locking | jsonlines library | jsonlines handles encoding, newline termination, and reader/writer context managers; avoids partial-write corruption |
| ISO 8601 UTC timestamps | Custom datetime formatting | `datetime.now(timezone.utc).isoformat()` | Built into Python stdlib; always include timezone offset to avoid ambiguity |

**Key insight:** All three external I/O concerns (SNMP, EWS, file I/O) have well-maintained Python libraries. The project's adapter pattern is designed to isolate exactly this complexity — use the libraries fully, don't leak protocol details into agent code.

---

## Common Pitfalls

### Pitfall 1: pysnmp v7 Asyncio API — Synchronous Code Breaks

**What goes wrong:** Calling `getCmd(...)` in pysnmp v7 returns a coroutine. Code that uses `next(getCmd(...))` or assigns the result directly raises `TypeError: 'coroutine' object is not an iterator`.

**Why it happens:** pysnmp v7 fully migrated to asyncio in v6.0 and retired the temporary sync API in v6.2. Old tutorials (pre-2023) show the synchronous iterator pattern that no longer works.

**How to avoid:** Install `pysnmp-sync-adapter` and use `get_cmd_sync()` instead of `getCmd()`. Alternatively, run pysnmp inside `asyncio.run()` — but this conflicts with APScheduler's event loop in later phases.

**Warning signs:** `RuntimeWarning: coroutine 'getCmd' was never awaited`; adapter returns None instead of integer value.

### Pitfall 2: SNMP OID Index Order Is Device-Dependent

**What goes wrong:** Hardcoding index 1=Black, 2=Cyan, 3=Magenta, 4=Yellow. On the actual XC2235, the order may differ (e.g., 1=Cyan, 2=Magenta, 3=Yellow, 4=Black — common on Lexmark color devices).

**Why it happens:** RFC 3805 defines the table structure but not the row ordering. Each printer firmware assigns indices arbitrarily.

**How to avoid:** During first-run initialization, walk `prtMarkerSuppliesDescription` (OID `.6.1.x`) to read color names, then build a dynamic `{color: index}` map. Never hardcode the index order as a constant.

**Warning signs:** Reported "cyan" level matches physical yellow cartridge; percentage values are swapped across colors.

### Pitfall 3: Exchange Auth Type Mismatch

**What goes wrong:** Configuring exchangelib with `NTLM` on a server that requires Basic Auth (or vice versa), causing `401 Unauthorized` on every send.

**Why it happens:** On-prem Exchange 2016 supports both, but some server configurations disable NTLM. Office 365 has deprecated Basic Auth entirely for most tenants.

**How to avoid:** Confirm auth type with IT before writing the EWS adapter. Make `auth_type` an env variable (`EWS_AUTH_TYPE=NTLM|BASIC|MSAL`) so it can be switched without code changes.

**Warning signs:** `exchangelib.errors.UnauthorizedError`; `401` in debug logs.

### Pitfall 4: JSONL Log File Mode Truncation

**What goes wrong:** Opening the log file with `mode='w'` instead of `mode='a'` — every poll wipes all historical data.

**Why it happens:** Standard Python file open defaults to write mode; easy to use the wrong mode.

**How to avoid:** Always use `jsonlines.open(path, mode='a')`. Add a comment in the code noting why `'a'` (not `'w'`) is critical.

**Warning signs:** Log file only ever has one line; historical data disappears after restart.

### Pitfall 5: `toner_pct` Computed Incorrectly When `max_capacity` Is Sentinel

**What goes wrong:** Some Lexmark firmware returns -2 for `prtMarkerSuppliesMaxCapacity` even when the level is valid. Division by -2 produces a nonsensical negative percentage.

**Why it happens:** The max_capacity OID can also return sentinel values, not just the level OID.

**How to avoid:** Validate both `max_capacity` and `level` before computing the percentage. If `max_capacity <= 0`, set `quality_flag = QualityFlag.UNKNOWN` and `toner_pct = None`.

**Warning signs:** Toner percentages reported as -4250% or similar impossible values.

---

## Code Examples

Verified patterns from official sources:

### SNMP Sentinel Value Detection and QualityFlag Assignment

```python
# Source: RFC 3805 Printer-MIB sentinel definitions + project CONTEXT.md decision
def classify_snmp_value(raw_level: int, max_capacity: int) -> tuple[QualityFlag, float | None]:
    """
    Convert raw SNMP integers to (QualityFlag, toner_pct | None).
    Sentinel values per RFC 3805:
      -1 = other/not applicable
      -2 = unknown (device cannot measure)
      -3 = present but unquantified (below low threshold)
    """
    if raw_level == -2:
        return QualityFlag.UNKNOWN, None
    if raw_level == -3:
        return QualityFlag.BELOW_LOW_THRESHOLD, None
    if raw_level == -1:
        return QualityFlag.NOT_SUPPORTED, None
    if raw_level is None:
        return QualityFlag.NULL_VALUE, None
    if max_capacity <= 0:
        # max_capacity itself is a sentinel — cannot compute percentage
        return QualityFlag.UNKNOWN, None
    if not (0 <= raw_level <= max_capacity):
        return QualityFlag.OUT_OF_RANGE, None
    pct = round((raw_level / max_capacity) * 100.0, 1)
    return QualityFlag.OK, pct
```

### exchangelib Message Send

```python
# Source: https://ecederstrand.github.io/exchangelib/ (official docs, verified 2026-02-28)
from exchangelib import Message, Mailbox

def send_alert(account, recipient_email: str, subject: str, body: str) -> None:
    """Send alert email without saving to Sent folder."""
    m = Message(
        account=account,
        subject=subject,
        body=body,
        to_recipients=[Mailbox(email_address=recipient_email)],
    )
    m.send()  # Does not save local copy; use m.send_and_save() if copy needed
```

### TypedDict with LangGraph-Compatible Reducers

```python
# Source: LangGraph docs 2025 — TypedDict is the canonical state schema approach
# Source: https://docs.langchain.com/oss/python/langgraph/graph-api
from __future__ import annotations
from typing import TypedDict, Optional, Annotated
import operator

class AgentState(TypedDict):
    """
    LangGraph pipeline state. Flows: SNMP → Monitor → Analyst → Policy Guard → Communicator.
    Fields updated by nodes are merged (not overwritten) when using Annotated reducers.
    """
    poll_result: Optional[PollResult]       # Set by Monitor node
    alert_needed: bool                       # Set by Analyst node
    alert_sent: bool                         # Set by Communicator node
    suppression_reason: Optional[str]        # Set by Policy Guard node
    decision_log: Annotated[list[str], operator.add]  # Appended by each node
```

### JSON Lines Append with Error Handling

```python
# Source: jsonlines library docs (https://jsonlines.readthedocs.io/)
import jsonlines
from pathlib import Path
from datetime import datetime, timezone

LOG_PATH = Path("logs/printer_history.jsonl")

def log_poll_result(result: dict) -> None:
    """Append poll result to JSONL log. Safe on first run (creates file)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with jsonlines.open(str(LOG_PATH), mode="a") as writer:
        writer.write(result)

# PollResult dict ready for serialization (QualityFlag.value is already a str)
entry = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "printer_host": "192.168.1.100",
    "readings": [
        {"color": "black", "raw_value": 85, "max_capacity": 100, "toner_pct": 85.0, "quality_flag": "ok", "data_quality_ok": True},
        {"color": "cyan",  "raw_value": -2,  "max_capacity": 100, "toner_pct": None,  "quality_flag": "unknown", "data_quality_ok": False},
    ],
    "snmp_error": None,
    "overall_quality_ok": False,
}
log_poll_result(entry)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pysnmp synchronous HLAPI (`next(getCmd(...))`) | pysnmp v7 asyncio (`await get_cmd(...)`) or `pysnmp-sync-adapter` | pysnmp v6.2 (2023–2024) | Old tutorial code silently returns coroutine objects instead of values; must use sync adapter |
| easysnmp (unmaintained) | ezsnmp (active fork, C extension) or pysnmp (pure Python) | easysnmp last released 2021 | easysnmp has no Python 3.12+ wheels; use ezsnmp or pysnmp |
| exchangelib Basic Auth (O365) | exchangelib MSAL/OAuth (O365) | O365 deprecated Basic Auth for most tenants ~2022–2023 | On-prem Exchange still supports NTLM/Basic; O365 requires OAuth |
| TypedDict without Annotated reducers | TypedDict + `Annotated[list, operator.add]` for multi-node writes | LangGraph 0.1+ (2024) | Without reducers, concurrent node writes overwrite each other |

**Deprecated/outdated:**
- `from pysnmp.hlapi import getCmd` (synchronous): Replaced by asyncio `get_cmd`; the old import path may still partially exist but the function is now async.
- easysnmp 0.2.6: Last release 2021, no Python 3.12+ support, unmaintained upstream.
- exchangelib Basic Auth on Office 365: Microsoft disabled for most tenants; use MSAL extra (`pip install exchangelib[msal]`) for O365.

---

## Open Questions

1. **Lexmark XC2235 SNMP color index order**
   - What we know: Standard Printer-MIB uses indices 1–4 for supplies; typical order is Black=1, Cyan=2, Magenta=3, Yellow=4, but firmware varies.
   - What's unclear: The exact index-to-color mapping for the physical XC2235 unit. Cannot determine without querying the device.
   - Recommendation: Phase 1 task must walk `prtMarkerSuppliesDescription` (`.6.1.x` for x in 1..8) on first run and build a dynamic color→index map. Do not hardcode.

2. **Exchange server auth type (Basic vs NTLM vs OAuth)**
   - What we know: exchangelib supports all three; on-prem Exchange 2016 commonly uses NTLM; O365 requires OAuth/MSAL.
   - What's unclear: Which auth type the target Exchange server enforces.
   - Recommendation: Make `EWS_AUTH_TYPE` an env variable (`NTLM` default). Confirm with IT before Phase 1 EWS task is verified against real server.

3. **SNMP community string and version on XC2235**
   - What we know: Lexmark printers typically use SNMPv2c with community string `public` for read-only access by default.
   - What's unclear: Whether the specific XC2235 unit has been reconfigured by IT to use a non-default community string.
   - Recommendation: `SNMP_COMMUNITY` env variable must be configured before integration testing. Default to `public` in mock mode.

4. **Whether `prtMarkerSuppliesMaxCapacity` returns 100 (percentage-mode) or raw units**
   - What we know: RFC 3805 says capacity is expressed in `prtMarkerSuppliesSupplyUnit`; some devices return 100 (percentage basis), others return raw page counts or ml values.
   - What's unclear: What unit the XC2235 uses.
   - Recommendation: Log both `raw_value` and `max_capacity` (locked decision already includes this). Percentage calculation is `(level / max_capacity) * 100` regardless of unit — works correctly in both cases.

---

## Sources

### Primary (HIGH confidence)
- RFC 3805 / RFC 1759 Printer-MIB — OID structure for `prtMarkerSuppliesLevel`, `prtMarkerSuppliesMaxCapacity`, `prtMarkerSuppliesDescription`, and sentinel values (-1, -2, -3): https://datatracker.ietf.org/doc/html/rfc1759
- exchangelib official documentation — credentials, Configuration, Message.send(), auth types: https://ecederstrand.github.io/exchangelib/
- pysnmp v7 changelog — confirmed synchronous HLAPI retirement in v6.2: https://docs.lextudio.com/pysnmp/changelog
- pysnmp-sync-adapter PyPI — blocking wrappers (get_cmd_sync, etc.) for pysnmp v7: https://pypi.org/project/pysnmp-sync-adapter/
- LangGraph graph API docs — TypedDict as canonical state schema, Annotated reducers: https://docs.langchain.com/oss/python/langgraph/graph-api

### Secondary (MEDIUM confidence)
- oidref.com prtMarkerSuppliesLevel OID detail — table index structure confirmed against multiple monitoring tool references: https://oidref.com/1.3.6.1.2.1.43.11.1.1.9
- Lexmark SNMP MIBs article (Feb 2025) — confirms Lexmark uses standard Printer-MIB RFC1759/RFC3805 for supply data; MIB download available: https://support.lexmark.com/content/support/guides/en/v55265344/setup-installation-and-configuration-issues/lexmark-snmp-mibs-and-oid-values-explained-may-201.html
- exchangelib PyPI — version 5.6.0 confirmed current, Python >=3.10 required: https://pypi.org/project/exchangelib/
- jsonlines library docs — append mode context manager pattern: https://jsonlines.readthedocs.io/

### Tertiary (LOW confidence — validate against device)
- Community monitoring documentation suggesting Black=1, Cyan=2, Magenta=3, Yellow=4 index order — not officially confirmed for XC2235 specifically; must verify against physical device.
- pysnmp-sync-adapter API surface (`get_cmd_sync` exact signature) — derived from PyPI description and GitHub README; not from Context7 or official structured docs.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pysnmp v7 + sync adapter, exchangelib 5.6.0, jsonlines all verified via PyPI and official docs
- Architecture: HIGH — TypedDict for LangGraph confirmed via official LangGraph docs; QualityFlag enum pattern is straightforward Python; OID structure confirmed via RFC 3805
- Pitfalls: HIGH (pysnmp v7 breaking change confirmed via changelog) / MEDIUM (OID index ordering — theoretical risk confirmed by Printer-MIB spec variability, not XC2235-specific)
- Lexmark OID indices: LOW — must verify against physical device; do not hardcode

**Research date:** 2026-02-28
**Valid until:** 2026-03-30 (stable libraries; pysnmp and exchangelib have slow release cadences)
