# Phase 3: LLM Analyst - Research

**Researched:** 2026-03-01
**Domain:** LLM integration (langchain-openai, OpenAI structured outputs, trend analysis, policy guard extension)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Trend history window:** Look back 7 days from current poll timestamp. Use ALL readings in the window (no sampling). Up to ~168 data points. Source: existing JSONL log at logs/printer_history.jsonl.
- **Cold start behavior:** Fewer than 3 readings in 7-day window = cold start. Fall back to Phase 2 deterministic threshold logic. Do NOT call the LLM on cold start.
- **Analyst output structure:** Produce both qualitative label ("Declining rapidly") AND specific estimate ("~5 days to depletion"). Combined format: "Declining rapidly — estimated ~5 days to depletion". Confidence: float 0.0–1.0, self-reported by the LLM. Depletion estimate uses days remaining only — no absolute calendar dates.
- **Email content:** Add a new "Analysis" section BELOW the existing toner level details block (additive, not replacement). Reasoning: 2–3 sentences. Confidence score shown numerically: "Confidence: 0.87". See CONTEXT.md for the exact format example.
- **Confidence scoring — what drives score down:** Too few history points (cold start = fallback, not LLM scoring). Erratic/noisy readings: toner % jumps up and down inconsistently (high standard deviation). Other factors are Claude's discretion.
- **Confidence suppression logging:** When alert suppressed due to low confidence, log: reason + score + contributing factors. Example: `"suppressed: confidence=0.62, reason=erratic_readings, std_dev=14%"`. Same JSONL log and same suppression_reason field in AgentState.
- **Policy guard — confidence check placement:** Add confidence as the FOURTH and FINAL check in run_policy_guard(). Order: freshness → SNMP quality → rate limit → confidence. Only call LLM if all cheap deterministic checks pass first.
- **LLM failure fallback:** On any LLM API failure: fall back to Phase 2 deterministic threshold logic immediately (no retry). Alert email note: "Note: LLM analysis unavailable — alert based on threshold check only." Log event_type=llm_failure to JSONL with timestamp and error details. Python logger also receives the error.

### Claude's Discretion

- Specific LLM prompt structure and system/user message design
- How std_dev threshold is defined for "erratic readings"
- How to handle partial confidence factors (e.g. when only some colors are erratic)
- Token budget / context window management for 168-entry history
- AgentState field names for the new confidence score and LLM reasoning fields

### Deferred Ideas (OUT OF SCOPE)

- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ANLZ-02 | LLM Analyst Agent self-reports a confidence score (0.0-1.0) alongside its analysis output as a structured field | `with_structured_output` / Pydantic BaseModel schema enforces float field; LLM fills it as part of analysis |
| ANLZ-03 | LLM Analyst Agent produces a natural language explanation of its reasoning included in the outbound alert email | Pydantic schema includes `reasoning: str` field; communicator.build_body() extended with optional llm_reasoning param |
| ANLZ-04 | LLM Analyst Agent applies trend-aware urgency — fast-dropping toner flagged with higher urgency than slow decline at same level | Depletion velocity (pct/day) computed from history, passed to LLM prompt; LLM sets urgency label accordingly |
| GURD-02 | Policy Guard blocks alert sending if LLM Analyst confidence score falls below configured minimum threshold (default 0.7) | 4th check in run_policy_guard() reads `state["llm_confidence"]`; suppression logged with reason string |
</phase_requirements>

---

## Summary

Phase 3 transforms the deterministic threshold checker in `agents/analyst.py` into an LLM-powered trend analyst. The core work is: (1) load and preprocess 7-day toner history from the JSONL log, (2) call an OpenAI model via `langchain-openai` with a structured-output Pydantic schema to produce a confidence score and reasoning, (3) add `llm_confidence` and `llm_reasoning` to AgentState, (4) extend the policy guard with a 4th check on confidence, and (5) extend the communicator's email body with an "Analysis" section.

The technical approach is straightforward: `langchain-openai` with `ChatOpenAI.with_structured_output(AnalystOutput)` enforces the schema at the LLM boundary, eliminating manual JSON parsing. The `pydantic` library (v2) validates the structured response and the confidence float. Exception handling wraps the LLM call and immediately falls back to Phase 2 logic on any failure, with no retry. The history preprocessing is pure Python `statistics` stdlib — no numpy needed for std_dev on 168 data points.

