"""
chat_server.py -- Standalone Flask entry point for Sentinel web chat interface.

Routes:
    GET  /      -- Serves templates/chat.html
    POST /chat  -- JSON API: classifies intent via Ollama, routes to handler, returns envelope

Environment variables:
    CHAT_PORT         -- Port to listen on (default: 5000)
    OLLAMA_BASE_URL   -- Ollama host URL (default: http://localhost:11434)
    OLLAMA_MODEL      -- Ollama model name (default: llama3.1)
    USE_MOCK_SNMP     -- Set to 'true' to bypass real SNMP hardware (dev/test)
    TONER_ALERT_THRESHOLD    -- Warning threshold % (default: 20)
    TONER_CRITICAL_THRESHOLD -- Critical threshold % (default: 10)

Run:
    python chat_server.py
"""

# stdlib
import json
import logging
import os
import concurrent.futures
from datetime import datetime, timezone, timedelta

# third-party
from flask import Flask, request, jsonify, render_template
from ollama import Client
from dotenv import load_dotenv

# project -- module-level so tests can patch chat_server.SNMPAdapter etc.
from adapters.snmp_adapter import SNMPAdapter
from adapters.persistence import read_poll_history
from agents.supervisor import run_pipeline

# ---------------------------------------------------------------------------
# Module-level constants (pure values, no side effects)
# ---------------------------------------------------------------------------

VALID_ACTIONS: frozenset = frozenset({
    "toner_status",
    "alert_history",
    "suppression_explanation",
    "trigger_pipeline",
    "anomaly_check",
})

SYSTEM_PROMPT = """
You are an intent classifier for a printer monitoring system.
Classify the user's message into exactly one of these actions:
- toner_status: user wants current toner levels
- alert_history: user wants to see recent alerts
- suppression_explanation: user wants to know why an alert was suppressed
- trigger_pipeline: user wants to run a check now
- anomaly_check: user asks about anomalies, issues, problems, warnings, or anything needing attention on the printer
- unknown: message doesn't match any supported action

Respond with ONLY a JSON object: {"action": "<action_name>"}
No explanation, no additional text.
""".strip()

# Suppression reason prefix/substring map (used by _plain_english)
SUPPRESSION_MESSAGES = {
    "rate_limit:": "An alert was already sent in the last 24 hours.",
    "data_quality:": "SNMP data quality check failed (stale, null, or invalid readings).",
    "reason=erratic_readings": "Toner readings were inconsistent -- alert withheld to avoid a false alarm.",
    "reason=low_confidence": "The LLM's confidence score was too low to trigger an alert reliably.",
}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helper functions (module-level, no side effects)
# ---------------------------------------------------------------------------

