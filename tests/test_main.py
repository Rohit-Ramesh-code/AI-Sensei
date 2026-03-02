"""
tests/test_main.py — Unit tests for main.py entry point logic.

Tests cover:
  - _validate_env(): missing required vars, invalid POLL_INTERVAL_MINUTES
  - _build_initial_state(): all 8 AgentState keys at correct defaults
  - run_job() error boundary: exception does not propagate; pipeline_error is logged
  - run_job() SNMP poll wiring: polls SNMPAdapter, persists PollResult before graph.invoke()

All tests run without real hardware, SMTP, or OpenAI credentials.

Import note: _validate_env and _build_initial_state are imported at module level
(not inside each test function) so that load_dotenv() in main.py does not re-run
on every test and overwrite monkeypatched env vars.
"""

import pytest
from unittest.mock import MagicMock, patch

# Import once at module level to avoid re-running load_dotenv() per test.
from main import _validate_env, _build_initial_state  # noqa: E402


# ---------------------------------------------------------------------------
# _validate_env tests
# ---------------------------------------------------------------------------

class TestValidateEnv:
    def test_validate_env_missing_snmp_host(self, monkeypatch, capsys):
        """When SNMP_HOST is unset, exits with code 1 and mentions SNMP_HOST."""
        monkeypatch.delenv("SNMP_HOST", raising=False)
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "SNMP_HOST" in captured.out

    def test_validate_env_missing_alert_recipient(self, monkeypatch, capsys):
        """When ALERT_RECIPIENT is unset, exits with code 1 and mentions ALERT_RECIPIENT."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.delenv("ALERT_RECIPIENT", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ALERT_RECIPIENT" in captured.out

    def test_validate_env_both_missing(self, monkeypatch, capsys):
        """When both SNMP_HOST and ALERT_RECIPIENT are unset, both appear in the exit message."""
        monkeypatch.delenv("SNMP_HOST", raising=False)
        monkeypatch.delenv("ALERT_RECIPIENT", raising=False)

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

        result = _validate_env()
        assert result == 60

    def test_validate_env_custom_interval(self, monkeypatch):
        """POLL_INTERVAL_MINUTES=30 returns 30."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "30")

        result = _validate_env()
        assert result == 30

    def test_validate_env_zero_interval(self, monkeypatch, capsys):
        """POLL_INTERVAL_MINUTES=0 calls sys.exit(1) with message containing POLL_INTERVAL_MINUTES."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "0")

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

        with pytest.raises(SystemExit) as exc_info:
            _validate_env()

        assert exc_info.value.code == 1

    def test_validate_env_non_numeric_interval(self, monkeypatch, capsys):
        """POLL_INTERVAL_MINUTES=abc calls sys.exit(1)."""
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.setenv("POLL_INTERVAL_MINUTES", "abc")

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

        Note: after the Phase 4.1 gap closure, append_poll_result is called twice:
        once with the poll_result (SNMP-04) and once with event_type=pipeline_error.
        This test verifies the error boundary event exists in the call list.
        """
        monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
        monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
        monkeypatch.delenv("POLL_INTERVAL_MINUTES", raising=False)

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = Exception("boom")

        mock_poll_result = {
            "printer_host": "192.168.1.1",
            "timestamp": "2026-03-02T10:00:00+00:00",
            "readings": [],
            "snmp_error": None,
            "overall_quality_ok": True,
        }
        mock_snmp_instance = MagicMock()
        mock_snmp_instance.poll.return_value = mock_poll_result
        mock_snmp_cls = MagicMock(return_value=mock_snmp_instance)

        captured_jobs = []

        def fake_add_job(func, **kwargs):
            captured_jobs.append(func)

        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = fake_add_job
        mock_scheduler.start.return_value = None

        with patch("main.SNMPAdapter", mock_snmp_cls), \
             patch("main.build_graph", return_value=mock_graph), \
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

            # append_poll_result is called at least once for the pipeline_error event.
            # (It is also called once for the successful poll_result before graph.invoke.)
            assert mock_append.call_count >= 1
            # Find the pipeline_error call in all calls
            all_calls = mock_append.call_args_list
            error_calls = [
                c for c in all_calls
                if isinstance(c[0][0], dict) and c[0][0].get("event_type") == "pipeline_error"
            ]
            assert len(error_calls) == 1, (
                f"Expected exactly one pipeline_error call; got: {all_calls}"
            )
            call_args = error_calls[0][0][0]
            assert call_args["error"] == "boom"
            assert "timestamp" in call_args


# ---------------------------------------------------------------------------
# run_job() SNMP poll wiring tests (Phase 4.1 gap closure)
# ---------------------------------------------------------------------------