The project venv currently has no LangChain or OpenAI packages installed (confirmed: only jsonlines, pysnmp, pytest, python-dotenv are present). Both `langchain-openai` and `openai` must be added to `requirements.txt` and installed. No LangGraph changes are needed — the pipeline remains a sequential function call in Phase 3 (LangGraph StateGraph wiring is deferred to Phase 4).

**Primary recommendation:** Use `langchain-openai>=0.3.0` with `ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(AnalystOutput, method="json_schema")` and a Pydantic v2 `BaseModel` for the output schema. Wrap in a `try/except Exception` block that immediately falls back to deterministic logic and logs `event_type=llm_failure`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langchain-openai | >=0.3.0 (latest: 1.1.10, released 2026-02-17) | ChatOpenAI with structured output | Official LangChain OpenAI integration; `with_structured_output` enforces Pydantic schema at LLM boundary |
| openai | >=1.0.0 (latest: 2.24.0, released 2026-02-24) | OpenAI API client (transitive dep of langchain-openai) | Required by langchain-openai; provides exception classes (APIConnectionError, APITimeoutError, RateLimitError) |
| pydantic | >=2.0 (already in venv as transitive dep of langchain) | AnalystOutput structured schema | Enforces float confidence score, str fields; validation errors are catchable |
| langchain-core | >=0.3.0 (already required by langchain-openai) | ChatPromptTemplate, SystemMessage, HumanMessage | Standard LangChain message construction |
| statistics (stdlib) | Python 3.12 stdlib | std_dev for erratic-readings detection | No additional dependency; `statistics.stdev()` handles sample std dev correctly |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | >=1.0.0 (already installed) | Load OPENAI_API_KEY from .env | Already in use for all other env vars |
| pytest | 9.0.2 (already installed) | Test LLM logic via mock | Already installed; USE_MOCK_LLM env var pattern for test isolation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| langchain-openai | openai Python SDK directly | Direct SDK has less abstraction; `client.beta.chat.completions.parse()` works but requires more boilerplate than `with_structured_output`; LangChain is already declared in requirements.txt |
| langchain-openai | langchain-anthropic | Anthropic also supports `with_structured_output`; no preference — use OpenAI since it's the simpler path given no existing LLM provider in the project |
| pydantic BaseModel | TypedDict | TypedDict gives no validation; Pydantic v2 gives float range validation and clear parse errors |
| statistics.stdev() | numpy.std() | numpy is not installed; stdlib is sufficient for ≤168 floats |

**Installation:**
```bash
pip install "langchain-openai>=0.3.0" "openai>=1.0.0"
```

Add to `requirements.txt`:
```
langchain-openai>=0.3.0
openai>=1.0.0
```

---

## Architecture Patterns

### Recommended Project Structure

No new directories. All changes are modifications to existing files:

```
agents/
  analyst.py           # REPLACE core logic — keep run_analyst() signature
state_types.py         # ADD llm_confidence, llm_reasoning fields to AgentState
guardrails/
  safety_logic.py      # ADD check_confidence() as 4th check in run_policy_guard()
agents/
  communicator.py      # EXTEND build_body() to accept optional llm_reasoning
requirements.txt       # ADD langchain-openai, openai
tests/
  test_analyst.py      # EXTEND with LLM mock tests (new test cases)
  test_safety_logic.py # EXTEND with confidence suppression test cases
  test_communicator.py # EXTEND with Analysis section in email body tests
```

### Pattern 1: Structured Output with Pydantic Schema

**What:** Define a Pydantic `BaseModel` for LLM output; pass to `with_structured_output()`. The LLM is constrained to return a JSON object matching the schema. The result is a validated Python object, not a raw string.

**When to use:** Any time an LLM must return structured data with predictable fields. Eliminates manual JSON parsing and string extraction.

**Example:**
```python
# Source: https://docs.langchain.com/oss/python/integrations/chat/openai (verified 2026-03-01)
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

class AnalystOutput(BaseModel):
    """Structured output from the LLM toner analyst."""
    trend_label: str = Field(
        description="Short qualitative label, e.g. 'Declining rapidly' or 'Stable'"
    )
    depletion_estimate_days: float | None = Field(
        description="Estimated days until depletion; None if toner is stable"
    )
    confidence: float = Field(
        description="Self-reported confidence score from 0.0 (no confidence) to 1.0 (very confident)"
    )
    reasoning: str = Field(
        description="2-3 sentence natural language explanation of the analysis"
    )

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
structured_llm = llm.with_structured_output(AnalystOutput, method="json_schema")
result: AnalystOutput = structured_llm.invoke(messages)
# result.confidence is a validated float; result.reasoning is a str
```

