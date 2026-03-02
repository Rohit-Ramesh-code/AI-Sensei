"""
main.py — Entry point for Project Sentinel.

Orchestrates startup: env validation, graph compilation, APScheduler job
registration, and graceful shutdown on KeyboardInterrupt or SIGTERM.

Design decisions:
- load_dotenv() is called BEFORE any project module imports to ensure all env
  vars are in os.environ before any module-level code reads them (RESEARCH.md
  Pitfall 2).
- build_graph() is called ONCE at startup; the compiled graph is reused across
  all polling cycles (never compiled inside run_job).
- _build_initial_state() is called INSIDE run_job() each cycle — fresh state
  per cycle, no leakage between polls.
- next_run_time=datetime.now() causes APScheduler to fire the first job
  immediately when scheduler.start() is called (not after the first interval).
- SIGTERM is handled explicitly so container/systemd shutdowns are clean.
"""

# ---------------------------------------------------------------------------
# stdlib imports
# ---------------------------------------------------------------------------

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# third-party — load env vars BEFORE any project module import
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

load_dotenv()  # MUST run before project module imports

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from apscheduler.triggers.interval import IntervalTrigger  # noqa: E402

# ---------------------------------------------------------------------------
# project modules (safe to import after load_dotenv)
# ---------------------------------------------------------------------------

from adapters.persistence import append_poll_result  # noqa: E402
from adapters.snmp_adapter import SNMPAdapter  # noqa: E402
from agents.supervisor import build_graph  # noqa: E402

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("sentinel.main")

# ---------------------------------------------------------------------------
# Required env var names
# ---------------------------------------------------------------------------

REQUIRED_ENV_VARS = ["SNMP_HOST", "ALERT_RECIPIENT"]


# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------

def _validate_env() -> int:
    """
    Validate required environment variables and return poll_interval_minutes.

    Checks:
    1. SNMP_HOST and ALERT_RECIPIENT must be non-empty strings.
    2. POLL_INTERVAL_MINUTES (default "60") must be a positive integer.

    Returns:
        poll_interval_minutes (int) — validated polling interval.

    Raises:
        SystemExit(1) — on missing required vars or invalid interval.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    interval_str = os.getenv("POLL_INTERVAL_MINUTES", "60")
    try:
        poll_interval = int(interval_str)
    except ValueError:
        print(
            f"ERROR: POLL_INTERVAL_MINUTES={interval_str!r} — must be a positive integer"
        )
        sys.exit(1)

    if poll_interval <= 0:
        print(
            f"ERROR: POLL_INTERVAL_MINUTES={interval_str!r} — must be a positive integer"
        )
        sys.exit(1)

    return poll_interval


# ---------------------------------------------------------------------------
# Initial state factory
# ---------------------------------------------------------------------------

def _build_initial_state() -> dict:
    """
    Build a fresh AgentState dict for one polling cycle.

    Must be called inside run_job() each cycle — never reused across invocations.
    All 8 AgentState keys are set to their default values.

    Returns:
        A fresh AgentState dict with all 8 keys at default values.
    """
    return {
        "poll_result": None,
        "alert_needed": False,
        "alert_sent": False,
        "suppression_reason": None,
        "decision_log": [],
        "flagged_colors": None,
        "llm_confidence": None,
        "llm_reasoning": None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Start Project Sentinel: validate env, compile graph, start scheduler.

    Execution flow:
      1. Validate env vars — exit(1) on failure.
      2. Compile the LangGraph graph once.
      3. Print startup banner.
      4. Register SIGTERM handler.
      5. Create BackgroundScheduler with immediate first poll.
      6. Block in while-True loop; handle KeyboardInterrupt for clean shutdown.
    """
    poll_interval = _validate_env()

    # Compile graph ONCE — reused by all run_job() invocations
    graph = build_graph()

    # Print startup banner
    snmp_host = os.getenv("SNMP_HOST", "unknown")
    print("=== Project Sentinel ===")
    print(f"Printer host : {snmp_host}")
    print(f"Poll interval: every {poll_interval} min — first poll running now")

    logger.info(
        "Sentinel starting up: SNMP_HOST=%s poll_interval=%d min",
        snmp_host,
        poll_interval,
    )

    # Define run_job as closure capturing the compiled graph
    def run_job() -> None:
        """Execute one polling cycle — called by APScheduler on each interval."""
        try:
            host = os.getenv("SNMP_HOST", "localhost")
            community = os.getenv("SNMP_COMMUNITY", "public")
            snmp = SNMPAdapter(host=host, community=community)
            poll_result = snmp.poll()

            # Persist every poll to JSONL before graph invoke (SNMP-04)
            # Must be BEFORE graph.invoke() so history accumulates even if graph raises
            append_poll_result(poll_result)

            initial_state = _build_initial_state()
            initial_state["poll_result"] = poll_result

            state = graph.invoke(initial_state)
            logger.info(
                "Cycle complete: alert_needed=%s alert_sent=%s suppression=%s",
                state.get("alert_needed"),
                state.get("alert_sent"),
                state.get("suppression_reason"),
            )
        except Exception as exc:
            logger.exception("Pipeline error in polling cycle: %s", exc)
            append_poll_result(
                {
                    "event_type": "pipeline_error",
                    "printer_host": os.getenv("SNMP_HOST", "unknown"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
            )

    # SIGTERM handler — clean shutdown for containers / systemd
    scheduler_ref: list = []  # mutable container so _on_sigterm can reference scheduler

    def _on_sigterm(signum, frame) -> None:  # noqa: ANN001
        logger.info("Sentinel stopped (SIGTERM)")
        if scheduler_ref:
            scheduler_ref[0].shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    # Create and start the scheduler
    scheduler = BackgroundScheduler()
    scheduler_ref.append(scheduler)

    scheduler.add_job(
        func=run_job,
        trigger=IntervalTrigger(minutes=poll_interval),
        next_run_time=datetime.now(),  # fires immediately on scheduler.start()
        id="sentinel_poll",
        name="Sentinel toner poll",
    )

    scheduler.start()
    logger.info("Scheduler started — polling every %d minute(s)", poll_interval)

    # Main thread: yield to scheduler; handle Ctrl+C for clean shutdown
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Sentinel stopped")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
