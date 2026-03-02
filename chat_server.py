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
})

SYSTEM_PROMPT = """
You are an intent classifier for a printer monitoring system.
Classify the user's message into exactly one of these actions:
- toner_status: user wants current toner levels
- alert_history: user wants to see recent alerts
- suppression_explanation: user wants to know why an alert was suppressed
- trigger_pipeline: user wants to run a check now
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
        logger.warning("classify_intent: Ollama call failed -- returning 'unknown'", exc_info=True)
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
    """Stub: Returns not-implemented envelope. Plan 02 replaces this."""
    return _envelope("ok", "toner_status", {"note": "not implemented"})


def _handle_alert_history() -> dict:
    """Stub: Returns not-implemented envelope. Plan 02 replaces this."""
    return _envelope("ok", "alert_history", {"note": "not implemented"})


def _handle_suppression_explanation() -> dict:
    """Stub: Returns not-implemented envelope. Plan 03 replaces this."""
    return _envelope("ok", "suppression_explanation", {"note": "not implemented"})


def _handle_trigger_pipeline() -> dict:
    """Stub: Returns not-implemented envelope. Plan 03 replaces this."""
    return _envelope("ok", "trigger_pipeline", {"note": "not implemented"})


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