def _run_job_under_patches(monkeypatch, mock_snmp_cls, mock_graph, mock_append,
                           call_job: bool = True):
    """
    Module-level helper: start main() with all dependencies patched, capture
    the run_job closure, and optionally call it — all within a single patch
    context so the closured references to main.SNMPAdapter and
    main.append_poll_result resolve to the mocks.

    Returns (job_fn, mock_snmp_cls, mock_graph, mock_append).
    """
    monkeypatch.setenv("SNMP_HOST", "192.168.1.1")
    monkeypatch.setenv("SNMP_COMMUNITY", "public")
    monkeypatch.setenv("ALERT_RECIPIENT", "test@example.com")
    monkeypatch.delenv("POLL_INTERVAL_MINUTES", raising=False)

    captured_jobs = []

    def fake_add_job(func, **kwargs):
        captured_jobs.append(func)

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = fake_add_job
    mock_scheduler.start.return_value = None

    import main as main_module

    with patch("main.SNMPAdapter", mock_snmp_cls), \
         patch("main.build_graph", return_value=mock_graph), \
         patch("main.BackgroundScheduler", return_value=mock_scheduler), \
         patch("main.append_poll_result", mock_append), \
         patch("main.time") as mock_time:
        mock_time.sleep.side_effect = KeyboardInterrupt
        try:
            main_module.main()
        except SystemExit:
            pass

        assert len(captured_jobs) == 1, "Expected add_job to capture exactly one run_job"
        job_fn = captured_jobs[0]

        if call_job:
            # Call the closure while patches are still active
            job_fn()

    return job_fn


class TestRunJobSnmpWiring:
    def test_run_job_polls_snmp_and_injects_into_graph(self, monkeypatch):
        """
        run_job() calls SNMPAdapter.poll() exactly once and passes the result as
        initial_state['poll_result'] to graph.invoke().
        """
        mock_poll_result = {
            "printer_host": "192.168.1.1",
            "timestamp": "2026-03-02T10:00:00+00:00",
            "readings": [],
            "snmp_error": None,
            "overall_quality_ok": True,
        }
        mock_snmp_instance = MagicMock()
        mock_snmp_instance.poll.return_value = mock_poll_result

        mock_snmp_cls = MagicMock(return_value=mock_snmp_instance)
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "alert_needed": False,
            "alert_sent": False,
            "suppression_reason": None,
        }
        mock_append = MagicMock()

        _run_job_under_patches(monkeypatch, mock_snmp_cls, mock_graph, mock_append)

        # SNMPAdapter.poll() must have been called exactly once
        mock_snmp_instance.poll.assert_called_once()

        # graph.invoke() must have received poll_result == the mock PollResult
        assert mock_graph.invoke.called, "graph.invoke() was not called"
        invoked_state = mock_graph.invoke.call_args[0][0]
        assert invoked_state["poll_result"] == mock_poll_result, (
            f"Expected poll_result to be injected into state, got: {invoked_state['poll_result']}"
        )

    def test_run_job_persists_poll_result_before_graph_invoke(self, monkeypatch):
        """
        run_job() calls append_poll_result(poll_result) BEFORE graph.invoke() so that
        history accumulates even if the graph raises.
        """
        mock_poll_result = {
            "printer_host": "192.168.1.1",
            "timestamp": "2026-03-02T10:00:00+00:00",
            "readings": [],
            "snmp_error": None,
            "overall_quality_ok": True,
        }
        mock_snmp_instance = MagicMock()
        mock_snmp_instance.poll.return_value = mock_poll_result

        mock_snmp_cls = MagicMock(return_value=mock_snmp_instance)

        # Track call order: was append called before invoke?
        call_order = []

        mock_append = MagicMock(side_effect=lambda *a, **kw: call_order.append("append"))
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = lambda *a, **kw: (
            call_order.append("invoke") or {
                "alert_needed": False,
                "alert_sent": False,
                "suppression_reason": None,
            }
        )

        _run_job_under_patches(monkeypatch, mock_snmp_cls, mock_graph, mock_append)

        # append must appear before invoke in call_order
        assert "append" in call_order, "append_poll_result was never called on the happy path"
        assert "invoke" in call_order, "graph.invoke was never called"
        append_idx = call_order.index("append")
        invoke_idx = call_order.index("invoke")
        assert append_idx < invoke_idx, (
            f"append_poll_result must be called BEFORE graph.invoke(); "
            f"got call order: {call_order}"
        )

        # append_poll_result should have been called with the mock PollResult
        mock_append.assert_called_once_with(mock_poll_result)

    def test_run_job_error_boundary_when_snmp_poll_raises(self, monkeypatch):
        """
        When SNMPAdapter.poll() raises, run_job() does NOT propagate the exception.
        The existing except block fires and appends event_type=pipeline_error.
        The except block does NOT reference the poll_result variable (no UnboundLocalError).
        """
        mock_snmp_instance = MagicMock()
        mock_snmp_instance.poll.side_effect = RuntimeError("snmp boom")

        mock_snmp_cls = MagicMock(return_value=mock_snmp_instance)
        mock_graph = MagicMock()
        mock_append = MagicMock()

        _run_job_under_patches(monkeypatch, mock_snmp_cls, mock_graph, mock_append)

        # append_poll_result should have been called once with event_type=pipeline_error
        mock_append.assert_called_once()
        call_arg = mock_append.call_args[0][0]
        assert call_arg["event_type"] == "pipeline_error", (
            f"Expected event_type=pipeline_error, got: {call_arg}"
        )
        assert "snmp boom" in call_arg["error"]

        # graph.invoke() must NOT have been called (failed before reaching it)
        mock_graph.invoke.assert_not_called()
