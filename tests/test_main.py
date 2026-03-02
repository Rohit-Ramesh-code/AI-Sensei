"""
tests/test_main.py — Unit tests for main.py entry point logic.

Tests cover:
  - _validate_env(): missing required vars, invalid POLL_INTERVAL_MINUTES
  - _build_initial_state(): all 8 AgentState keys at correct defaults
  - run_job() error boundary: exception does not propagate; pipeline_error is logged

All tests run without real hardware, SMTP, or OpenAI credentials.
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _validate_env tests
# ---------------------------------------------------------------------------

class TestValidateEnv:
    def test_validate_env_missing_snmp_host(self, monkeypatch, capsys):
        """When SNMP_HOST is unset, exits with code 1 and mentions SNMP_HOST."""
        monkeypatch.delenv("SNMP_HOST", raising=False)
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")

        from main import _validate_env

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "SNMP_HOST" in captured.out

    def test_validate_env_missing_alert_recipient(self, monkeypatch, capsys):
        """When ALERT_RECIPIENT is unset, exits with code 1 and mentions ALERT_RECIPIENT."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.delenv("ALERT_RECIPIENT", raising=False)

        from main import _validate_env

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ALERT_RECIPIENT" in captured.out

    def test_validate_env_both_missing(self, monkeypatch, capsys):
        """When both SNMP_HOST and ALERT_RECIPIENT are unset, both appear in the exit message."""
        monkeypatch.delenv("SNMP_HOST", raising=False)
        monkeypatch.delenv("ALERT_RECIPIENT", raising=False)

        from main import _validate_env

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "SNMP_HOST" in captured.out
        assert "ALERT_RECIPIENT" in captured.out

    def test_validate_env_valid_defaults(self, monkeypatch):
        """When required vars are set, returns 60 (default POLL_INTERVAL_MINUTES)."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.delenv("POLL_INTERVAL_MINUTES", raising=False)

        from main import _validate_env

        result = _validate_env()
        assert result == 60

    def test_validate_env_custom_interval(self, monkeypatch):
        """POLL_INTERVAL_MINUTES=30 returns 30."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "30")

        from main import _validate_env

        result = _validate_env()
        assert result == 30

    def test_validate_env_zero_interval(self, monkeypatch, capsys):
        """POLL_INTERVAL_MINUTES=0 calls sys.exit(1) with message containing POLL_INTERVAL_MINUTES."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "0")

        from main import _validate_env

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "POLL_INTERVAL_MINUTES" in captured.out

    def test_validate_env_negative_interval(self, monkeypatch, capsys):
        """POLL_INTERVAL_MINUTES=-5 calls sys.exit(1)."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "-5")

        from main import _validate_env

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1

    def test_validate_env_non_numeric_interval(self, monkeypatch, capsys):
        """POLL_INTERVAL_MINUTES=abc calls sys.exit(1)."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "abc")

        from main import _validate_env

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "POLL_INTERVAL_MINUTES" in captured.out


# ---------------------------------------------------------------------------
# _build_initial_state tests
# ---------------------------------------------------------------------------

class TestBuildInitialState:
    def test_build_initial_state_has_all_keys(self):
        """_build_initial_state() returns a dict with all 8 AgentState keys at correct defaults."""
        from main import _build_initial_state

        state = _build_initial_state()

        # Verify all 8 required keys are present
        assert "poll_result" in state
        assert "alert_needed" in state
        assert "alert_sent" in state
        assert "suppression_reason" in state
        assert "decision_log" in state
        assert "flagged_colors" in state
        assert "llm_confidence" in state
        assert "llm_reasoning" in state

        # Verify correct default values
        assert state["poll_result"] is None
        assert state["alert_needed"] is False
        assert state["alert_sent"] is False
        assert state["suppression_reason"] is None
        assert state["decision_log"] == []
        assert state["flagged_colors"] is None
        assert state["llm_confidence"] is None
        assert state["llm_reasoning"] is None

    def test_build_initial_state_returns_fresh_dict_each_call(self):
        """Each call to _build_initial_state() returns a new dict — no state leaks."""
        from main import _build_initial_state

        state1 = _build_initial_state()
        state2 = _build_initial_state()

        # Should be equal in value but not the same object
        assert state1 == state2
        assert state1 is not state2

        # Mutating one should not affect the other
        state1["decision_log"].append("entry")
        assert state2["decision_log"] == []


# ---------------------------------------------------------------------------
# run_job error boundary test
# ---------------------------------------------------------------------------

class TestRunJobErrorBoundary:
    def test_run_job_logs_pipeline_error_on_exception(self, monkeypatch):
        """
        When graph.invoke() raises an exception, run_job() does not propagate it
        (scheduler stays alive) and append_poll_result is called with event_type=pipeline_error.
        """
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.delenv("POLL_INTERVAL_MINUTES", raising=False)

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = Exception("boom")

        captured_jobs = []

        def fake_add_job(func, **kwargs):
            captured_jobs.append(func)

        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = fake_add_job
        mock_scheduler.start.return_value = None

        with patch("main.build_graph", return_value=mock_graph), \
             patch("main.BackgroundScheduler", return_value=mock_scheduler), \
             patch("main.append_poll_result") as mock_append, \
             patch("main.time") as mock_time:
            # Make the while True loop exit after first sleep
            mock_time.sleep.side_effect = KeyboardInterrupt

            import main as main_module
            try:
                main_module.main()
            except SystemExit:
                pass

            # The scheduled job function was captured during scheduler.add_job()
            assert len(captured_jobs) == 1, "Expected add_job to capture run_job"
            job_fn = captured_jobs[0]

            # Calling the job should NOT raise (error boundary active)
            job_fn()

            # append_poll_result should have been called with pipeline_error event
            mock_append.assert_called_once()
            call_args = mock_append.call_args[0][0]
            assert call_args["event_type"] == "pipeline_error"
            assert call_args["error"] == "boom"
            assert "timestamp" in call_args