### Pattern 2: ChatPromptTemplate with System + Human Messages

**What:** Separate system-level instructions (role, output format, constraints) from the user-level data payload (history, current readings). This produces better LLM output than single-message prompts.

**When to use:** Always for analyst calls. The system message describes the analyst's role and output format once; the human message contains the per-poll data.

**Example:**
```python
# Source: LangChain docs + project pattern
from langchain_core.messages import SystemMessage, HumanMessage

SYSTEM_PROMPT = """You are a printer supply analyst for Project Sentinel.
Analyze toner level history and produce a structured assessment.

Rules:
- confidence reflects data quality: noisy/erratic readings = lower confidence
- depletion_estimate_days is days from NOW until toner hits 0%, based on trend rate
- trend_label must be one of: "Stable", "Declining slowly", "Declining rapidly", "Critically low"
- reasoning must be 2-3 sentences covering: trend, estimate, confidence factors
- If toner is above threshold or rising, set depletion_estimate_days to null
"""

def build_analyst_messages(color: str, history_summary: str, current_pct: float) -> list:
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"""
Color: {color}
Current level: {current_pct}%
History (last 7 days, chronological):
{history_summary}

Analyze this toner and return a structured assessment.
"""),
    ]
```

### Pattern 3: History Preprocessing Before LLM Call

**What:** Compute depletion velocity and std_dev from raw JSONL history in Python before calling the LLM. Pass pre-computed stats to the LLM rather than raw data — this reduces token usage and produces more reliable analysis.

**When to use:** Always. Raw 168-entry JSONL history costs ~2,000+ tokens; pre-computed stats cost ~100 tokens.

**Example:**
```python
# Source: Python stdlib statistics module
import statistics
from datetime import datetime, timedelta, timezone

def load_color_history(
    color: str,
    log_path: Path,
    window_days: int = 7,
) -> list[float]:
    """Return list of toner_pct values for color within the 7-day window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    history = read_poll_history(log_path=log_path)
    values = []
    for record in history:
        if record.get("event_type"):
            continue  # skip non-poll records (suppression events, llm_failure)
        ts = datetime.fromisoformat(record["timestamp"])
        if ts < cutoff:
            continue
        for reading in record.get("readings", []):
            if reading["color"] == color and reading.get("toner_pct") is not None:
                values.append(reading["toner_pct"])
    return values

def compute_history_stats(values: list[float]) -> dict:
    """Compute depletion velocity and erratic-readings flags."""
    n = len(values)
    if n < 2:
        return {"n": n, "std_dev": None, "velocity_pct_per_day": None}
    std_dev = statistics.stdev(values)  # sample stdev (Bessel's correction)
    # Velocity: negative = declining; estimate from first/last with time span
    # Simple linear: (last - first) / n_hours * 24 per day
    # Caller must supply timestamps for accurate velocity — pass as paired list
    return {"n": n, "std_dev": round(std_dev, 2)}
```

### Pattern 4: LLM Failure Fallback

**What:** Catch all exceptions from the LLM call at the agent boundary. Log the failure to JSONL as `event_type=llm_failure`. Return state with fallback flag set. The analyst returns to Phase 2 deterministic result but sets `llm_confidence=None` and `llm_reasoning=None`.

**When to use:** Always. The LLM call is the only external network call in the analyst node.

**Example:**
```python
# Source: Project pattern — consistent with existing try/except in snmp_adapter.py
import logging

logger = logging.getLogger(__name__)

def call_llm_analyst(messages: list, log_path: Path) -> AnalystOutput | None:
    """
    Call LLM with structured output. Returns None on any failure.
    Logs event_type=llm_failure to JSONL on exception.
    """
    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        structured_llm = llm.with_structured_output(AnalystOutput, method="json_schema")
        return structured_llm.invoke(messages)
    except Exception as exc:  # covers APIConnectionError, APITimeoutError, ValidationError, etc.
        logger.error("LLM analyst failed: %s: %s", type(exc).__name__, exc)
        append_poll_result(
            {
                "event_type": "llm_failure",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
            },
            log_path=log_path,
        )
        return None
```

### Pattern 5: AgentState Extension

