"""Standalone smoke test — run on the Windows host with MSFS loaded into a flight.

    python scripts/smoke_test.py

Prints layer health, then (if SimConnect connects) a live aircraft-state snapshot.
Exercises the client layers directly, without going through the MCP transport.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from msfs_mcp.fsuipc_client import FSUIPC  # noqa: E402
from msfs_mcp.memory_client import MEMORY  # noqa: E402
from msfs_mcp.simconnect_client import SIMCONNECT, LayerUnavailable  # noqa: E402


def banner(t: str) -> None:
    print(f"\n=== {t} ===")


def main() -> int:
    banner("Layer health")
    print(json.dumps({
        "simconnect": SIMCONNECT.status(),
        "fsuipc": FSUIPC.status(),
        "memory": MEMORY.status(),
    }, indent=2, default=str))

    banner("SimConnect connect")
    try:
        SIMCONNECT.connect()
        print("Connected.")
    except LayerUnavailable as exc:
        print(f"SimConnect unavailable: {exc}")
        print("\n(If you're not on the Windows host with MSFS running, that's expected.)")
        return 0

    banner("Live aircraft state")
    state = SIMCONNECT.get_many([
        "TITLE", "PLANE_LATITUDE", "PLANE_LONGITUDE", "PLANE_ALTITUDE",
        "AIRSPEED_INDICATED", "PLANE_HEADING_DEGREES_MAGNETIC", "SIM_ON_GROUND",
    ])
    print(json.dumps(state, indent=2, default=str))

    banner("Event round-trip (toggle nav lights twice)")
    try:
        SIMCONNECT.trigger("TOGGLE_NAV_LIGHTS")
        SIMCONNECT.trigger("TOGGLE_NAV_LIGHTS")
        print("Nav-light toggle events fired.")
    except LayerUnavailable as exc:
        print(f"Event failed: {exc}")

    print("\nSmoke test complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
