"""
agents/communicator.py — Email dispatch agent for Project Sentinel.

Implements three public functions:
  - build_subject(flagged_colors) -> str
  - build_body(printer_host, flagged_colors) -> str
  - run_communicator(state) -> AgentState

Design decisions:
- Subject uses an em dash character (U+2014) to separate the urgency prefix from
  the color list, matching the format locked in CONTEXT.md.
- Overall urgency in the subject is CRITICAL if ANY flagged color is CRITICAL;
  otherwise WARNING. Mixed lists always promote to CRITICAL.
- A single send_alert() call is made regardless of how many colors are flagged.
  The body lists all flagged colors in one email — no per-color emails.
- record_alert_sent() is called after every successful send to update the
  rate limit state in alert_state.json (GURD-04 requirement).
- Mock mode is fully controlled by USE_MOCK_SMTP=true env var or the use_mock
  kwarg on SMTPAdapter() — no extra logic needed in this module.

Environment variables required at runtime:
  ALERT_RECIPIENT — Destination email address (raises ValueError if absent).
  USE_MOCK_SMTP   — Set to 'true' to log instead of send (dev/test).
"""

from __future__ import annotations

import logging
import os

from adapters.smtp_adapter import SMTPAdapter
from guardrails.safety_logic import record_alert_sent
from state_types import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email construction helpers
# ---------------------------------------------------------------------------

def build_subject(flagged_colors: list[dict]) -> str:
    """
    Build the email subject line for a toner alert.

    The overall urgency is "CRITICAL" if any flagged color has urgency="CRITICAL",
    otherwise "WARNING". Color parts are formatted as "{Color} {display_value}"
    joined by ", ".

    Format:
        [Sentinel] {urgency}: Printer toner low \u2014 {color_parts}

    Args:
        flagged_colors: List of dicts with keys: color, urgency, display_value.

    Returns:
        Formatted email subject string.
    """
    # Determine overall urgency: CRITICAL if any entry is CRITICAL
    overall_urgency = (
        "CRITICAL"
        if any(entry["urgency"] == "CRITICAL" for entry in flagged_colors)
        else "WARNING"
    )

    # Build comma-separated color parts: "Cyan 8.0%", "Yellow below low threshold (unquantified)"
    color_parts = ", ".join(
        f"{entry['color'].capitalize()} {entry['display_value']}"
        for entry in flagged_colors
    )

    return f"[Sentinel] {overall_urgency}: Printer toner low \u2014 {color_parts}"


def build_body(
    printer_host: str,
    flagged_colors: list[dict],
    llm_reasoning: "str | None" = None,
    llm_confidence: "float | None" = None,
) -> str:
    """
    Build the plain-text email body for a toner alert.

    Format (with llm_reasoning and llm_confidence):
        Printer: {printer_host}

        Low toner detected:
          {Color}: {display_value} [{urgency}]
          Recommended action: Order {color} toner

        Confidence: {X}%
        Analysis:
        {llm_reasoning}

    Format (with llm_reasoning, no llm_confidence):
        Printer: {printer_host}

        Low toner detected:
          {Color}: {display_value} [{urgency}]
          Recommended action: Order {color} toner

        Analysis:
        {llm_reasoning}

    Format (without llm_reasoning — fallback note):
        Printer: {printer_host}

        Low toner detected:
          {Color}: {display_value} [{urgency}]
          Recommended action: Order {color} toner

        Note: LLM analysis unavailable — alert based on threshold check only.

    Args:
        printer_host:    IP address or hostname of the printer.
        flagged_colors:  List of dicts with keys: color, urgency, display_value.
        llm_reasoning:   Optional LLM analyst reasoning text. When set, an
                         "Analysis:" section is appended. When None, the locked
                         fallback note is appended instead.
        llm_confidence:  Optional LLM confidence score (0.0–1.0). When set
                         alongside llm_reasoning, a "Confidence: X%" line is
                         emitted before the "Analysis:" section (ALRT-02).

    Returns:
        Formatted plain-text email body string.
    """
    lines = [f"Printer: {printer_host}", "", "Low toner detected:"]

    for entry in flagged_colors:
        color = entry["color"]
        display_value = entry["display_value"]
        urgency = entry["urgency"]
        lines.append(f"  {color.capitalize()}: {display_value} [{urgency}]")
        lines.append(f"  Recommended action: Order {color} toner")
        lines.append("")  # blank line between color entries

    if llm_reasoning is not None:
        if llm_confidence is not None:
            lines.append(f"Confidence: {llm_confidence:.0%}")
        lines.append("Analysis:")
        lines.append(llm_reasoning)
    else:
        lines.append("Note: LLM analysis unavailable — alert based on threshold check only.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent node
# ---------------------------------------------------------------------------

def run_communicator(state: AgentState) -> AgentState:
    """
    Send a single toner alert email if alert_needed is True.

    Steps:
      1. If alert_needed is False: log skip and return unchanged.
      2. Read ALERT_RECIPIENT from env — raise ValueError if absent.
      3. Build subject and body from flagged_colors and printer_host.
      4. Instantiate SMTPAdapter (mock mode via USE_MOCK_SMTP env var).
      5. Call send_alert() once with recipient, subject, body.
      6. Call record_alert_sent() to update the 24-hour rate limit state.
      7. Set alert_sent=True and append to decision_log.

    Args:
        state: Current AgentState from the LangGraph pipeline.

    Returns:
        Updated AgentState with alert_sent=True and decision_log updated.

    Raises:
        ValueError: If ALERT_RECIPIENT environment variable is not set or is empty.
    """
    if not state["alert_needed"]:
        log_entry = "communicator: skipped (alert_needed=False)"
        logger.info(log_entry)
        state["decision_log"] = state["decision_log"] + [log_entry]
        return state

    # Validate required environment variable before attempting any send
    alert_recipient = os.getenv("ALERT_RECIPIENT")
    if not alert_recipient:
        raise ValueError(
            "ALERT_RECIPIENT env var must be set to send alert emails. "
            "Set ALERT_RECIPIENT to the destination email address "
            "(e.g. admin@example.com) or enable mock mode with USE_MOCK_SMTP=true "
            "if testing without a real recipient."
        )

    printer_host: str = state["poll_result"]["printer_host"]
    flagged_colors: list[dict] = state["flagged_colors"] or []

    subject = build_subject(flagged_colors)
    body = build_body(
        printer_host,
        flagged_colors,
        llm_reasoning=state.get("llm_reasoning"),
        llm_confidence=state.get("llm_confidence"),
    )

    # Instantiate adapter — picks up USE_MOCK_SMTP from environment automatically
    smtp = SMTPAdapter()
    smtp.send_alert(alert_recipient, subject, body)

    # Update rate limit state so the Policy Guard suppresses the next alert within 24h
    record_alert_sent(printer_host)

    state["alert_sent"] = True
    log_entry = f"communicator: alert sent to {alert_recipient}"
    logger.info(log_entry)
    state["decision_log"] = state["decision_log"] + [log_entry]

    return state