**What:** Add `llm_confidence` and `llm_reasoning` fields to `AgentState` TypedDict in `state_types.py`.

**When to use:** Required — the policy guard reads `llm_confidence` and the communicator reads `llm_reasoning`.

**Example:**
```python
# state_types.py addition
class AgentState(TypedDict):
    poll_result: Optional[PollResult]
    alert_needed: bool
    alert_sent: bool
    suppression_reason: Optional[str]
    decision_log: Annotated[list[str], operator.add]
    flagged_colors: Optional[list]
    llm_confidence: Optional[float]    # NEW: 0.0–1.0 or None if LLM not called
    llm_reasoning: Optional[str]       # NEW: 2-3 sentence reasoning or None
```

### Pattern 6: Policy Guard 4th Check

**What:** Add `check_confidence()` as the 4th short-circuit check in `run_policy_guard()`, after rate limit passes.

**When to use:** Must follow existing `(bool, Optional[str])` return tuple pattern.

**Example:**
```python
# guardrails/safety_logic.py addition — same pattern as existing check_rate_limit()
def check_confidence(state: "AgentState") -> tuple[bool, Optional[str]]:
    """Check LLM confidence meets minimum threshold."""
    threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))
    confidence = state.get("llm_confidence")
    if confidence is None:
        # LLM not called (cold start or LLM failure) — do not suppress on confidence
        return True, None
    if confidence < threshold:
        reason = f"suppressed: confidence={confidence:.2f}, threshold={threshold}"
        return False, reason
    return True, None
```

### Anti-Patterns to Avoid

- **Passing raw JSONL entries to the LLM:** 168 entries × ~50 tokens each = 8,400 tokens per call. Pre-compute stats and pass a compact summary instead.
- **Retrying on LLM failure:** CONTEXT.md is explicit: no retry — fall back immediately. A retry loop adds latency to every alert cycle.
- **Using `json_mode` instead of `json_schema`:** `json_mode` returns valid JSON but does NOT enforce the field schema. Use `method="json_schema"` for guaranteed field compliance.
- **Accessing `result.confidence` without checking for None:** `with_structured_output` will raise if the LLM returns invalid output; wrap in try/except, do not assume success.
- **Using `pydantic.v1` import:** Some older LangChain examples use `from langchain_core.pydantic_v1 import BaseModel`. Use `from pydantic import BaseModel` (Pydantic v2) consistently with the rest of the project.
- **Appending Analysis section unconditionally:** `build_body()` must only append the Analysis section when `llm_reasoning is not None`. Fallback alerts must not show an empty Analysis section.
- **Not initializing `llm_confidence` and `llm_reasoning` in AgentState:** These must have `None` defaults in the initial state built by supervisor, or KeyError will occur when the policy guard reads them before the analyst runs.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured JSON parsing from LLM | Custom JSON extraction regex, response.content string splitting | `ChatOpenAI.with_structured_output(AnalystOutput, method="json_schema")` | LLM output is non-deterministic; manual parsing breaks on whitespace/formatting variance |
| Confidence range validation | Manual `if 0.0 <= score <= 1.0` checks everywhere | Pydantic `Field(ge=0.0, le=1.0)` on the confidence field | Validation runs at LLM boundary; downstream code can trust the float |
| Sample standard deviation | Custom loop computing mean then squared differences | `statistics.stdev()` (Python stdlib) | Handles edge cases, uses Bessel's correction (N-1) by default, no new dependency |
| LLM exception hierarchy | Checking `isinstance(exc, SomeClass)` for 5 OpenAI exception types | `except Exception` at the outer boundary, log type name in `error_type` field | The project pattern for fallback is "any exception = fall back"; distinguishing timeout vs. rate limit adds no value here |
| Prompt token counting | tiktoken integration to count tokens before call | Compact pre-processed history summary (stats, not raw data) | Keeps prompt <1,000 tokens for 168 readings; no new dependency needed |

**Key insight:** `with_structured_output` is the most important "don't hand-roll" item in this phase. Every custom approach to parsing LLM JSON output has failed silently in production systems. Let LangChain enforce the contract at the boundary.

---

## Common Pitfalls

### Pitfall 1: `llm_confidence=None` Blocks Alert When Confidence Check Runs Before LLM Node

**What goes wrong:** If the analyst sets `llm_confidence=None` (cold start or LLM failure) and `check_confidence()` treats `None` as a failing check, all cold-start and LLM-failure alerts get suppressed — silent alert failure.

