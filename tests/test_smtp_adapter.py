"""
Tests for adapters/smtp_adapter.py — SMTPAdapter class.

All tests run in mock mode or validate configuration behaviour;
none require a live SMTP server.
"""

import logging
import importlib
import sys
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_adapter_module():
    """Force-reload smtp_adapter so that env vars are re-evaluated per test."""
    mod_name = "adapters.smtp_adapter"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import adapters.smtp_adapter as m
    return m


# ---------------------------------------------------------------------------
# Test 1: send_alert() in mock mode returns without error
# ---------------------------------------------------------------------------

def test_send_alert_mock_returns_without_error():
    """SMTPAdapter(use_mock=True).send_alert() completes without raising."""
    from adapters.smtp_adapter import SMTPAdapter

    adapter = SMTPAdapter(use_mock=True)
    adapter.send_alert(
        recipient="user@example.com",
        subject="Test Subject",
        body="Test body content.",
    )


# ---------------------------------------------------------------------------
# Test 2: Mock mode does NOT attempt an SMTP connection
# ---------------------------------------------------------------------------

def test_mock_mode_does_not_connect(monkeypatch):
    """In mock mode, send_alert() must not open an SMTP connection."""
    import adapters.smtp_adapter as module

    def _smtp_should_not_be_called(*args, **kwargs):
        raise AssertionError("smtplib.SMTP was called in mock mode!")

    monkeypatch.setattr(module.smtplib, "SMTP", _smtp_should_not_be_called)

    from adapters.smtp_adapter import SMTPAdapter

    adapter = SMTPAdapter(use_mock=True)
    adapter.send_alert("a@b.com", "S", "B")


# ---------------------------------------------------------------------------
# Test 3: Mock mode logs recipient, subject, and first 100 chars of body
# ---------------------------------------------------------------------------

def test_mock_mode_logs_email_content(caplog):
    """send_alert() in mock mode logs recipient, subject, and body preview."""
    from adapters.smtp_adapter import SMTPAdapter

    long_body = "X" * 200  # longer than 100 chars
    adapter = SMTPAdapter(use_mock=True)

    with caplog.at_level(logging.INFO, logger="adapters.smtp_adapter"):
        adapter.send_alert(
            recipient="admin@corp.com",
            subject="Toner Alert",
            body=long_body,
        )

    combined = " ".join(caplog.messages)
    assert "admin@corp.com" in combined, "Recipient not found in log"
    assert "Toner Alert" in combined, "Subject not found in log"
    assert long_body[:100] in combined, "First 100 chars of body not in log"
    assert long_body[:101] not in combined, "Body was not truncated at 100 chars"


# ---------------------------------------------------------------------------
# Test 4: Respects USE_MOCK_SMTP=true env var (no kwarg needed)
# ---------------------------------------------------------------------------

def test_env_var_use_mock_smtp_true(monkeypatch):
    """SMTPAdapter reads USE_MOCK_SMTP from env; no use_mock kwarg required."""
    monkeypatch.setenv("USE_MOCK_SMTP", "true")
    for key in ("SMTP_USERNAME", "SMTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    mod = _fresh_adapter_module()

    adapter = mod.SMTPAdapter()
    adapter.send_alert("x@y.com", "Sub", "Body")


# ---------------------------------------------------------------------------
# Test 5: Instantiable without any SMTP env vars in mock mode
# ---------------------------------------------------------------------------

def test_mock_mode_no_env_vars_needed(monkeypatch):
    """SMTPAdapter(use_mock=True) instantiates even when all SMTP vars absent."""
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)

    from adapters.smtp_adapter import SMTPAdapter

    adapter = SMTPAdapter(use_mock=True)
    assert adapter is not None


# ---------------------------------------------------------------------------
# Test 6: send_alert() accepts arbitrary recipient, subject, body
# ---------------------------------------------------------------------------

def test_send_alert_accepts_arbitrary_strings():
    """send_alert() forwards whatever strings are passed — nothing hardcoded."""
    from adapters.smtp_adapter import SMTPAdapter

    adapter = SMTPAdapter(use_mock=True)
    adapter.send_alert(
        recipient="different@recipient.org",
        subject="Unique Subject 12345",
        body="Body with special chars: <>&\"'",
    )


# ---------------------------------------------------------------------------
# Test 7: SMTP_HOST defaults to smtp.office365.com; reads from env
# ---------------------------------------------------------------------------

def test_smtp_host_defaults_to_office365(monkeypatch):
    """SMTPAdapter._host defaults to smtp.office365.com when SMTP_HOST not set."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("SMTP_USERNAME", "user@outlook.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    mod = _fresh_adapter_module()
    adapter = mod.SMTPAdapter()
    assert adapter._host == "smtp.office365.com"


def test_smtp_host_read_from_env(monkeypatch):
    """SMTPAdapter._host reads SMTP_HOST from environment."""
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    mod = _fresh_adapter_module()
    adapter = mod.SMTPAdapter()
    assert adapter._host == "smtp.gmail.com"


# ---------------------------------------------------------------------------
# Test 8: __init__ does not raise when use_mock=True even with missing creds
# ---------------------------------------------------------------------------

def test_init_does_not_raise_in_mock_mode(monkeypatch):
    """SMTPAdapter.__init__ with use_mock=True never raises for missing config."""
    for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)

    from adapters.smtp_adapter import SMTPAdapter

    try:
        SMTPAdapter(use_mock=True)
    except Exception as exc:
        pytest.fail(f"SMTPAdapter(use_mock=True) unexpectedly raised: {exc}")


# ---------------------------------------------------------------------------
# Test 9: Missing SMTP_USERNAME raises ValueError with clear message (non-mock)
# ---------------------------------------------------------------------------

def test_missing_smtp_username_raises_value_error(monkeypatch):
    """When use_mock=False and SMTP_USERNAME is absent, ValueError with clear msg."""
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("USE_MOCK_SMTP", raising=False)

    mod = _fresh_adapter_module()

    with pytest.raises(ValueError) as exc_info:
        mod.SMTPAdapter(use_mock=False)

    message = str(exc_info.value)
    assert "SMTP_USERNAME" in message, (
        f"ValueError message should mention SMTP_USERNAME, got: {message!r}"
    )
