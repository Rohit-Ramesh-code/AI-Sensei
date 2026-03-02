"""
guardrails/safety_logic.py — Policy Guard for Project Sentinel.

All outbound alert actions must pass through run_policy_guard() before the
Communicator Agent sends any email. Four independent checks are enforced:

  1. Data freshness  — poll timestamp must not be older than STALE_THRESHOLD_MINUTES
  2. SNMP quality    — poll_result.snmp_error must be None
  3. Rate limit      — at most 1 alert per printer per 24-hour window
  4. LLM confidence  — llm_confidence must meet LLM_CONFIDENCE_THRESHOLD (default 0.7)
                       when set; None passes through (cold start / LLM failure)

If any check fails, the alert is suppressed and the suppression event is
appended to the JSONL log via adapters.persistence.append_poll_result().

Public API:
  run_policy_guard(state, *, state_path, log_path) -> AgentState
  record_alert_sent(printer_host, *, state_path) -> None

Design decisions:
- state_path and log_path are keyword-only parameters with defaults so callers
  (production and tests alike) can override without patching globals.
- _load_alert_state() catches both json.JSONDecodeError and OSError so corrupted
  or permission-denied files degrade gracefully to an empty state.
- Timestamps always use timezone.utc to avoid naive/aware TypeError.
- Checks are ordered: freshness → SNMP quality → rate limit → confidence. First
  failure short-circuits; remaining checks are skipped.
- llm_confidence=None passes through the confidence check — cold start and LLM
  failure cases rely on deterministic threshold alerts and must not be suppressed.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import adapters.persistence as persistence
from adapters.persistence import append_poll_result

if TYPE_CHECKING:
    from state_types import AgentState, PollResult

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

ALERT_STATE_PATH = Path("logs/alert_state.json")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_policy_guard(
    state: "AgentState",
    *,
    state_path: Path = ALERT_STATE_PATH,
    log_path: Path = persistence.LOG_PATH,
) -> "AgentState":
    """
    Gate all outbound alerts through four independent policy checks.

    If state["alert_needed"] is False, returns state unchanged (no-op).

    Check order (short-circuits on first failure):
      1. Data freshness  — poll timestamp age vs. STALE_THRESHOLD_MINUTES
      2. SNMP quality    — poll_result["snmp_error"] is not None
      3. Rate limit      — previous alert within last 24 hours
      4. LLM confidence  — llm_confidence < LLM_CONFIDENCE_THRESHOLD (skipped if None)

    On suppression: sets alert_needed=False, sets suppression_reason, appends
    a record to the JSONL log.

    Args:
        state:      AgentState dict flowing through the LangGraph pipeline.
        state_path: Path to alert_state.json (injectable for test isolation).
        log_path:   Path to printer_history.jsonl (injectable for test isolation).

    Returns:
        Updated AgentState dict.
    """
    if not state.get("alert_needed", False):
        logger.debug("Policy guard: alert_needed=False — skipping all checks (no-op)")
        return state

    poll_result: "PollResult" = state["poll_result"]
    printer_host: str = poll_result["printer_host"]

    # --- Check 1: Data freshness ---
    fresh_ok, freshness_reason = check_data_freshness(poll_result)
    if not fresh_ok:
        logger.warning("Policy guard SUPPRESSED (stale data): %s — %s", printer_host, freshness_reason)
        log_suppression(printer_host, reason=freshness_reason, extra={}, log_path=log_path)
        state["alert_needed"] = False
        state["suppression_reason"] = freshness_reason
        state["decision_log"] = state.get("decision_log", []) + [
            f"PolicyGuard: suppressed — {freshness_reason}"
        ]
        return state

    state["decision_log"] = state.get("decision_log", []) + [
        "PolicyGuard: freshness check passed"
    ]

    # --- Check 2: SNMP data quality ---
    quality_ok, quality_reason = check_snmp_quality(poll_result)
    if not quality_ok:
        logger.warning("Policy guard SUPPRESSED (data quality): %s — %s", printer_host, quality_reason)
        log_suppression(printer_host, reason=quality_reason, extra={}, log_path=log_path)
        state["alert_needed"] = False
        state["suppression_reason"] = quality_reason
        state["decision_log"] = state.get("decision_log", []) + [
            f"PolicyGuard: suppressed — {quality_reason}"
        ]
        return state

    state["decision_log"] = state.get("decision_log", []) + [
        "PolicyGuard: SNMP quality check passed"
    ]

    # --- Check 3: Rate limit ---
    rate_ok, rate_reason = check_rate_limit(printer_host, state_path=state_path)
    if not rate_ok:
        logger.warning("Policy guard SUPPRESSED (rate limit): %s — %s", printer_host, rate_reason)
        log_suppression(printer_host, reason=rate_reason, extra={}, log_path=log_path)
        state["alert_needed"] = False
        state["suppression_reason"] = rate_reason
        state["decision_log"] = state.get("decision_log", []) + [
            f"PolicyGuard: suppressed — {rate_reason}"
        ]
        return state

    state["decision_log"] = state.get("decision_log", []) + [
        "PolicyGuard: rate limit check passed"
    ]

    # --- Check 4: LLM confidence ---
    confidence_ok, confidence_reason = check_confidence(state)
    if not confidence_ok:
        logger.warning(
            "Policy guard SUPPRESSED (low confidence): %s — %s",
            printer_host, confidence_reason,
        )
        log_suppression(
            printer_host,
            reason=confidence_reason,
            extra={"confidence": state.get("llm_confidence")},
            log_path=log_path,
        )
        state["alert_needed"] = False
        state["suppression_reason"] = confidence_reason
        state["decision_log"] = state.get("decision_log", []) + [
            f"PolicyGuard: suppressed — {confidence_reason}"
        ]
        return state

    state["decision_log"] = state.get("decision_log", []) + [
        "PolicyGuard: confidence check passed — alert cleared"
    ]
    logger.info("Policy guard CLEARED alert for %s", printer_host)
    return state


def record_alert_sent(
    printer_host: str,
    *,
    state_path: Path = ALERT_STATE_PATH,
) -> None:
    """
    Record that an alert was successfully sent for this printer.

    Performs a read-modify-write on alert_state.json:
      - Loads existing state (or starts with {})
      - Sets state[printer_host]["last_alert_timestamp"] = now (ISO 8601 UTC)
      - Saves back to disk

    Args:
        printer_host: IP address / hostname key in alert_state.json.
        state_path:   Path to alert_state.json (injectable for test isolation).
    """
    now = datetime.now(timezone.utc)
    existing = _load_alert_state(state_path)
    existing[printer_host] = {"last_alert_timestamp": now.isoformat()}
    _save_alert_state(existing, state_path)
    logger.info("record_alert_sent: updated alert_state.json for %s at %s", printer_host, now.isoformat())


# ---------------------------------------------------------------------------
# Internal check helpers (public for direct unit-test access)
# ---------------------------------------------------------------------------

def check_data_freshness(poll_result: "PollResult") -> tuple[bool, Optional[str]]:
    """
    Check whether the poll timestamp is recent enough to act on.

    Reads STALE_THRESHOLD_MINUTES from the environment (default: 120).

    Args:
        poll_result: PollResult dict with ISO 8601 "timestamp" field.

    Returns:
        (True, None) if fresh.
        (False, reason_str) if stale — reason contains age and threshold.
    """
    stale_minutes = float(os.getenv("STALE_THRESHOLD_MINUTES", "120"))
    poll_ts = datetime.fromisoformat(poll_result["timestamp"])
    now = datetime.now(timezone.utc)
    age_minutes = (now - poll_ts).total_seconds() / 60.0

    if age_minutes > stale_minutes:
        reason = f"stale_data: age={age_minutes:.1f}min > threshold={stale_minutes}min"
        return False, reason

    return True, None


def check_snmp_quality(poll_result: "PollResult") -> tuple[bool, Optional[str]]:
    """
    Check whether the SNMP poll succeeded (no transport/protocol error).

    Args:
        poll_result: PollResult dict with optional "snmp_error" field.

    Returns:
        (True, None) if no error.
        (False, reason_str) if snmp_error is set.
    """
    snmp_error = poll_result.get("snmp_error")
    if snmp_error is not None:
        reason = f"data_quality: snmp_error={snmp_error}"
        return False, reason

    return True, None


def check_rate_limit(
    printer_host: str,
    *,
    state_path: Path = ALERT_STATE_PATH,
) -> tuple[bool, Optional[str]]:
    """
    Check whether the 24-hour rate limit has expired for this printer.

    Args:
        printer_host: IP address / hostname to look up in alert_state.json.
        state_path:   Path to alert_state.json (injectable for test isolation).

    Returns:
        (True, None) if no prior alert or window has expired.
        (False, reason_str) if within the 24-hour window.
    """
    alert_state = _load_alert_state(state_path)
    host_entry = alert_state.get(printer_host, {})
    last_ts_str = host_entry.get("last_alert_timestamp")

    if last_ts_str is None:
        return True, None

    try:
        last_ts = datetime.fromisoformat(last_ts_str)
    except (ValueError, TypeError):
        # Unparseable timestamp — treat as no prior alert
        return True, None

    now = datetime.now(timezone.utc)
    elapsed = now - last_ts

    if elapsed < timedelta(hours=24):
        reason = f"rate_limit: last_alert={last_ts_str}"
        return False, reason

    return True, None


def check_confidence(state: "AgentState") -> tuple[bool, Optional[str]]:
    """
    Check LLM confidence meets minimum threshold (4th policy guard check).

    Returns (True, None) when llm_confidence is None — LLM was not called
    (cold start or LLM failure). These cases fall back to deterministic
    threshold logic and must NOT be suppressed by the confidence gate.

    Returns:
        (True, None)  — confidence is acceptable OR LLM was not called.
        (False, reason_str) — confidence < threshold; include score, reason, and std_dev in reason.
    """
    threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))
    confidence = state.get("llm_confidence")

    if confidence is None:
        # LLM not called (cold start or LLM failure) — do not block on confidence.
        # Deterministic fallback alerts are always allowed through.
        return True, None

    if confidence < threshold:
        # Derive contributing factor from flagged_colors std_dev if available
        flagged = state.get("flagged_colors") or []
        std_devs = [
            fc.get("std_dev")
            for fc in flagged
            if fc.get("std_dev") is not None
        ]
        if std_devs:
            avg_std_dev = sum(std_devs) / len(std_devs)
            reason = (
                f"suppressed: confidence={confidence:.2f}, "
                f"reason=erratic_readings, "
                f"std_dev={avg_std_dev:.0f}%"
            )
        else:
            reason = (
                f"suppressed: confidence={confidence:.2f}, "
                f"reason=low_confidence, "
                f"threshold={threshold:.2f}"
            )
        return False, reason

    return True, None


def log_suppression(
    printer_host: str,
    reason: str,
    extra: dict,
    *,
    log_path: Path = persistence.LOG_PATH,
) -> None:
    """
    Append a suppression record to the JSONL audit log.

    The record always includes: event_type, printer_host, timestamp, reason.
    Additional context can be passed via the extra dict (merged into the record).

    Args:
        printer_host: IP address / hostname of the printer.
        reason:       Human-readable suppression reason string.
        extra:        Additional fields to merge into the log record.
        log_path:     Path to JSONL file (injectable for test isolation).
    """
    now = datetime.now(timezone.utc)
    record: dict = {
        "event_type": "suppressed_alert",
        "printer_host": printer_host,
        "timestamp": now.isoformat(),
        "reason": reason,
        **extra,
    }
    append_poll_result(record, log_path=log_path)
    logger.info("Suppression logged: %s — %s", printer_host, reason)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_alert_state(state_path: Path) -> dict:
    """
    Load alert_state.json from disk.

    Returns {} if the file does not exist or contains invalid JSON.
    Handles OSError (permission denied, locked file) the same way.

    Args:
        state_path: Path to alert_state.json.

    Returns:
        Parsed dict or {} on any read/parse failure.
    """
    if not state_path.exists():
        return {}

    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("_load_alert_state: failed to read %s — %s; treating as empty", state_path, exc)
        return {}


def _save_alert_state(state: dict, state_path: Path) -> None:
    """
    Write alert_state dict to disk as formatted JSON.

    Creates parent directories if they do not exist.

    Args:
        state:      Dict to serialise.
        state_path: Target file path.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