**Why it happens:** Check 4 runs after check 3 (rate limit passes). If confidence is None, the guard would suppress unless None is explicitly handled as "pass through."

**How to avoid:** `check_confidence()` must return `(True, None)` when `llm_confidence is None`. The suppression logging for cold start / LLM failure happens in the analyst node itself, not in the policy guard.

**Warning signs:** In tests, cold-start state flows to run_policy_guard and alert_needed becomes False when it should be True.

### Pitfall 2: Non-Poll Records in JSONL History Contaminate toner_pct Values

**What goes wrong:** The JSONL log contains `suppressed_alert` records and `llm_failure` records (event_type is set). Iterating all records to extract toner_pct reads these non-poll records, which have no `readings` key, causing KeyError or wrong data.

**Why it happens:** `append_poll_result()` writes any dict to the JSONL — it's used for both poll results and suppression/failure events.

**How to avoid:** Filter records in history loading: skip any record with an `event_type` field (those are administrative records, not poll results). Poll result records do not have this field.

**Warning signs:** KeyError on `record["readings"]` or unexpectedly low reading counts in unit tests that write suppression events alongside poll events.

### Pitfall 3: `statistics.stdev()` Raises on n=1

**What goes wrong:** `statistics.stdev()` requires at least 2 values. Called on a single-reading history list (rare but possible after filter), it raises `statistics.StatisticsError`.

**Why it happens:** Cold start threshold is 3, but history loading for a specific color (e.g., cyan only) may return fewer readings than the total history count.

**How to avoid:** Guard `stdev()` call: `if len(values) >= 2: std_dev = statistics.stdev(values)`. Per-color history length may differ from total poll count if some polls had SNMP errors for that color.

**Warning signs:** `StatisticsError: variance requires at least two data points` during test or runtime.

### Pitfall 4: Pydantic v1 vs v2 Import Path

**What goes wrong:** Some LangChain examples use `from langchain_core.pydantic_v1 import BaseModel`. This imports Pydantic v1 compatibility layer, which conflicts with Pydantic v2 behavior in the rest of the project.

**Why it happens:** Older LangChain versions bundled pydantic v1 shims. Current langchain-openai 1.x works with Pydantic v2 natively.

**How to avoid:** Always use `from pydantic import BaseModel, Field` (no `langchain_core.pydantic_v1`).

**Warning signs:** `ImportError` or unexpected validation behavior; `Field(ge=0.0, le=1.0)` not enforced.

### Pitfall 5: Token Budget for 168-Entry History

**What goes wrong:** Passing 168 JSONL poll records verbatim to the LLM as part of the prompt consumes ~6,000–10,000 tokens per call. On gpt-4o-mini this costs ~$0.001–$0.002 per poll and may hit context limits.

**Why it happens:** Raw JSONL has many redundant fields (`raw_value`, `max_capacity`, `quality_flag`, etc.) that the LLM doesn't need.

**How to avoid:** Pre-compute a compact statistics summary to send instead of raw records. For each color: `[first_pct, last_pct, min_pct, max_pct, std_dev, n_readings, velocity_pct_per_day]`. This reduces the history payload to ~100 tokens per color (400 total for CMYK).

**Warning signs:** Costs increasing with polling history growth; `ContextLengthExceededError` after the system runs for several months.

### Pitfall 6: Missing `llm_confidence` / `llm_reasoning` in Initial AgentState

**What goes wrong:** The policy guard reads `state.get("llm_confidence")` after the analyst runs, but the initial AgentState constructed in supervisor has no `llm_confidence` key. On cold start or no-alert paths where the analyst skips, the guard raises KeyError or behaves unexpectedly.

**Why it happens:** TypedDict fields must be initialized — they don't have defaults automatically.

**How to avoid:** The supervisor's initial state dict must include `"llm_confidence": None, "llm_reasoning": None`. Also update `_make_state()` fixtures in all test files to include these fields.

**Warning signs:** `KeyError: 'llm_confidence'` in policy guard tests; test_safety_logic.py tests failing after AgentState update.

---

## Code Examples

Verified patterns from official sources:

### AnalystOutput Pydantic Schema

