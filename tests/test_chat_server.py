"""
tests/test_chat_server.py — Scaffold tests for chat_server.py Flask skeleton.

Tests cover:
    - GET / returns 200 with HTML content-type
    - POST /chat with missing message key returns 400 with error envelope
    - POST /chat with empty message returns 400 with error envelope
    - POST /chat with unknown intent returns 200 with unknown_intent envelope and help text
    - classify_intent() returns 'unknown' when Ollama is unreachable (no crash)
    - _handle_toner_status() returns per-color CMYK dict with pct and status (UI-02)
    - _handle_alert_history() returns filtered 7-day entries from log (UI-03)
    - _handle_suppression_explanation() returns plain-English suppression reason (UI-04)
"""
import pytest
from unittest.mock import patch, MagicMock
import chat_server  # module-level import (matches Phase 4 test_main.py pattern)


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("USE_MOCK_SNMP", "true")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mock-ollama:11434")
    return chat_server.create_app()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_get_index_returns_200_html(client):
    """GET / returns 200 with HTML content-type."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.content_type


def test_post_chat_missing_message_key_returns_400(client):
    """POST /chat with no message key returns 400 with status=error."""
    response = client.post("/chat", json={})
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"


def test_post_chat_empty_message_returns_400(client):
    """POST /chat with empty string message returns 400 with status=error."""
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"


def test_post_chat_unknown_intent_returns_200_with_help_text(client, monkeypatch):
    """POST /chat with unrecognized message (classify_intent returns 'unknown') returns 200
    with status=unknown_intent, action=unknown, and help text mentioning 'toner status'."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "unknown")
    response = client.post("/chat", json={"message": "xyz"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "unknown_intent"
    assert data["action"] == "unknown"
    assert "toner status" in data["data"]["message"].lower()


def test_classify_intent_ollama_unreachable_returns_unknown(monkeypatch):
    """classify_intent() returns 'unknown' when Ollama is unreachable (no exception raised)."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mock-ollama:11434")

    with patch("chat_server.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance
        mock_client_instance.chat.side_effect = ConnectionError("Connection refused")
        result = chat_server.classify_intent("test message")

    assert result == "unknown"


# ---------------------------------------------------------------------------
# Task 1: _handle_toner_status() tests (UI-02)
# ---------------------------------------------------------------------------

def _make_mock_poll_result():
    """Return a minimal PollResult dict with 4 CMYK readings at varying levels."""
    return {
        "printer_host": "127.0.0.1",
        "timestamp": "2026-03-02T10:00:00+00:00",
        "readings": [
            {"color": "cyan",    "toner_pct": 45.0, "quality_flag": "ok", "data_quality_ok": True},
            {"color": "magenta", "toner_pct": 12.0, "quality_flag": "ok", "data_quality_ok": True},
            {"color": "yellow",  "toner_pct": 78.0, "quality_flag": "ok", "data_quality_ok": True},
            {"color": "black",   "toner_pct":  5.0, "quality_flag": "ok", "data_quality_ok": True},
        ],
        "overall_quality_ok": True,
    }


def test_toner_status_returns_cmyk_dict(client, monkeypatch):
    """POST /chat toner_status returns 200 with per-color dict containing pct and status."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "toner_status")

    mock_adapter_instance = MagicMock()
    mock_adapter_instance.poll.return_value = _make_mock_poll_result()
    mock_adapter_cls = MagicMock(return_value=mock_adapter_instance)
    monkeypatch.setattr(chat_server, "SNMPAdapter", mock_adapter_cls)

    response = client.post("/chat", json={"message": "toner status"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "toner_status"

    colors = data["data"]
    for color in ("cyan", "magenta", "yellow", "black"):
        assert color in colors, f"Missing color key: {color}"
        assert "pct" in colors[color]
        assert "status" in colors[color]

    # Verify status labels match thresholds (defaults: critical=10, low=20)
    assert colors["cyan"]["pct"] == 45.0
    assert colors["cyan"]["status"] == "ok"
    assert colors["magenta"]["pct"] == 12.0
    assert colors["magenta"]["status"] == "low"
    assert colors["yellow"]["pct"] == 78.0
    assert colors["yellow"]["status"] == "ok"
    assert colors["black"]["pct"] == 5.0
    assert colors["black"]["status"] == "critical"


def test_toner_status_snmp_exception_returns_error_envelope(client, monkeypatch):
    """POST /chat toner_status when SNMPAdapter.poll() raises returns 200 with status=error."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "toner_status")

    mock_adapter_instance = MagicMock()
    mock_adapter_instance.poll.side_effect = RuntimeError("SNMP timeout")
    mock_adapter_cls = MagicMock(return_value=mock_adapter_instance)
    monkeypatch.setattr(chat_server, "SNMPAdapter", mock_adapter_cls)

    response = client.post("/chat", json={"message": "toner status"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "error"
    assert data["action"] == "toner_status"
    assert "message" in data["data"]
    # Should be user-readable, not a traceback
    assert "Failed to read toner levels" in data["data"]["message"]


# ---------------------------------------------------------------------------
# Task 2: _handle_alert_history() tests (UI-03)
# ---------------------------------------------------------------------------

def test_alert_history_returns_only_recent_entries(client, monkeypatch):
    """POST /chat alert_history returns only entries within the last 7 days."""
    from datetime import datetime, timezone, timedelta

    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "alert_history")

    now = datetime.now(timezone.utc)
    recent_entry = {"timestamp": now.isoformat(), "toner_pct": 15.0, "action": "alert_sent"}
    old_entry_1 = {"timestamp": (now - timedelta(days=10)).isoformat(), "toner_pct": 30.0, "action": "no_alert"}
    old_entry_2 = {"timestamp": (now - timedelta(days=14)).isoformat(), "toner_pct": 50.0, "action": "no_alert"}

    monkeypatch.setattr(chat_server, "read_poll_history", lambda: [old_entry_1, old_entry_2, recent_entry])

    response = client.post("/chat", json={"message": "show alert history"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "alert_history"
    entries = data["data"]["entries"]
    assert len(entries) == 1
    assert entries[0]["toner_pct"] == 15.0
    assert data["data"]["window_days"] == 7


def test_alert_history_empty_log_returns_empty_list(client, monkeypatch):
    """POST /chat alert_history with empty log file returns data.entries=[] without error."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "alert_history")
    monkeypatch.setattr(chat_server, "read_poll_history", lambda: [])

    response = client.post("/chat", json={"message": "alert history"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "alert_history"
    assert data["data"]["entries"] == []
    assert data["data"]["window_days"] == 7


# ---------------------------------------------------------------------------
# Task 2: _handle_suppression_explanation() tests (UI-04)
# ---------------------------------------------------------------------------

def test_suppression_explanation_rate_limit_returns_plain_english(client, monkeypatch):
    """POST /chat suppression_explanation returns plain-English rate limit message."""
    from datetime import datetime, timezone

    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "suppression_explanation")

    history = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "suppression_reason": "rate_limit: last_alert=2026-03-01T10:00:00+00:00",
        }
    ]
    monkeypatch.setattr(chat_server, "read_poll_history", lambda: history)

    response = client.post("/chat", json={"message": "why was alert suppressed"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "suppression_explanation"
    assert data["data"]["suppression_reason"] == "An alert was already sent in the last 24 hours."
    assert "raw_reason" in data["data"]
    assert "timestamp" in data["data"]


def test_suppression_explanation_no_suppression_in_history(client, monkeypatch):
    """POST /chat suppression_explanation returns 'No suppressed alerts found' message when none exist."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "suppression_explanation")

    # History entries without suppression_reason
    history = [
        {"timestamp": "2026-03-02T10:00:00+00:00", "toner_pct": 25.0},
        {"timestamp": "2026-03-01T10:00:00+00:00", "toner_pct": 30.0},
    ]
    monkeypatch.setattr(chat_server, "read_poll_history", lambda: history)

    response = client.post("/chat", json={"message": "why was alert suppressed"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "suppression_explanation"
    assert data["data"]["message"] == "No suppressed alerts found in history."


def test_suppression_explanation_low_confidence_returns_plain_english(client, monkeypatch):
    """POST /chat suppression_explanation returns plain-English low_confidence message."""
    from datetime import datetime, timezone

    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "suppression_explanation")

    history = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "suppression_reason": "confidence_check_failed: reason=low_confidence, score=0.45",
        }
    ]
    monkeypatch.setattr(chat_server, "read_poll_history", lambda: history)

    response = client.post("/chat", json={"message": "why was alert suppressed"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "suppression_explanation"
    assert data["data"]["suppression_reason"] == "The LLM's confidence score was too low to trigger an alert reliably."


# ---------------------------------------------------------------------------
# Task 1 (Plan 03): _handle_trigger_pipeline() tests (UI-05)
# ---------------------------------------------------------------------------

def _make_trigger_agent_state(
    alert_needed=True,
    alert_sent=False,
    suppression_reason="rate_limit: last_alert=2026-03-01T10:00:00+00:00",
    llm_reasoning="Magenta is critically low at 5%",
    llm_confidence=0.91,
    include_poll=True,
):
    """Return a minimal AgentState dict for trigger_pipeline handler tests."""
    poll = None
    if include_poll:
        poll = {
            "printer_host": "127.0.0.1",
            "timestamp": "2026-03-02T10:00:00+00:00",
            "readings": [
                {"color": "cyan",    "toner_pct": 45.0, "quality_flag": "ok", "data_quality_ok": True},
                {"color": "magenta", "toner_pct":  5.0, "quality_flag": "ok", "data_quality_ok": True},
                {"color": "yellow",  "toner_pct": 78.0, "quality_flag": "ok", "data_quality_ok": True},
                {"color": "black",   "toner_pct": 30.0, "quality_flag": "ok", "data_quality_ok": True},
            ],
            "overall_quality_ok": True,
        }
    return {
        "alert_needed": alert_needed,
        "alert_sent": alert_sent,
        "suppression_reason": suppression_reason,
        "poll_result": poll,
        "llm_reasoning": llm_reasoning,
        "llm_confidence": llm_confidence,
        "decision_log": [],
        "flagged_colors": None,
    }


def test_trigger_pipeline_success_returns_ok_envelope(client, monkeypatch):
    """POST /chat trigger_pipeline with successful run_pipeline call returns 200 with
    status='ok', action='trigger_pipeline', and data containing alert_needed, alert_sent,
    suppression_reason (plain English), toner dict, and llm_reasoning."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "trigger_pipeline")

    state = _make_trigger_agent_state()
    monkeypatch.setattr(chat_server, "run_pipeline", lambda: state)

    response = client.post("/chat", json={"message": "run a check now"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["action"] == "trigger_pipeline"

    d = data["data"]
    assert d["alert_needed"] is True
    assert d["alert_sent"] is False
    # suppression_reason should be plain English (rate_limit prefix -> 24 hours message)
    assert d["suppression_reason"] == "An alert was already sent in the last 24 hours."
    assert d["llm_reasoning"] == "Magenta is critically low at 5%"
    # toner dict should have CMYK colors
    assert d["toner"] is not None
    assert "cyan" in d["toner"]
    assert "magenta" in d["toner"]
    assert d["toner"]["magenta"]["pct"] == 5.0
    assert d["toner"]["magenta"]["status"] == "critical"


def test_trigger_pipeline_timeout_returns_error_envelope(client, monkeypatch):
    """POST /chat trigger_pipeline when run_pipeline raises TimeoutError returns 200
    with status='error' and data.message containing 'timed out'."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "trigger_pipeline")

    def raise_timeout():
        raise TimeoutError("future timed out")

    monkeypatch.setattr(chat_server, "run_pipeline", raise_timeout)

    response = client.post("/chat", json={"message": "run check now"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "error"
    assert data["action"] == "trigger_pipeline"
    assert "timed out" in data["data"]["message"].lower()


def test_trigger_pipeline_runtime_error_returns_error_envelope(client, monkeypatch):
    """POST /chat trigger_pipeline when run_pipeline raises RuntimeError returns 200
    with status='error' and data.message containing 'Pipeline error'."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "trigger_pipeline")

    def raise_runtime():
        raise RuntimeError("SNMP failed")

    monkeypatch.setattr(chat_server, "run_pipeline", raise_runtime)

    response = client.post("/chat", json={"message": "run check now"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "error"
    assert data["action"] == "trigger_pipeline"
    assert "Pipeline error" in data["data"]["message"]


def test_trigger_pipeline_alert_sent_true_in_response(client, monkeypatch):
    """POST /chat trigger_pipeline where alert_sent=True returns alert_sent=True in response data."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "trigger_pipeline")

    state = _make_trigger_agent_state(alert_needed=True, alert_sent=True, suppression_reason=None)
    monkeypatch.setattr(chat_server, "run_pipeline", lambda: state)

    response = client.post("/chat", json={"message": "run check now"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["data"]["alert_sent"] is True
    assert data["data"]["suppression_reason"] is None


def test_trigger_pipeline_no_poll_result_returns_toner_none(client, monkeypatch):
    """POST /chat trigger_pipeline where poll_result is None returns toner=None without crashing."""
    monkeypatch.setattr("chat_server.classify_intent", lambda msg: "trigger_pipeline")

    state = _make_trigger_agent_state(include_poll=False)
    monkeypatch.setattr(chat_server, "run_pipeline", lambda: state)

    response = client.post("/chat", json={"message": "run check now"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "ok"
    assert data["data"]["toner"] is None
