# Domain Pitfalls

**Domain:** SNMP Printer Monitoring + LangGraph Multi-Agent Pipeline + EWS Email Alerting
**Researched:** 2026-02-28

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

### Pitfall 1: Lexmark SNMP Toner Values Become Unreliable Below 20%

**What goes wrong:** The standard Printer MIB OID `prtMarkerSuppliesLevel` (`.1.3.6.1.2.1.43.11.1.1.9`) stops returning accurate integer percentages when toner drops below approximately 20%. Lexmark firmware returns special sentinel values (`-2` for "unknown", `-3` for "supply has reached low threshold") instead of actual numeric levels. Starting with certain EC6 firmware revisions, a "SNMP Compatibility Mode" setting controls whether the printer returns legacy `-3` values or continues reporting actual counts after the LOW threshold is reached.

**Why it happens:** The Printer MIB RFC allows manufacturer-defined special values. Lexmark (and many other vendors) chose to report a generic "low" signal rather than precise measurements once supplies reach a vendor-defined threshold. This is by design in their firmware, not a bug.

**Consequences:** Your entire value proposition -- predicting time-to-depletion before it happens -- breaks at exactly the point it matters most. The LLM analyst receives `-3` instead of `12%`, generates garbage predictions, and either spams alerts or stays silent during the critical depletion window.

**Prevention:**
1. Probe the actual Lexmark XC2235 with `snmpwalk` across the full `.1.3.6.1.2.1.43.11` subtree before writing any parsing code. Document every OID and its actual return values at various toner levels.
2. Check device settings for "SNMP Compatibility Mode" and set it to return actual counts if available on XC2235.
3. Build explicit handling for sentinel values: `-2` (unknown) and `-3` (low) must be treated as structured signals, not errors. Map `-3` to a "confirmed low, exact level unknown" state.
4. Consider also reading `prtMarkerSuppliesMaxCapacity` (`.1.3.6.1.2.1.43.11.1.1.8`) and Lexmark's private MIB OIDs (enterprise `.1.3.6.1.4.1.641.*`) which may provide additional granularity.
5. Implement a data quality flag in the SNMP adapter output: `{"level": -3, "data_quality": "sentinel_low", "raw_oid_value": -3}` so downstream agents can reason about data reliability.

**Detection:** During development, if you only test with a printer that has >20% toner, you will never see sentinel values. Test with a printer in LOW state or use snmpsim to simulate these responses.

**Phase:** Adapters (Phase 1). Must be resolved before any agent logic is built.
**Confidence:** MEDIUM -- Lexmark support docs confirm sentinel values exist; exact XC2235 behavior needs device-level validation.

---

### Pitfall 2: LLM Confidence Self-Scores Are Poorly Calibrated

**What goes wrong:** The project design requires the LLM Analyst to self-report a confidence score (0.0-1.0) alongside its analysis. Research shows LLM verbalized confidence scores are severely miscalibrated, with Expected Calibration Errors (ECE) ranging from 0.108 to 0.427 across models. LLMs tend to report high confidence even when wrong, and show minimal variation between correct and incorrect answers.

**Why it happens:** LLMs do not have intrinsic uncertainty estimation. When asked "how confident are you?", they generate a plausible-sounding number based on linguistic patterns, not statistical self-awareness. The confidence score is effectively another text generation, not a probability measurement.

**Consequences:** The Policy Guard's confidence threshold check (>= 0.7) becomes either useless (always passes because the LLM always says 0.85+) or a source of false suppression if the LLM arbitrarily outputs low numbers. Either way, the guardrail provides a false sense of safety.

**Prevention:**
1. Do NOT rely solely on LLM self-reported confidence. Implement a two-layer confidence system as the project spec already suggests:
   - **Data quality score** (computed, not LLM-generated): Is SNMP data fresh? Is the value in a valid range (0-100 or known sentinel)? Is there sufficient historical data for trend analysis? This should be a deterministic function in the SNMP adapter or a pre-analyst step.
   - **LLM reasoning quality** (heuristic-checked): Does the LLM's response contain a time-to-depletion estimate? Does the estimate change appropriately when input data changes? Does it acknowledge data limitations?
