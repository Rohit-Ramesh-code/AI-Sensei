# Phase 3: LLM Analyst - Context

**Gathered:** 2026-03-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Transform the existing deterministic threshold checker (analyst.py) into an LLM-powered analyst that reads toner trend history, produces a confidence-scored analysis with natural language reasoning, and gates alerts on that confidence score. The policy guard gains a fourth check: confidence threshold. The communicator gains an "Analysis" section in the email body. LangGraph StateGraph wiring is NOT in scope — that is Phase 4.

</domain>

<decisions>
## Implementation Decisions

### Trend history window
- Look back 7 days from the current poll timestamp
- Use ALL readings within the window (no sampling/deduplication)
- Up to ~168 data points (hourly polls over 7 days)
- Source: existing JSONL log at logs/printer_history.json

### Cold start behavior
- Minimum data threshold: fewer than 3 readings in the 7-day window = cold start
- Cold start action: fall back to Phase 2 deterministic threshold logic (same as LLM failure fallback)
- Do NOT call the LLM on cold start — no trend to analyze

### Analyst output structure
- Produce both: qualitative label ("Declining rapidly") AND specific estimate ("~5 days to depletion")
- Combined format: "Declining rapidly — estimated ~5 days to depletion"
- Confidence score: float 0.0–1.0, self-reported by the LLM alongside the analysis
- Depletion estimate uses days remaining only — no absolute calendar dates

### Email content
- Add a new "Analysis" section BELOW the existing toner level details block (additive, not replacement)
- Reasoning: 2–3 sentences covering trend description, depletion estimate, and confidence
- Confidence score shown numerically in the email body: "Confidence: 0.87"
- Example format:
  ```
  Printer: 192.168.1.100

  Low toner detected:
    Cyan: 12.0% [CRITICAL]
    Recommended action: Order cyan toner

  Analysis:
  Cyan toner dropped from 45% to 12% over 4 days, a decline rate of ~8%/day.
  At this rate, depletion is estimated in ~1 day. Confidence: 0.91.
  ```

### Confidence scoring — what drives score down
- Too few history points (below the cold-start minimum — this triggers fallback, not LLM scoring)
- Erratic / noisy readings: toner % jumps up and down inconsistently (high standard deviation)
- Other factors (conflicting CMYK signals, gapped history) are Claude's discretion

### Confidence suppression logging
- When alert is suppressed due to low confidence, log: reason + score + contributing factors
- Example: `"suppressed: confidence=0.62, reason=erratic_readings, std_dev=14%"`
- Same JSONL log (printer_history.jsonl) and same suppression_reason field in AgentState

### Policy guard — confidence check placement
- Add confidence as the FOURTH and FINAL check in run_policy_guard()
- Order: freshness → SNMP quality → rate limit → confidence
- Rationale: only call LLM if all cheap deterministic checks pass first

### LLM failure fallback
- On any LLM API failure (timeout, exception, error response): fall back to Phase 2 deterministic threshold logic
- No retry — fall back immediately
- Alert email includes a note: "Note: LLM analysis unavailable — alert based on threshold check only."
- LLM failure is logged to printer_history.jsonl as event_type=llm_failure with timestamp and error details
- Python logger also receives the error (in addition to JSONL log)

### LLM backend
- Ollama running on a separate powerful machine, accessed remotely via its OpenAI-compatible API endpoint
- Use `langchain-openai` (`ChatOpenAI`) — no new package needed; point `base_url` at the Ollama server
- Environment variables: `OLLAMA_BASE_URL` (e.g. `http://192.168.x.x:11434/v1`), `OLLAMA_MODEL` (e.g. `llama3.2`), `OLLAMA_API_KEY` (dummy value, default `"ollama"`)
- `with_structured_output(method="json_schema")` support is model-dependent — test with the chosen model; fall back to `method="json_mode"` if `json_schema` is unsupported
- No `OPENAI_API_KEY` required — Ollama does not use OpenAI authentication

### Claude's Discretion
- Specific LLM prompt structure and system/user message design
- How std_dev threshold is defined for "erratic readings"
- How to handle partial confidence factors (e.g. when only some colors are erratic)
- Token budget / context window management for 168-entry history
- AgentState field names for the new confidence score and LLM reasoning fields
- Whether to use `method="json_schema"` or `method="json_mode"` based on what the chosen Ollama model supports

</decisions>

<specifics>
## Specific Ideas

- No specific product references mentioned — open to standard approaches for LLM call structure
- The cold start and LLM failure fallback should behave identically: same code path, same email format note

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/analyst.py`: Current deterministic threshold checker. Phase 3 replaces the core logic here, keeping the same `run_analyst(state) -> AgentState` function signature.
- `guardrails/safety_logic.py`: `run_policy_guard()` already has 3 ordered checks with short-circuit logic. Add confidence as check 4 using the same pattern.
- `agents/communicator.py`: `build_body()` constructs the plain-text email. Extend it to accept optional `llm_reasoning: str | None` and append the Analysis section.
- `adapters/persistence.py`: `append_poll_result()` already handles JSONL writes — reuse for llm_failure events and confidence-suppressed events.

### Established Patterns
- AgentState flows as a TypedDict through all nodes — add new fields: `llm_confidence: Optional[float]`, `llm_reasoning: Optional[str]`
- decision_log uses list concatenation (`state["decision_log"] + [entry]`) — maintain this pattern
- All checks in policy guard return `(bool, Optional[str])` tuples — follow the same pattern for the confidence check
- Environment variables read with `os.getenv("VAR", "default")` — new vars: `LLM_CONFIDENCE_THRESHOLD` (default: 0.7)
- Mock mode pattern (`USE_MOCK_SNMP`, `USE_MOCK_SMTP`) — consider `USE_MOCK_LLM` for test isolation

### Integration Points
- `state_types.py`: Add `llm_confidence` and `llm_reasoning` fields to `AgentState` TypedDict
- `supervisor.py`: `run_pipeline()` passes state through unchanged — no changes needed (pipeline is sequential)
- `logs/printer_history.json` (JSONL): New event types: `llm_failure`, confidence-suppressed events already handled by existing `log_suppression()`

</code_context>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-llm-analyst*
*Context gathered: 2026-03-01*