```python
# Source: LangChain docs (https://docs.langchain.com/oss/python/integrations/chat/openai, verified 2026-03-01)
from pydantic import BaseModel, Field

class AnalystOutput(BaseModel):
    """Structured output contract for the LLM toner analyst."""
    trend_label: str = Field(
        description=(
            "Qualitative trend label. One of: 'Stable', 'Declining slowly', "
            "'Declining rapidly', 'Critically low'"
        )
    )
    depletion_estimate_days: float | None = Field(
        description=(
            "Estimated days from now until toner is depleted at the current rate. "
            "None if toner is stable or rising."
        )
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Self-reported confidence in this analysis from 0.0 (very uncertain) "
            "to 1.0 (very confident). Lower when readings are erratic or sparse."
        )
    )
    reasoning: str = Field(
        description=(
            "2-3 sentence natural language explanation: trend description, "
            "depletion estimate, and main confidence factors."
        )
    )
```

### Full LLM Analyst Call with Fallback

```python
# Source: Derived from LangChain + OpenAI docs; project pattern for fallback
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from adapters.persistence import append_poll_result, read_poll_history

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a printer supply analyst. Given toner level statistics \
from the last 7 days, produce a structured assessment.

Output requirements:
- trend_label: one of "Stable", "Declining slowly", "Declining rapidly", "Critically low"
- depletion_estimate_days: float (days to depletion at current rate) or null if stable/rising
- confidence: float 0.0–1.0 reflecting data quality (lower when std_dev is high)
- reasoning: 2-3 sentences covering trend, estimate, and confidence factors
"""

def call_llm_analyst(
    color: str,
    current_pct: float,
    n_readings: int,
    velocity_pct_per_day: float | None,
    std_dev: float | None,
    log_path: Path,
) -> Optional["AnalystOutput"]:
    """
    Call LLM with pre-computed history stats. Returns None on any failure.
    Logs event_type=llm_failure on exception.
    """
    history_summary = (
        f"  readings in window: {n_readings}\n"
        f"  depletion velocity: {velocity_pct_per_day:.2f}%/day (negative = declining)\n"
        f"  reading std_dev: {std_dev:.2f}% (high = erratic readings)\n"
        f"  current level: {current_pct}%"
        if velocity_pct_per_day is not None and std_dev is not None
        else f"  readings in window: {n_readings}\n  current level: {current_pct}%"
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Color: {color}\n{history_summary}"),
    ]
    try:
        llm = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            temperature=0,
        )
        structured_llm = llm.with_structured_output(AnalystOutput, method="json_schema")
        return structured_llm.invoke(messages)
    except Exception as exc:
        logger.error("LLM analyst failed: %s: %s", type(exc).__name__, exc)
        append_poll_result(
            {
                "event_type": "llm_failure",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
            },
            log_path=log_path,
        )
        return None
```

### History Stats Preprocessing

```python
# Source: Python stdlib statistics module (https://docs.python.org/3/library/statistics.html)
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

def compute_color_stats(
    color: str,
    log_path: Path,
    window_days: int = 7,
) -> dict:
    """
    Load 7-day history for one color and compute depletion stats.

    Returns:
        {
          "n": int,
          "std_dev": float | None,
          "velocity_pct_per_day": float | None,  # negative = declining
          "values": list[float],  # chronological toner_pct values
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    history = read_poll_history(log_path=log_path)

    values = []
    for record in history:
        if record.get("event_type"):  # skip suppression/llm_failure records
            continue
        ts = datetime.fromisoformat(record["timestamp"])
        if ts < cutoff:
            continue
        for reading in record.get("readings", []):
            if reading["color"] == color and reading.get("toner_pct") is not None:
                values.append(reading["toner_pct"])

    n = len(values)
    if n < 2:
        return {"n": n, "std_dev": None, "velocity_pct_per_day": None, "values": values}

    std_dev = statistics.stdev(values)  # sample stdev (Bessel's correction, n-1)
    # Simple linear velocity: total drop / n_intervals (where each interval = poll_period)
    # Negative = declining, positive = rising
    velocity_pct_per_day = (values[-1] - values[0]) / (len(values) - 1) * 24  # assuming hourly polls

    return {
        "n": n,
        "std_dev": round(std_dev, 2),
        "velocity_pct_per_day": round(velocity_pct_per_day, 3),
        "values": values,
    }
```

### Mock LLM for Tests (USE_MOCK_LLM pattern)