2. Use structured output (JSON schema enforcement via LangChain's `with_structured_output`) so the LLM cannot just say "I'm 90% confident." Force it to output specific fields: `estimated_days_remaining`, `trend_direction`, `data_points_used`, `limitations`.
3. Consider calibrating against historical accuracy: log predictions vs. actual depletion events, and adjust thresholds over time.

**Detection:** If every LLM response has confidence >= 0.8 regardless of data quality, the score is not calibrated. Test with deliberately bad data (stale timestamps, sentinel values, insufficient history) -- confidence should drop.

**Phase:** Agents (Analyst) and Guardrails. Design the confidence schema before implementing either.
**Confidence:** HIGH -- supported by multiple peer-reviewed papers (ACL 2025, ICLR 2024) and practical benchmarks.

---

### Pitfall 3: Using the Wrong PySNMP Package

**What goes wrong:** The original `pysnmp` by Ilya Etingof (etingof/pysnmp on GitHub) has been unmaintained since 2019-2020. Developers install it, hit Python 3.10+ compatibility issues, broken async support, or missing security fixes, and waste days debugging.

**Why it happens:** The original `pysnmp` still appears in many tutorials, Stack Overflow answers, and even some documentation. The actively maintained fork by LeXtudio Inc. now controls the PyPI `pysnmp` package name (as of their takeover), but version confusion persists.

**Consequences:** Build on a dead library, encounter cryptic errors with modern Python, waste time, then have to migrate anyway.

**Prevention:**
1. Use `pysnmp` from PyPI which is now the LeXtudio fork (version 7.x as of 2025). Verify with `pip show pysnmp` that the maintainer is LeXtudio.
2. Pin to `pysnmp>=7.0` in `requirements.txt` to ensure you get the maintained fork.
3. Reference docs at `https://docs.lextudio.com/snmp/` (NOT `pysnmp.readthedocs.io` which is the old unmaintained docs).

**Detection:** If `pip install pysnmp` gives you version 4.x, you have the wrong package.

**Phase:** Adapters (Phase 1). First dependency to install and verify.
**Confidence:** HIGH -- confirmed via PyPI, GitHub, and multiple downstream project migrations (Glances, Home Assistant, OpenStack).

---

### Pitfall 4: exchangelib Basic Auth Blocked by Office 365

**What goes wrong:** Microsoft has deprecated and is actively blocking Basic Authentication for Exchange Online (Office 365). If the target Exchange server is O365, `exchangelib` with username/password credentials will fail with authentication errors. Even on-premises Exchange may have Basic Auth disabled by policy.

**Why it happens:** Microsoft's security posture change, rolling out since 2022 and now fully enforced for most tenants. The project spec says "service account credentials sufficient" and "no OAuth" -- but this only works if the Exchange server is on-premises with Basic Auth or NTLM enabled.

**Consequences:** The entire email alerting pipeline is dead on arrival if the Exchange environment requires OAuth/Modern Auth. This is a potential project-blocking issue.

**Prevention:**
1. Before writing any EWS code, confirm with IT: Is the Exchange server on-premises or O365? Is Basic Auth / NTLM enabled for service accounts?
2. If O365: You must use OAuth. `exchangelib` supports OAuth but requires Azure AD app registration with `EWS.AccessAsUser.All` delegate permissions. This changes the auth setup significantly.
3. If on-premises: Confirm the auth type explicitly. Use `exchangelib`'s `Configuration` object with explicit `auth_type` (e.g., `NTLM`) rather than relying on autodiscover, which is fragile.
4. Always bypass autodiscover by constructing a `Configuration(server=..., credentials=..., auth_type=...)` directly. Autodiscover is unreliable and adds failure modes.

**Detection:** `exchangelib.errors.TransportError: Failed to get auth type from service` is the classic symptom. Test EWS connectivity in isolation before wiring into the agent pipeline.

**Phase:** Adapters (Phase 1). Must validate Exchange connectivity before building Communicator.
**Confidence:** HIGH -- confirmed by exchangelib GitHub issues, Microsoft documentation, and community reports.

---

### Pitfall 5: LangGraph State Overwrites Instead of Accumulating

**What goes wrong:** Without explicit reducer functions on TypedDict fields, LangGraph's default behavior is to overwrite state values when a node returns an update. Developers expect list fields (like message history or toner reading history) to accumulate, but they get replaced with only the latest value.

**Why it happens:** LangGraph requires explicit `Annotated[list, add]` syntax to enable list accumulation. The default (no annotation) is last-write-wins. This is documented but counterintuitive for developers coming from other frameworks.

**Consequences:** Historical toner trend data is lost on every polling cycle. The analyst agent receives only the latest reading instead of a time series, making trend analysis and time-to-depletion prediction impossible.

**Prevention:**
1. Define the graph state schema upfront with explicit reducers for every field:
   ```python
   from typing import Annotated, TypedDict
   from operator import add

   class SentinelState(TypedDict):
       current_reading: dict                        # Overwrites (latest only)
       reading_history: Annotated[list, add]         # Accumulates
       alerts_sent: Annotated[list, add]             # Accumulates
       analysis_result: dict                         # Overwrites (latest only)
   ```
2. Never mutate state objects directly within nodes. Always return new values via the node's return dict. Direct mutation bypasses LangGraph's tracking and breaks checkpointing.
3. Add a `max_steps` or iteration counter to prevent unbounded accumulation in long-running graphs.

**Detection:** If your analyst agent's trend analysis says "insufficient data" on every run despite the system running for days, check whether reading_history is being overwritten instead of accumulated.

**Phase:** Agents/Supervisor (Phase 3). Must be designed correctly before any agent node is implemented.
**Confidence:** HIGH -- confirmed by LangGraph official documentation and multiple practitioner guides.

## Moderate Pitfalls

### Pitfall 6: APScheduler Missed Jobs in Production

**What goes wrong:** APScheduler (the likely scheduler for hourly polling in `main.py`) silently misses scheduled jobs when the system is under load, when using multi-process deployments, or when the GIL is disabled (e.g., under uWSGI). Jobs may also execute multiple times if multiple scheduler instances share a job store without interprocess synchronization.

**Prevention:**
1. Run the scheduler in a single dedicated process. Do not embed it in a multi-worker web server.
2. For this project (a standalone script, not a web app), use `BlockingScheduler` with `misfire_grace_time` set appropriately (e.g., 300 seconds) so jobs that fire slightly late still execute.
3. Log every scheduler tick with timestamp. If gaps appear in the log, the scheduler is misfiring.
4. Consider a simpler alternative: a `while True` loop with `time.sleep(3600)` may be more reliable for a single-purpose polling script than the full APScheduler machinery. Or use the OS-level scheduler (cron/Task Scheduler) to invoke `main.py` on each cycle.

**Phase:** Main/Orchestration (Phase 4, final wiring).
**Confidence:** MEDIUM -- APScheduler issues are well-documented but may not apply if using a simple single-process architecture.

---

### Pitfall 7: SNMP Timeouts and Network Unreliability Not Handled

**What goes wrong:** SNMP queries to the printer time out silently if the device is powered off, in sleep mode, or the network path is down. Without explicit timeout handling and retry logic, the entire pipeline hangs or crashes.

**Prevention:**
1. Set explicit SNMP timeouts (e.g., 5 seconds) and retry counts (e.g., 2 retries) in the pysnmp transport configuration.
2. The SNMP adapter must return a structured error response (not raise an exception that kills the pipeline): `{"status": "timeout", "timestamp": ..., "device": ...}`.
3. The supervisor/monitor agent must handle "no data" gracefully -- skip the analyst step, log the event, and wait for the next cycle.
4. Consider the printer's sleep/power-save mode: many networked printers disable their SNMP agent during deep sleep. This is normal, not an error.

**Phase:** Adapters (Phase 1).
**Confidence:** HIGH -- fundamental to any SNMP monitoring system.

---

### Pitfall 8: Rate Limiting State Lost on Restart

**What goes wrong:** The Policy Guard's "1 alert per day per printer" rate limit is stored only in memory. When the process restarts (crash, deployment, reboot), the rate limit state is lost, and the system may immediately re-send an alert that was already sent today.

**Prevention:**
1. Persist rate limit state to disk alongside `printer_history.json`. On startup, read the last alert timestamp for each printer and resume rate limiting from there.
2. Use a simple JSON structure: `{"printer_id": {"last_alert_sent": "2026-02-28T10:00:00Z"}}`.
3. Make the rate limiter check idempotent: "was an alert sent for this printer in the last 24 hours?" not "have I sent an alert since I started?"

**Phase:** Guardrails (Phase 2).
**Confidence:** HIGH -- standard stateful rate limiting concern.

---

### Pitfall 9: LLM API Costs and Latency in a Polling Loop

**What goes wrong:** Calling an LLM on every hourly poll cycle, even when toner levels haven't changed, wastes API credits and adds unnecessary latency. Over a month with 1 printer polling hourly, that is 720 LLM calls -- most producing identical "everything is fine" responses.

**Prevention:**
1. Add a "change detection" gate before the analyst agent: only invoke the LLM when the toner reading has changed meaningfully (e.g., dropped by >= 1% since last analysis) or when a sentinel value is newly encountered.
2. Cache the last analysis result. If input data hasn't changed, return the cached result without an LLM call.
3. Log LLM invocations with cost estimates to monitor burn rate.

**Phase:** Supervisor/Agents (Phase 3). Design the conditional edge in the LangGraph graph.
**Confidence:** HIGH -- straightforward optimization but easy to forget in initial implementation.

---

### Pitfall 10: JSON Log File Corruption and Unbounded Growth

**What goes wrong:** `printer_history.json` is written to on every polling cycle. Concurrent writes (if the scheduler fires overlapping jobs), crashes mid-write, or simply growing the file indefinitely all cause problems. A corrupted JSON file prevents the system from reading historical data on restart.

**Prevention:**
1. Use atomic writes: write to a temp file, then rename (atomic on most filesystems).
2. Use JSON Lines format (`.jsonl`) instead of a single JSON array -- each line is an independent JSON object, so partial writes only corrupt the last line, not the entire history.
3. Implement log rotation: keep the last N entries or last N days. A year of hourly polling with 4 toner readings each produces ~35,000 entries.
4. On startup, validate the log file. If corrupted, rename the bad file and start fresh with a warning.

**Phase:** Logging infrastructure (Phase 1-2, before agents write to it).
**Confidence:** HIGH -- standard file-based logging concern.

## Minor Pitfalls

### Pitfall 11: SNMP Community String Exposure in Logs

**What goes wrong:** Debug logging of SNMP queries may include the community string in plain text. The community string is effectively a password for SNMP v1/v2c.

**Prevention:** Never log SNMP transport parameters. Log the OID being queried and the result, not the connection credentials. Keep the community string in `.env` only.

**Phase:** Adapters (Phase 1).
**Confidence:** HIGH.

---

### Pitfall 12: exchangelib Autodiscover DNS Failures

**What goes wrong:** `exchangelib`'s autodiscover mechanism makes multiple DNS lookups and HTTP requests to discover the EWS endpoint. On networks with strict DNS or firewall rules, autodiscover fails with opaque errors.

**Prevention:** Skip autodiscover entirely. Use `Configuration(server='your-exchange-server.com', ...)` with the explicit EWS endpoint. This is faster, more reliable, and removes a failure mode.

**Phase:** Adapters (Phase 1).
**Confidence:** HIGH -- well-documented in exchangelib GitHub discussions.

---

### Pitfall 13: Timezone Handling in Rate Limiting and Alerts

**What goes wrong:** The "1 alert per 24 hours" window behaves differently depending on whether timestamps are stored in UTC, local time, or are timezone-naive. Daylight saving transitions can cause a 23-hour or 25-hour day, leading to duplicate or missed alerts.

**Prevention:** Store all timestamps as UTC (timezone-aware). Use `datetime.now(timezone.utc)` not `datetime.now()`. Compare alert windows using UTC exclusively.

**Phase:** Guardrails (Phase 2).
**Confidence:** HIGH.

---

### Pitfall 14: LangGraph Graph Compilation Errors Are Opaque

**What goes wrong:** Mistakes in graph wiring (missing edges, disconnected nodes, invalid conditional edge functions) produce error messages that are difficult to interpret, especially for developers new to LangGraph.

**Prevention:** Build the graph incrementally. Start with a two-node graph (monitor -> analyst) and verify it compiles and runs. Add nodes one at a time. Use `graph.get_graph().draw_mermaid()` to visualize the graph structure at each step.

**Phase:** Supervisor (Phase 3).
**Confidence:** MEDIUM -- based on community reports, may improve with newer LangGraph versions.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| SNMP Adapter | Sentinel values (-2, -3) at low toner break parsing | Probe real device first; handle sentinels as structured data |
| SNMP Adapter | Wrong pysnmp package (etingof vs LeXtudio) | Pin `pysnmp>=7.0`, verify with `pip show` |
| SNMP Adapter | Timeout/sleep mode not handled | Explicit timeouts, structured error returns |
| EWS Adapter | Basic Auth blocked on O365 | Confirm auth type with IT before coding |
| EWS Adapter | Autodiscover fails on restricted networks | Use explicit Configuration, skip autodiscover |
| Guardrails | Rate limit state lost on restart | Persist to disk alongside history log |
| Guardrails | Timezone bugs in 24-hour window | UTC everywhere, timezone-aware datetimes |
| Analyst Agent | LLM confidence scores unreliable | Two-layer confidence: deterministic data quality + LLM reasoning |
| Analyst Agent | Unnecessary LLM calls on unchanged data | Change detection gate before analyst node |
| Supervisor | State overwrites instead of accumulates | Explicit `Annotated[list, add]` reducers on list fields |
| Supervisor | Graph cycles without termination | Max-steps counter, explicit exit conditions |
| Main/Scheduler | APScheduler misses jobs | Single process, or use OS-level cron instead |
| Logging | JSON file corruption/unbounded growth | JSON Lines format, atomic writes, rotation |

## Sources

- [Lexmark SNMP MIBs and OID Values Explained](https://support.lexmark.com/en_us/printers/printer/E462/article/FA615.html) -- Lexmark official (MEDIUM confidence, not XC2235-specific)
- [Lexmark SNMP Toner Reporting Issue](http://support.lexmark.com/index?pmv=print&page=content&locale=en&modifiedDate=03/20/16&actp=LIST_RECENT&userlocale=EN_US&id=SO7870) -- Lexmark support (MEDIUM confidence)
- [Brother Printer SNMP Toner Monitoring](https://www.claudiokuenzler.com/blog/1422/monitoring-brother-printer-snmp-alert-low-toner) -- Cross-vendor OID reliability issues (MEDIUM confidence)
- [On Verbalized Confidence Scores for LLMs (arXiv 2412.14737)](https://arxiv.org/pdf/2412.14737) -- Academic research on LLM calibration (HIGH confidence)
- [5 Methods for Calibrating LLM Confidence Scores](https://latitude.so/blog/5-methods-for-calibrating-llm-confidence-scores) -- Practical calibration guide (MEDIUM confidence)
- [Benchmarking LLM Confidence in Clinical Questions](https://medinform.jmir.org/2025/1/e66917) -- ECE measurements across models (HIGH confidence)
- [PySNMP 7 by LeXtudio](https://docs.lextudio.com/snmp/) -- Maintained fork documentation (HIGH confidence)
- [Call for help to revive PySNMP ecosystem (GitHub #429)](https://github.com/etingof/pysnmp/issues/429) -- Fork history (HIGH confidence)
- [Glances migration to LeXtudio fork (GitHub #2741)](https://github.com/nicolargo/glances/issues/2741) -- Downstream confirmation (HIGH confidence)
- [exchangelib GitHub - Auth Type Error Discussion #1021](https://github.com/ecederstrand/exchangelib/discussions/1021) -- EWS auth issues (HIGH confidence)
- [exchangelib GitHub - Credential Issue Discussion #1050](https://github.com/ecederstrand/exchangelib/discussions/1050) -- OAuth requirements (HIGH confidence)
- [LangGraph Best Practices](https://www.swarnendu.de/blog/langgraph-best-practices/) -- State management and cycles (MEDIUM confidence)
- [Mastering State Reducers in LangGraph](https://medium.com/data-science-collective/mastering-state-reducers-in-langgraph-a-complete-guide-b049af272817) -- Reducer patterns (MEDIUM confidence)
- [Mastering LangGraph State Management in 2025](https://sparkco.ai/blog/mastering-langgraph-state-management-in-2025) -- Current best practices (MEDIUM confidence)
- [APScheduler FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html) -- Missed jobs documentation (HIGH confidence)
- [Common APScheduler Mistakes](https://sepgh.medium.com/common-mistakes-with-using-apscheduler-in-your-python-and-django-applications-100b289b812c) -- Production pitfalls (MEDIUM confidence)
- [APScheduler Missed Jobs Issue #481](https://github.com/agronholm/apscheduler/issues/481) -- Confirmed bug reports (HIGH confidence)
