"""
Tests for adapters/ews_scraper.py — EWSAdapter class.

All tests in this file run in mock mode or validate configuration behaviour;
none require a live Exchange server.
"""

import logging
import os
import importlib
import sys
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_adapter_module():
    """Force-reload ews_scraper so that env vars picked up at import time
    are re-evaluated during each test that manipulates os.environ."""
    mod_name = "adapters.ews_scraper"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import adapters.ews_scraper as m
    return m


# ---------------------------------------------------------------------------
# Test 1: send_alert() in mock mode returns without error
# ---------------------------------------------------------------------------

def test_send_alert_mock_returns_without_error():
    """EWSAdapter(use_mock=True).send_alert() completes without raising."""
    from adapters.ews_scraper import EWSAdapter

    adapter = EWSAdapter(use_mock=True)
    # Must not raise
    adapter.send_alert(
        recipient="user@example.com",
        subject="Test Subject",
        body="Test body content.",
    )


# ---------------------------------------------------------------------------
# Test 2: Mock mode does NOT attempt to use exchangelib Account
# ---------------------------------------------------------------------------

def test_mock_mode_does_not_use_exchangelib_account(monkeypatch):
    """In mock mode, send_alert() must not touch exchangelib Account."""
    import adapters.ews_scraper as module

    # Patch Account to raise if called — mock mode must never reach it
    def _account_should_not_be_called(*args, **kwargs):
        raise AssertionError("exchangelib Account was called in mock mode!")

    monkeypatch.setattr(module, "Account", _account_should_not_be_called, raising=False)

    from adapters.ews_scraper import EWSAdapter

    adapter = EWSAdapter(use_mock=True)
    # This should not invoke Account
    adapter.send_alert("a@b.com", "S", "B")


# ---------------------------------------------------------------------------
# Test 3: Mock mode logs recipient, subject, and first 100 chars of body
# ---------------------------------------------------------------------------

def test_mock_mode_logs_email_content(caplog):
    """send_alert() in mock mode logs recipient, subject, body preview."""
    from adapters.ews_scraper import EWSAdapter

    long_body = "X" * 200  # Body longer than 100 chars
    adapter = EWSAdapter(use_mock=True)

    with caplog.at_level(logging.INFO, logger="adapters.ews_scraper"):
        adapter.send_alert(
            recipient="admin@corp.com",
            subject="Toner Alert",
            body=long_body,
        )

    combined = " ".join(caplog.messages)
    assert "admin@corp.com" in combined, "Recipient not found in log"
    assert "Toner Alert" in combined, "Subject not found in log"
    # First 100 chars of body must appear; the remaining 100 must NOT appear as a
    # continuous string (i.e., the body was truncated, not logged in full)
    assert long_body[:100] in combined, "First 100 chars of body not in log"
    assert long_body[:101] not in combined, "Body was not truncated at 100 chars"


# ---------------------------------------------------------------------------
# Test 4: Respects USE_MOCK_EWS=true env var (no kwarg needed)
# ---------------------------------------------------------------------------

def test_env_var_use_mock_ews_true(monkeypatch):
    """EWSAdapter reads USE_MOCK_EWS from env; no use_mock kwarg required."""
    monkeypatch.setenv("USE_MOCK_EWS", "true")
    # Remove any EWS env vars to prove mock works without them
    for key in ("EWS_SERVER", "EWS_USERNAME", "EWS_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    mod = _fresh_adapter_module()

    # Instantiate without any kwarg — should not raise
    adapter = mod.EWSAdapter()
    # send_alert must also not raise
    adapter.send_alert("x@y.com", "Sub", "Body")


# ---------------------------------------------------------------------------
# Test 5: Instantiable without any EWS env vars in mock mode
# ---------------------------------------------------------------------------

def test_mock_mode_no_env_vars_needed(monkeypatch):
    """EWSAdapter(use_mock=True) instantiates even when all EWS vars absent."""
    for key in ("EWS_SERVER", "EWS_USERNAME", "EWS_PASSWORD", "EWS_AUTH_TYPE"):
        monkeypatch.delenv(key, raising=False)

    from adapters.ews_scraper import EWSAdapter

    # Must not raise despite missing env vars
    adapter = EWSAdapter(use_mock=True)
    assert adapter is not None


# ---------------------------------------------------------------------------
# Test 6: send_alert() accepts arbitrary recipient, subject, body
# ---------------------------------------------------------------------------

def test_send_alert_accepts_arbitrary_strings():
    """send_alert() must forward whatever strings are passed — nothing hardcoded."""
    from adapters.ews_scraper import EWSAdapter

    adapter = EWSAdapter(use_mock=True)
    # Different values from the defaults used elsewhere in tests
    adapter.send_alert(
        recipient="different@recipient.org",
        subject="Unique Subject 12345",
        body="Body with special chars: <>&\"'",
    )


# ---------------------------------------------------------------------------
# Test 7: auth_type defaults to NTLM; respects EWS_AUTH_TYPE env var
# ---------------------------------------------------------------------------

def test_auth_type_defaults_to_ntlm(monkeypatch):
    """EWSAdapter.auth_type defaults to 'NTLM' when EWS_AUTH_TYPE is not set."""
    monkeypatch.delenv("EWS_AUTH_TYPE", raising=False)

    from adapters.ews_scraper import EWSAdapter

    adapter = EWSAdapter(use_mock=True)
    assert adapter.auth_type == "NTLM"


def test_auth_type_read_from_env(monkeypatch):
    """EWSAdapter.auth_type reads EWS_AUTH_TYPE from environment."""
    monkeypatch.setenv("EWS_AUTH_TYPE", "BASIC")

    from adapters.ews_scraper import EWSAdapter

    adapter = EWSAdapter(use_mock=True)
    assert adapter.auth_type == "BASIC"


# ---------------------------------------------------------------------------
# Test 8: __init__ does not raise when use_mock=True even with missing creds
# ---------------------------------------------------------------------------

def test_init_does_not_raise_in_mock_mode(monkeypatch):
    """EWSAdapter.__init__ with use_mock=True never raises for missing config."""
    for key in ("EWS_SERVER", "EWS_USERNAME", "EWS_PASSWORD", "EWS_AUTH_TYPE"):
        monkeypatch.delenv(key, raising=False)

    from adapters.ews_scraper import EWSAdapter

    try:
        EWSAdapter(use_mock=True)
    except Exception as exc:
        pytest.fail(f"EWSAdapter(use_mock=True) unexpectedly raised: {exc}")


# ---------------------------------------------------------------------------
# Test 9: Missing EWS_SERVER raises ValueError with clear message (non-mock)
# ---------------------------------------------------------------------------

def test_missing_ews_server_raises_value_error(monkeypatch):
    """When use_mock=False and EWS_SERVER is absent, ValueError with clear msg."""
    monkeypatch.delenv("EWS_SERVER", raising=False)
    monkeypatch.delenv("USE_MOCK_EWS", raising=False)

    mod = _fresh_adapter_module()

    with pytest.raises(ValueError) as exc_info:
        mod.EWSAdapter(use_mock=False)

    message = str(exc_info.value)
    assert "EWS_SERVER" in message, (
        f"ValueError message should mention EWS_SERVER, got: {message!r}"
    )