```python
# Source: Project pattern (USE_MOCK_SNMP, USE_MOCK_SMTP already established)
# In agents/analyst.py:
import os

USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "false").lower() == "true"

def _mock_analyst_output(current_pct: float) -> "AnalystOutput":
    """Return deterministic AnalystOutput for test isolation."""
    return AnalystOutput(
        trend_label="Declining rapidly",
        depletion_estimate_days=5.0,
        confidence=0.85,
        reasoning=(
            f"Toner at {current_pct}% with a steady decline over the history window. "
            "Depletion estimated in approximately 5 days at current rate. "
            "Confidence is high due to consistent readings."
        ),
    )

# In call_llm_analyst():
if USE_MOCK_LLM:
    return _mock_analyst_output(current_pct)
```

### Policy Guard Confidence Check (4th check)

```python
# Source: Project pattern — follows check_rate_limit() signature exactly
def check_confidence(state: "AgentState") -> tuple[bool, Optional[str]]:
    """
    Check LLM confidence meets minimum threshold.

    Returns (True, None) if confidence is None — LLM was not called (cold start
    or LLM failure). These cases are already handled by the analyst node.

    Returns:
        (True, None) if confidence is acceptable or LLM was not called.
        (False, reason_str) if confidence < threshold.
    """
    threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))
    confidence = state.get("llm_confidence")

    if confidence is None:
        return True, None  # LLM not called — do not block on confidence

    if confidence < threshold:
        std_dev_note = ""
        # Extract contributing factors from state if available
        reason = (
            f"suppressed: confidence={confidence:.2f}, "
            f"threshold={threshold}{std_dev_note}"
        )
        return False, reason

    return True, None
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON parsing from LLM response strings | `with_structured_output(Schema, method="json_schema")` | LangChain 0.2+ / OpenAI Aug 2024 Structured Outputs | 100% schema compliance vs. ~35% with manual prompting alone |
| `from langchain_core.pydantic_v1 import BaseModel` | `from pydantic import BaseModel` (Pydantic v2) | LangChain 0.3+ | Remove compatibility shim; Pydantic v2 is default |
| `json_mode` method | `json_schema` method | langchain-openai 0.3+ | `json_schema` enforces field names; `json_mode` only guarantees valid JSON |
| Separate openai and langchain packages | `langchain-openai` partner package | LangChain 0.2 | langchain-openai bundles the OpenAI integration; langchain-community.chat_models.openai is deprecated |

**Deprecated/outdated:**
- `from langchain.chat_models import ChatOpenAI`: Deprecated; use `from langchain_openai import ChatOpenAI`
- `create_structured_output_chain()`: Deprecated legacy chain; use `llm.with_structured_output()` directly
- `langchain_community.chat_models.openai`: Deprecated; use `langchain_openai`

---

## Open Questions

1. **Erratic readings std_dev threshold**
   - What we know: CONTEXT.md says high std_dev = lower confidence; the specific threshold is Claude's discretion
   - What's unclear: What std_dev value (as a % of toner scale) constitutes "erratic"? Is 5% high? 15%?
   - Recommendation: Use 10% as the default "high erratic" threshold (configurable via env var `ERRATIC_STD_DEV_THRESHOLD`). At 10% std_dev on a 0–100 scale, readings are swinging 20% peak-to-peak, which is genuinely noisy for a slowly depleting supply.

2. **Per-color vs. whole-poll cold start**
   - What we know: Cold start is "fewer than 3 readings in the 7-day window." Window is per printer, not per color.
   - What's unclear: Should cold start be checked per-color (some colors may have missing readings) or globally for the poll?
   - Recommendation: Check per color. Each color's history is loaded independently. If cyan has <3 readings but magenta has 50, run LLM for magenta and fall back for cyan.

3. **Depletion velocity accuracy with non-uniform polling**
   - What we know: Polling is hourly but may miss intervals (system downtime, SNMP errors). The "168 entries" assumes perfect hourly polling.
   - What's unclear: How to compute velocity when the time gap between readings is variable.
   - Recommendation: Use actual timestamps from the JSONL records, not assumed hourly intervals. Compute `(last_pct - first_pct) / elapsed_hours * 24` for pct/day using real timestamps from the first and last readings in the window.

4. **LLM_MODEL env var**
   - What we know: Model is not explicitly locked in CONTEXT.md — discretion to choose model.
   - What's unclear: Should the model be configurable or hardcoded to gpt-4o-mini?
   - Recommendation: Use `os.getenv("LLM_MODEL", "gpt-4o-mini")` for configurability. Document in .env template.

---

## Validation Architecture

> `workflow.nyquist_validation` is not present in `.planning/config.json` — the key does not exist in the config. Research treats this as false; the Validation Architecture section is included because the project uses pytest and has a well-established test pattern.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none — `sys.path.insert` in each test file |
| Quick run command | `.venv/bin/python.exe -m pytest tests/test_analyst.py tests/test_safety_logic.py tests/test_communicator.py -x -q` |
| Full suite command | `.venv/bin/python.exe -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ANLZ-02 | LLM returns confidence float 0.0–1.0 in structured output | unit (mock LLM) | `.venv/bin/python.exe -m pytest tests/test_analyst.py::test_llm_output_has_confidence_score -x` | ❌ Wave 0 |
| ANLZ-03 | Email body includes Analysis section with reasoning text | unit | `.venv/bin/python.exe -m pytest tests/test_communicator.py::test_build_body_includes_analysis_section -x` | ❌ Wave 0 |
| ANLZ-04 | Fast-dropping toner gets "Declining rapidly" label; slow decline gets "Declining slowly" | unit (mock LLM) | `.venv/bin/python.exe -m pytest tests/test_analyst.py::test_velocity_affects_trend_label -x` | ❌ Wave 0 |
| GURD-02 | Policy guard suppresses alert when confidence < 0.7 | unit | `.venv/bin/python.exe -m pytest tests/test_safety_logic.py::test_low_confidence_suppresses_alert -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/python.exe -m pytest tests/ -q`
- **Per wave merge:** `.venv/bin/python.exe -m pytest tests/ -q`
- **Phase gate:** Full suite green (74 existing + new tests)

