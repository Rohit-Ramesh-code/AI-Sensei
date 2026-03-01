"""
adapters/snmp_adapter.py — SNMP adapter for Lexmark XC2235 toner data.

Polls the printer's Printer-MIB (RFC 3805) tables for per-color (CMYK) toner
levels and max capacities. Converts raw SNMP integers to typed QualityFlag
values — raw sentinel integers (-2, -3, etc.) never escape this module.

Usage:
    # Mock mode (no printer needed — for dev/test)
    import os; os.environ["USE_MOCK_SNMP"] = "true"
    from adapters.snmp_adapter import SNMPAdapter

    adapter = SNMPAdapter(host="192.168.1.100", community="public")
    result = adapter.poll()  # Returns PollResult TypedDict

Design notes:
- pysnmp v7 is asyncio-only. The real SNMP path uses asyncio.run() for
  blocking execution. pysnmp-sync-adapter provides an alternative if installed.
- The adapter NEVER raises. Transport failures return a PollResult with
  snmp_error set, so the pipeline always has a valid result to log and route.
- OID index order is NOT hardcoded. The adapter walks prtMarkerSuppliesDescription
  to build a dynamic color->index map at poll() time.

CRITICAL anti-patterns avoided:
- NEVER pass raw sentinel integers (-2, -3) in any TonerReading field.
- NEVER hardcode color index order — walk prtMarkerSuppliesDescription first.
- NEVER open log files in write mode — that is handled in Plan 02.
- NEVER use next(getCmd(...)) — pysnmp v7 is asyncio-only.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from state_types import QualityFlag, PollResult, TonerReading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RFC 3805 Printer-MIB OID bases
# prtMarkerSuppliesDescription: 1.3.6.1.2.1.43.11.1.1.6.1.{index}
# prtMarkerSuppliesMaxCapacity: 1.3.6.1.2.1.43.11.1.1.8.1.{index}
# prtMarkerSuppliesLevel:       1.3.6.1.2.1.43.11.1.1.9.1.{index}
# ---------------------------------------------------------------------------

_OID_DESCRIPTION_BASE = "1.3.6.1.2.1.43.11.1.1.6.1"
_OID_MAX_CAPACITY_BASE = "1.3.6.1.2.1.43.11.1.1.8.1"
_OID_LEVEL_BASE = "1.3.6.1.2.1.43.11.1.1.9.1"

# ---------------------------------------------------------------------------
# Mock fixture — represents a typical Lexmark XC2235 state for offline testing.
# black and cyan are valid; magenta uses sentinel -2 (UNKNOWN); yellow uses -3.
# ---------------------------------------------------------------------------

MOCK_FIXTURE: dict[str, dict[str, int]] = {
    "black":   {"level": 85, "max": 100},   # Valid -> OK, 85.0%
    "cyan":    {"level": 42, "max": 100},   # Valid -> OK, 42.0%
    "magenta": {"level": -2, "max": 100},   # Sentinel -2 -> UNKNOWN
    "yellow":  {"level": -3, "max": 100},   # Sentinel -3 -> BELOW_LOW_THRESHOLD
}


# ---------------------------------------------------------------------------
# classify_snmp_value — sentinel classification (pure function, testable alone)
# ---------------------------------------------------------------------------

def classify_snmp_value(
    raw_level: Optional[int],
    max_capacity: int,
) -> tuple[QualityFlag, Optional[float]]:
    """
    Convert raw SNMP integers to a (QualityFlag, toner_pct | None) pair.

    Classification rules applied in order:
      1. raw_level is None  -> NULL_VALUE, None
      2. raw_level == -2    -> UNKNOWN, None          (RFC 3805 sentinel)
      3. raw_level == -3    -> BELOW_LOW_THRESHOLD, None (RFC 3805 sentinel)
      4. raw_level == -1    -> NOT_SUPPORTED, None    (RFC 3805 sentinel)
      5. max_capacity <= 0  -> UNKNOWN, None          (capacity is itself a sentinel)
      6. not 0 <= raw_level <= max_capacity -> OUT_OF_RANGE, None
      7. else               -> OK, round((raw_level / max_capacity) * 100.0, 1)

    Args:
        raw_level:    Raw integer from prtMarkerSuppliesLevel OID (may be sentinel).
        max_capacity: Raw integer from prtMarkerSuppliesMaxCapacity OID.

    Returns:
        (QualityFlag member, toner_pct float or None)
    """
    if raw_level is None:
        return QualityFlag.NULL_VALUE, None
    if raw_level == -2:
        return QualityFlag.UNKNOWN, None
    if raw_level == -3:
        return QualityFlag.BELOW_LOW_THRESHOLD, None
    if raw_level == -1:
        return QualityFlag.NOT_SUPPORTED, None
    if max_capacity <= 0:
        # max_capacity is itself a sentinel — cannot compute meaningful percentage
        return QualityFlag.UNKNOWN, None
    if not (0 <= raw_level <= max_capacity):
        return QualityFlag.OUT_OF_RANGE, None

    toner_pct = round((raw_level / max_capacity) * 100.0, 1)
    return QualityFlag.OK, toner_pct


# ---------------------------------------------------------------------------
# _build_toner_reading — assemble a TonerReading dict from classified values
# ---------------------------------------------------------------------------

def _build_toner_reading(
    color: str,
    raw_level: Optional[int],
    max_capacity: int,
) -> TonerReading:
    """Build a TonerReading dict using classify_snmp_value for flag and pct."""
    flag, pct = classify_snmp_value(raw_level, max_capacity)
    return TonerReading(
        color=color,
        raw_value=raw_level if raw_level is not None else 0,
        max_capacity=max_capacity,
        toner_pct=pct,
        quality_flag=flag.value,          # Always a plain str — JSON-safe
        data_quality_ok=(flag == QualityFlag.OK),
    )


# ---------------------------------------------------------------------------
# _poll_real_async — async implementation of real SNMP poll
# ---------------------------------------------------------------------------

async def _poll_real_async(
    host: str,
    community: str,
) -> list[TonerReading]:
    """
    Async implementation of real SNMP polling using pysnmp v7 asyncio API.

    Walks prtMarkerSuppliesDescription to build a dynamic color->index map,
    then GETs level and max_capacity for each identified color.

    Returns a list of TonerReading dicts (one per CMYK color found).
    Raises RuntimeError or any pysnmp exception on transport failure.
    """
    from pysnmp.hlapi.v3arch.asyncio import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
    )

    engine = SnmpEngine()
    auth = CommunityData(community, mpModel=1)   # mpModel=1 = SNMPv2c
    transport = await UdpTransportTarget.create((host, 161), timeout=5, retries=1)
    ctx = ContextData()

    # -----------------------------------------------------------------------
    # Step 1: Walk prtMarkerSuppliesDescription to build {color: index} map.
    # Indices 1-8 are checked (XC2235 has 4 CMYK cartridges; 8 is conservative).
    # -----------------------------------------------------------------------
    color_index_map: dict[str, int] = {}

    for idx in range(1, 9):
        oid = f"{_OID_DESCRIPTION_BASE}.{idx}"
        error_indication, error_status, error_index, var_binds = await getCmd(
            engine,
            auth,
            transport,
            ctx,
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication or error_status:
            break  # No more valid indices
        if not var_binds:
            break

        _, value = var_binds[0]
        description = str(value).strip().lower()

        # Normalise common Lexmark description strings to CMYK color names
        for color in ("black", "cyan", "magenta", "yellow"):
            if color in description:
                color_index_map[color] = idx
                break

    if not color_index_map:
        raise RuntimeError(
            f"prtMarkerSuppliesDescription walk returned no recognisable CMYK colors "
            f"from {host}. Check OID access and community string."
        )

    # -----------------------------------------------------------------------
    # Step 2: GET level and max_capacity for each identified color.
    # -----------------------------------------------------------------------
    readings: list[TonerReading] = []

    for color, idx in color_index_map.items():
        level_oid = f"{_OID_LEVEL_BASE}.{idx}"
        max_oid = f"{_OID_MAX_CAPACITY_BASE}.{idx}"

        # GET level
        raw_level: Optional[int] = None
        ei, es, _, vb = await getCmd(
            engine, auth, transport, ctx, ObjectType(ObjectIdentity(level_oid))
        )
        if not ei and not es and vb:
            try:
                raw_level = int(vb[0][1])
            except (ValueError, TypeError):
                pass

        # GET max_capacity
        raw_max: int = -2  # Default to unknown sentinel if GET fails
        ei, es, _, vb = await getCmd(
            engine, auth, transport, ctx, ObjectType(ObjectIdentity(max_oid))
        )
        if not ei and not es and vb:
            try:
                raw_max = int(vb[0][1])
            except (ValueError, TypeError):
                pass

        readings.append(_build_toner_reading(color, raw_level, raw_max))

    return readings


# ---------------------------------------------------------------------------
# SNMPAdapter — public class
# ---------------------------------------------------------------------------

class SNMPAdapter:
    """
    SNMP adapter for polling a Lexmark XC2235 (or compatible Printer-MIB device).

    Supports two modes controlled by the ``use_mock`` constructor argument or
    the ``USE_MOCK_SNMP`` environment variable:

    Mock mode (USE_MOCK_SNMP=true):
        Returns fixture data (black=85%, cyan=42%, magenta=UNKNOWN, yellow=BELOW_LOW)
        without querying any network device. Use for development and testing.

    Real mode (default):
        Polls the live printer at ``host`` via SNMPv2c GET/WALK operations.
        Requires pysnmp v7 installed. Failures are caught and returned as a
        PollResult with snmp_error set — the adapter never raises to callers.

    Args:
        host:      IP address or hostname of the printer.
        community: SNMPv2c community string (default "public" for read-only).
        use_mock:  If True, always use fixture data regardless of env var.
    """

    def __init__(
        self,
        host: str,
        community: str = "public",
        use_mock: bool = False,
    ) -> None:
        self.host = host
        self.community = community
        # Check both the constructor argument and the environment variable
        self.use_mock = use_mock or (
            os.getenv("USE_MOCK_SNMP", "false").lower() == "true"
        )

    def poll(self) -> PollResult:
        """
        Poll the printer for per-color CMYK toner data.

        Returns a PollResult TypedDict. This method NEVER raises — SNMP transport
        failures are caught and surfaced via the ``snmp_error`` field.

        Returns:
            PollResult with readings, timestamp, overall_quality_ok, and optionally
            snmp_error if the transport or protocol failed.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        if self.use_mock:
            return self._poll_mock(timestamp)

        return self._poll_real(timestamp)

    # -----------------------------------------------------------------------
    # Mock poll — returns MOCK_FIXTURE data
    # -----------------------------------------------------------------------

    def _poll_mock(self, timestamp: str) -> PollResult:
        """Build a PollResult from MOCK_FIXTURE using classify_snmp_value."""
        readings: list[TonerReading] = []
        for color, values in MOCK_FIXTURE.items():
            readings.append(
                _build_toner_reading(color, values["level"], values["max"])
            )

        overall_ok = all(r["data_quality_ok"] for r in readings)

        logger.debug(
            "SNMP mock poll: host=%s, overall_ok=%s, readings=%d",
            self.host,
            overall_ok,
            len(readings),
        )

        return PollResult(
            printer_host=self.host,
            timestamp=timestamp,
            readings=readings,
            snmp_error=None,
            overall_quality_ok=overall_ok,
        )

    # -----------------------------------------------------------------------
    # Real poll — uses pysnmp v7 asyncio API via asyncio.run()
    # -----------------------------------------------------------------------

    def _poll_real(self, timestamp: str) -> PollResult:
        """
        Poll the live printer.

        Uses asyncio.run() to execute the async pysnmp v7 API in a blocking
        context. If pysnmp-sync-adapter is available it can replace this, but
        asyncio.run() is fully equivalent and has no additional dependencies.

        Transport or protocol failures are caught and returned in snmp_error.
        """
        try:
            readings = asyncio.run(
                _poll_real_async(self.host, self.community)
            )
            overall_ok = all(r["data_quality_ok"] for r in readings)

            return PollResult(
                printer_host=self.host,
                timestamp=timestamp,
                readings=readings,
                snmp_error=None,
                overall_quality_ok=overall_ok,
            )

        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "SNMP poll failed for host=%s: %s", self.host, error_msg
            )

            # Build error readings for all four CMYK colors
            error_readings: list[TonerReading] = [
                TonerReading(
                    color=color,
                    raw_value=0,
                    max_capacity=0,
                    toner_pct=None,
                    quality_flag=QualityFlag.SNMP_ERROR.value,
                    data_quality_ok=False,
                )
                for color in ("black", "cyan", "magenta", "yellow")
            ]

            return PollResult(
                printer_host=self.host,
                timestamp=timestamp,
                readings=error_readings,
                snmp_error=error_msg,
                overall_quality_ok=False,
            )
