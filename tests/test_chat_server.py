"""
tests/test_chat_server.py — Scaffold tests for chat_server.py Flask skeleton.

Tests cover:
    - GET / returns 200 with HTML content-type
    - POST /chat with missing message key returns 400 with error envelope
    - POST /chat with empty message returns 400 with error envelope
    - POST /chat with unknown intent returns 200 with unknown_intent envelope and help text
    - classify_intent() returns 'unknown' when Ollama is unreachable (no crash)
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