### Wave 0 Gaps

- [ ] `tests/test_analyst.py` — new test cases for LLM mock path, confidence score output, cold start fallback, LLM failure fallback
- [ ] `tests/test_safety_logic.py` — new test cases for `check_confidence()` and confidence-based suppression logging
- [ ] `tests/test_communicator.py` — new test cases for Analysis section in `build_body()` with/without `llm_reasoning`
- [ ] `requirements.txt` — add `langchain-openai>=0.3.0` and `openai>=1.0.0`; install in venv before any tests run

---

## Sources

### Primary (HIGH confidence)

- `https://docs.langchain.com/oss/python/integrations/chat/openai` — ChatOpenAI integration, `with_structured_output`, Pydantic BaseModel, temperature=0, message format (verified 2026-03-01)
- `https://pypi.org/project/langchain-openai/` — langchain-openai 1.1.10 (latest as of 2026-02-17); Python >=3.10 requirement (verified 2026-03-01)
- `https://pypi.org/project/openai/` — openai 2.24.0 (latest as of 2026-02-24); Python >=3.9 (verified 2026-03-01)
- `https://developers.openai.com/cookbook/examples/structured_outputs_intro` — `client.beta.chat.completions.parse()` pattern; supported models: gpt-4o-mini, gpt-4o-2024-08-06 and future models (verified 2026-03-01)
- Python stdlib `statistics` module — `statistics.stdev()` requires n≥2, uses Bessel's correction by default

### Secondary (MEDIUM confidence)

- `https://mirascope.com/blog/langchain-structured-output` — Three structured output methods; `json_schema` vs `json_mode` difference; common pitfalls (cross-verified with LangChain docs)
- `https://reference.langchain.com/v0.3/python/openai/chat_models/langchain_openai.chat_models.base.ChatOpenAI.html` — ChatOpenAI structured output Pydantic example; `OpenAIRefusalError` / `OpenAIContextOverflowError` exception types

### Tertiary (LOW confidence)

- WebSearch: Exception class names (`APIConnectionError`, `APITimeoutError`, `RateLimitError`) from openai package — import from `openai` directly, not from LangChain; project uses broad `except Exception` for fallback anyway

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — langchain-openai 1.1.10 and openai 2.24.0 versions confirmed via PyPI; with_structured_output Pydantic pattern confirmed via official LangChain docs
- Architecture: HIGH — patterns derived from existing project code (state_types.py, safety_logic.py, communicator.py) plus verified LangChain docs
- Pitfalls: HIGH — most pitfalls sourced from direct code inspection of existing project files and official docs; one MEDIUM (token budget estimate based on general LLM token overhead guidance)

**Research date:** 2026-03-01
**Valid until:** 2026-04-01 (langchain-openai moves fast; re-verify if installation fails)