def _envelope(status: str, action: str, data: dict) -> dict:
    """Return the standard JSON response envelope with UTC ISO timestamp."""
    return {
        "status": status,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def _plain_english(reason: str | None) -> str | None:
    """Map a suppression_reason string to a plain-English explanation.

    Uses substring/prefix matching because suppression_reason strings are dynamic
    (e.g. "rate_limit: last_alert=2026-03-01T...").  Falls back to the raw reason
    string for any future reasons not in the mapping.
    """
    if reason is None:
        return None
    if reason.startswith("rate_limit:"):
        return SUPPRESSION_MESSAGES["rate_limit:"]
    if reason.startswith("data_quality:"):
        return SUPPRESSION_MESSAGES["data_quality:"]
    if "reason=erratic_readings" in reason:
        return SUPPRESSION_MESSAGES["reason=erratic_readings"]
    if "reason=low_confidence" in reason:
        return SUPPRESSION_MESSAGES["reason=low_confidence"]
    # Fallback: return the raw reason so we never crash on unknown future values.
    return reason


def classify_intent(message: str) -> str:
    """Classify user message into one of the four supported actions via Ollama.

    Returns one of: toner_status, alert_history, suppression_explanation,
    trigger_pipeline, unknown.

    Always returns 'unknown' on any exception (Ollama unreachable, parse error,
    invalid action value) -- never raises.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    try:
        client = Client(host=base_url)
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            format="json",
            options={"temperature": 0},
        )
        parsed = json.loads(response.message.content)
        action = parsed.get("action", "unknown")
        return action if action in VALID_ACTIONS else "unknown"
    except Exception:
        # Ollama unreachable, malformed JSON, or unexpected response shape.
        # Fall back to keyword matching so the UI remains functional.
        logger.warning("classify_intent: Ollama call failed -- falling back to keyword match", exc_info=True)
        return _keyword_classify(message)


def _keyword_classify(message: str) -> str:
    """Keyword fallback when Ollama is unreachable."""
    m = message.lower()
    if any(w in m for w in ("toner", "level", "ink", "cmyk", "cyan", "magenta", "yellow", "black")):
        return "toner_status"
    if any(w in m for w in ("alert", "history", "fired", "week", "sent", "notification")):
        return "alert_history"
    if any(w in m for w in ("suppressed", "suppression", "why", "blocked", "not sent", "skipped")):
        return "suppression_explanation"
    if any(w in m for w in ("run", "check", "trigger", "now", "manual", "force", "execute")):
        return "trigger_pipeline"
    if any(w in m for w in ("anomaly", "issue", "problem", "warning", "attention", "concern", "anything wrong", "printer ok", "printer fine")):
        return "anomaly_check"
    return "unknown"


def _toner_dict_from_poll(poll: dict) -> dict:
    """Convert a PollResult's readings list to {color: {pct, status}} dict.

    Status label logic:
        - pct is None  -> use quality_flag value as status string
        - pct <= TONER_CRITICAL_THRESHOLD -> "critical"
        - pct <= TONER_ALERT_THRESHOLD    -> "low"
        - else                            -> "ok"

    Thresholds are read from env vars inside this function (not at module level)
    so tests can monkeypatch them freely.
    """
    alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
    critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))
    result = {}
    for reading in poll.get("readings", []):
        pct = reading.get("toner_pct")
        if pct is None:
            status = reading.get("quality_flag", "unknown")
        elif pct <= critical_threshold:
            status = "critical"
        elif pct <= alert_threshold:
            status = "low"
        else:
            status = "ok"
        result[reading["color"]] = {"pct": pct, "status": status}
    return result


# ---------------------------------------------------------------------------
# Stub action handlers (Plans 02 and 03 implement these)
# ---------------------------------------------------------------------------

def _handle_toner_status() -> dict:
    """Live SNMP read — returns per-color CMYK toner levels with status labels.

    USE_MOCK_SNMP is respected internally by SNMPAdapter.poll(), so no special
    handling is needed here.  Returns an error envelope (status="error") rather
    than raising on any SNMP failure so the chat UI always gets a JSON response.
    """
    host = os.getenv("SNMP_HOST", "127.0.0.1")
    community = os.getenv("SNMP_COMMUNITY", "public")
    try:
        adapter = SNMPAdapter(host, community)
        poll = adapter.poll()
        return _envelope("ok", "toner_status", _toner_dict_from_poll(poll))
    except Exception as exc:
        logger.exception("toner_status handler error")
        return _envelope("error", "toner_status", {"message": f"Failed to read toner levels: {exc}"})


def _handle_alert_history() -> dict:
    """Return log entries from the last 7 days.

    Reads the full JSONL history via read_poll_history() and filters to entries
    whose timestamp falls within the last 7 days.  Returns an empty list when the
    log file does not exist or no entries match.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    history = read_poll_history()
    recent = []
    for entry in history:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts >= cutoff:
                recent.append(entry)
        except (ValueError, TypeError):
            pass  # skip malformed timestamp entries
    return _envelope("ok", "alert_history", {"entries": recent, "window_days": 7})


def _handle_suppression_explanation() -> dict:
    """Return a plain-English explanation of the most recent suppressed alert.

    Searches the log history newest-first for any entry with a suppression_reason
    field.  Translates the raw reason string to human-readable text via
    _plain_english().  Returns a 'not found' message when no suppression exists.
    """
    history = read_poll_history()
    # Search newest-first for the most recent suppressed entry
    for entry in reversed(history):
        reason = entry.get("suppression_reason")
        if reason:
            plain = _plain_english(reason)
            return _envelope("ok", "suppression_explanation", {
                "suppression_reason": plain,
                "raw_reason": reason,
                "timestamp": entry.get("timestamp"),
                "llm_confidence": entry.get("confidence"),
            })
    return _envelope("ok", "suppression_explanation", {
        "message": "No suppressed alerts found in history."
    })


def _handle_anomaly_check() -> dict:
    """Poll live toner levels and ask the LLM to identify anything needing attention.

    Fetches current SNMP readings, formats them into a prompt, and calls the
    Ollama LLM for a plain-English anomaly assessment.  Falls back to a
    deterministic summary if the LLM call fails.
    """
    host = os.getenv("SNMP_HOST", "127.0.0.1")
    community = os.getenv("SNMP_COMMUNITY", "public")
    alert_threshold = float(os.getenv("TONER_ALERT_THRESHOLD", "20"))
    critical_threshold = float(os.getenv("TONER_CRITICAL_THRESHOLD", "10"))

    try:
        adapter = SNMPAdapter(host, community)
        poll = adapter.poll()
    except Exception as exc:
        logger.exception("anomaly_check: SNMP poll failed")
        return _envelope("error", "anomaly_check", {"message": f"Failed to read toner levels: {exc}"})

    readings = poll.get("readings", [])
    toner = _toner_dict_from_poll(poll)

    # Build a concise toner summary for the LLM
    lines = []
    for color, info in toner.items():
        pct = info["pct"]
        status = info["status"]
        lines.append(f"  - {color}: {pct}% ({status})")
    toner_summary = "\n".join(lines) if lines else "  No readings available."

    prompt = (
        f"Current printer toner levels:\n{toner_summary}\n\n"
        f"Warning threshold: {alert_threshold}%\n"
        f"Critical threshold: {critical_threshold}%\n\n"
        "Analyse these readings. Identify any colors that need attention, "
        "explain the severity, and recommend what action should be taken. "
        "If everything looks fine, say so clearly. "
        "Reply in 2-4 plain-English sentences."
    )

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    try:
        client = Client(host=base_url)
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
        analysis = response.message.content.strip()
    except Exception:
        logger.warning("anomaly_check: LLM call failed — using deterministic summary", exc_info=True)
        flagged = [c for c, info in toner.items() if info["status"] in ("low", "critical")]
        if flagged:
            analysis = f"The following colors need attention: {', '.join(flagged)}."
        else:
            analysis = "All toner levels are within normal range."

    return _envelope("ok", "anomaly_check", {
        "analysis": analysis,
        "toner": toner,
    })


def _handle_trigger_pipeline() -> dict:
    """Run the full LangGraph pipeline in a thread with a 30-second timeout.

    Uses ThreadPoolExecutor (Windows-compatible — signal.alarm() is not available
    on Windows).  On timeout, returns an error envelope; the background thread
    continues running and its result will be persisted normally.

    Returns a structured envelope containing:
        alert_needed, alert_sent, suppression_reason (plain English),
        toner (per-color dict or None), llm_reasoning.
    """
    timeout = int(os.getenv("PIPELINE_TIMEOUT_SECONDS", "120"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_pipeline)
        try:
            state = future.result(timeout=timeout)
        except TimeoutError:
            return _envelope("error", "trigger_pipeline", {
                "message": f"Pipeline timed out after {timeout} seconds"
            })
        except Exception as exc:
            logger.exception("trigger_pipeline handler error")
            return _envelope("error", "trigger_pipeline", {
                "message": f"Pipeline error: {exc}"
            })

    poll = state.get("poll_result")
    toner = _toner_dict_from_poll(poll) if poll else None

    return _envelope("ok", "trigger_pipeline", {
        "alert_needed": state.get("alert_needed"),
        "alert_sent": state.get("alert_sent"),
        "suppression_reason": _plain_english(state.get("suppression_reason")),
        "toner": toner,
        "llm_confidence": state.get("llm_confidence"),
        "llm_reasoning": state.get("llm_reasoning"),
    })


# ---------------------------------------------------------------------------
# Flask application factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """Create and configure the Flask application.

    load_dotenv() is called as the FIRST line here (not at module level) to
    match the Phase 4 pattern: tests monkeypatch env vars before calling
    create_app(), so dotenv must not overwrite them at import time.
    """
    load_dotenv()

    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("chat.html")

    @app.post("/chat")
    def chat():
        body = request.get_json(force=True, silent=True) or {}
        message = str(body.get("message", "")).strip()

        if not message:
            return jsonify(_envelope("error", "unknown", {"message": "Empty message"})), 400

        action = classify_intent(message)

        if action == "toner_status":
            result = _handle_toner_status()
        elif action == "alert_history":
            result = _handle_alert_history()
        elif action == "suppression_explanation":
            result = _handle_suppression_explanation()
        elif action == "trigger_pipeline":
            result = _handle_trigger_pipeline()
        elif action == "anomaly_check":
            result = _handle_anomaly_check()
        else:
            # Unknown intent -- return help text
            return (
                jsonify(
                    _envelope(
                        "unknown_intent",
                        "unknown",
                        {
                            "message": (
                                "I didn't understand that. Try: 'toner status', "
                                "'alert history', 'why was alert suppressed', "
                                "'run check now'"
                            )
                        },
                    )
                ),
                200,
            )

        return jsonify(result), 200

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("CHAT_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
