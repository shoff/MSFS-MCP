"""MSFS 2024 MCP server.

Exposes Microsoft Flight Simulator 2024 to MCP clients across three layers:
  1. SimConnect  — official API: SimVars, Events, bundled aircraft state
  2. FSUIPC7     — offset table for values SimConnect doesn't cleanly expose
  3. Raw memory  — escape hatch (read-only by default, writes double-gated)

Run on the Windows host where MSFS runs:  python -m msfs_mcp.server
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import catalog
from .config import CONFIG
from .fsuipc_client import FSUIPC
from .memory_client import MEMORY
from .simconnect_client import SIMCONNECT, LayerUnavailable

logging.basicConfig(
    level=getattr(logging, CONFIG.log_level, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("msfs_mcp")

mcp = FastMCP("msfs2024")


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, default=str, indent=2)


def _err(exc: Exception) -> str:
    return json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}, indent=2)


def _guard(fn):
    """Turn LayerUnavailable / unexpected errors into structured JSON, never a crash."""
    try:
        return _ok(fn())
    except LayerUnavailable as exc:
        return _err(exc)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("Unexpected tool error")
        return _err(exc)


# ======================================================================= #
# Connection / health
# ======================================================================= #
@mcp.tool()
def connection_status() -> str:
    """Report health of all three layers (enabled, imported, connected)."""
    return _ok({
        "simconnect": SIMCONNECT.status(),
        "fsuipc": FSUIPC.status(),
        "memory": MEMORY.status(),
    })


@mcp.tool()
def connect_sim() -> str:
    """Connect the SimConnect layer to a running MSFS. Idempotent."""
    return _guard(SIMCONNECT.connect)


# ======================================================================= #
# Layer 1 — SimConnect: SimVars
# ======================================================================= #
@mcp.tool()
def get_simvar(name: str) -> str:
    """Read any SimVar by its exact SDK name. Supports indices, e.g. 'TURB_ENG_N1:1'."""
    return _guard(lambda: {"name": name, "value": SIMCONNECT.get(name)})


@mcp.tool()
def get_simvars(names: list[str]) -> str:
    """Read several SimVars at once. Returns a name->value map; failures are inline."""
    return _guard(lambda: SIMCONNECT.get_many(names))


@mcp.tool()
def set_simvar(name: str, value: float) -> str:
    """Write a settable SimVar (e.g. AUTOPILOT_HEADING_LOCK_DIR). Check 'settable' in the catalog."""
    return _guard(lambda: (SIMCONNECT.set(name, value), {"name": name, "set_to": value})[1])


@mcp.tool()
def get_aircraft_state() -> str:
    """Bundled snapshot: position, attitude, speeds, engine/fuel, config, autopilot, status."""
    bundle = [
        "PLANE_LATITUDE", "PLANE_LONGITUDE", "PLANE_ALTITUDE", "PLANE_ALT_ABOVE_GROUND",
        "PLANE_HEADING_DEGREES_MAGNETIC", "PLANE_PITCH_DEGREES", "PLANE_BANK_DEGREES",
        "AIRSPEED_INDICATED", "AIRSPEED_TRUE", "GROUND_VELOCITY", "VERTICAL_SPEED",
        "GENERAL_ENG_RPM:1", "TURB_ENG_N1:1", "FUEL_TOTAL_QUANTITY",
        "GEAR_HANDLE_POSITION", "FLAPS_HANDLE_INDEX", "BRAKE_PARKING_POSITION",
        "AUTOPILOT_MASTER", "AUTOPILOT_HEADING_LOCK_DIR", "AUTOPILOT_ALTITUDE_LOCK_VAR",
        "SIM_ON_GROUND", "STALL_WARNING", "G_FORCE", "TITLE",
    ]
    return _guard(lambda: SIMCONNECT.get_many(bundle))


# ======================================================================= #
# Layer 1 — SimConnect: Events (controls)
# ======================================================================= #
@mcp.tool()
def trigger_event(event: str, value: int | None = None) -> str:
    """Fire a SimConnect Event (a control/command). Pass 'value' for events that take a parameter.

    Examples: trigger_event('GEAR_TOGGLE'); trigger_event('HEADING_BUG_SET', 270).
    """
    return _guard(lambda: (SIMCONNECT.trigger(event, value), {"event": event, "value": value})[1])


# ---- Autopilot convenience wrappers (thin sugar over events/simvars) ---- #
@mcp.tool()
def autopilot_set_heading(heading_deg: int) -> str:
    """Set the autopilot heading bug (0-359 degrees)."""
    return _guard(lambda: (SIMCONNECT.trigger("HEADING_BUG_SET", heading_deg % 360),
                           {"heading_deg": heading_deg % 360})[1])


@mcp.tool()
def autopilot_set_altitude(altitude_ft: int) -> str:
    """Set the autopilot target altitude in feet."""
    return _guard(lambda: (SIMCONNECT.trigger("AP_ALT_VAR_SET_ENGLISH", altitude_ft),
                           {"altitude_ft": altitude_ft})[1])


@mcp.tool()
def autopilot_set_vertical_speed(fpm: int) -> str:
    """Set the autopilot target vertical speed in feet per minute (negative = descend)."""
    return _guard(lambda: (SIMCONNECT.trigger("AP_VS_VAR_SET_ENGLISH", fpm), {"fpm": fpm})[1])


@mcp.tool()
def autopilot_toggle_master() -> str:
    """Toggle the autopilot master on/off."""
    return _guard(lambda: (SIMCONNECT.trigger("AP_MASTER"), {"toggled": "AP_MASTER"})[1])


# ======================================================================= #
# Discovery — the catalog
# ======================================================================= #
@mcp.tool()
def list_simvars(query: str = "", category: str = "") -> str:
    """Search the SimVar catalog by keyword and/or category. Empty args list everything.

    Categories: position, attitude, speed, engine, fuel, config, autopilot,
    systems, environment, status.
    """
    results = catalog.search_simvars(query, category)
    return _ok({
        "count": len(results),
        "categories": catalog.SIMVAR_CATEGORIES,
        "simvars": [s.__dict__ for s in results],
    })


@mcp.tool()
def list_events(query: str = "", category: str = "") -> str:
    """Search the Event catalog by keyword and/or category. Empty args list everything.

    Categories: engine, config, autopilot, controls, systems, sim.
    """
    results = catalog.search_events(query, category)
    return _ok({
        "count": len(results),
        "categories": catalog.EVENT_CATEGORIES,
        "events": [e.__dict__ for e in results],
    })


# ======================================================================= #
# Layer 2 — FSUIPC offsets
# ======================================================================= #
@mcp.tool()
def fsuipc_status() -> str:
    """FSUIPC layer health plus the list of built-in known offset keys."""
    return _ok(FSUIPC.status())


@mcp.tool()
def fsuipc_read_offset(offset_hex: str, type_code: str, length: int | None = None) -> str:
    """Read a raw FSUIPC offset. offset_hex like '0x0560'; type_code one of b/B/h/H/d/u/l/L/f/s.

    For strings use type_code='s' and pass a length.
    """
    return _guard(lambda: {
        "offset": offset_hex,
        "value": FSUIPC.read(int(offset_hex, 16), type_code, length),
    })


@mcp.tool()
def fsuipc_read_known(key: str) -> str:
    """Read one of the built-in known offsets by key (see fsuipc_status.known_offsets)."""
    return _guard(lambda: {"key": key, "value": FSUIPC.read_known(key)})


@mcp.tool()
def fsuipc_write_offset(offset_hex: str, type_code: str, value: float) -> str:
    """Write a raw FSUIPC offset. Use deliberately — offsets are global sim state."""
    return _guard(lambda: (FSUIPC.write(int(offset_hex, 16), type_code, value),
                           {"offset": offset_hex, "set_to": value})[1])


# ======================================================================= #
# Layer 3 — raw memory (escape hatch)
# ======================================================================= #
@mcp.tool()
def memory_status() -> str:
    """Raw-memory layer health (enabled flag, attach state, target process/pid)."""
    return _ok(MEMORY.status())


@mcp.tool()
def memory_attach(process_name: str | None = None) -> str:
    """Attach to the MSFS process for raw reads. Off unless MSFS_ENABLE_MEMORY=true."""
    return _guard(lambda: MEMORY.attach(process_name))


@mcp.tool()
def memory_module_base(module_name: str | None = None) -> str:
    """Return the base address of a loaded module (defaults to the main executable)."""
    return _guard(lambda: {"module": module_name or CONFIG.process_name,
                           "base": hex(MEMORY.module_base(module_name))})


@mcp.tool()
def memory_read(address_hex: str, type_name: str) -> str:
    """Read a typed value at an absolute address. type_name: int32/uint32/int64/uint64/float/double/byte/ubyte."""
    return _guard(lambda: {"address": address_hex,
                           "value": MEMORY.read(int(address_hex, 16), type_name)})


@mcp.tool()
def memory_read_pointer_chain(base_hex: str, offsets_hex: list[str], type_name: str) -> str:
    """Resolve a pointer chain from a base address, then read the typed value at the end."""
    def run() -> dict[str, Any]:
        base = int(base_hex, 16)
        offs = [int(o, 16) for o in offsets_hex]
        addr = MEMORY.resolve_pointer_chain(base, offs)
        return {"resolved_address": hex(addr), "value": MEMORY.read(addr, type_name)}
    return _guard(run)


@mcp.tool()
def memory_write(address_hex: str, type_name: str, value: float, allow_write: bool = False) -> str:
    """Write to an absolute address. Double-gated: needs MSFS_ENABLE_MEMORY=true AND allow_write=true."""
    return _guard(lambda: (MEMORY.write(int(address_hex, 16), type_name, value, allow_write),
                           {"address": address_hex, "set_to": value})[1])


# ======================================================================= #
# Resources — live telemetry as readable URIs
# ======================================================================= #
@mcp.resource("msfs://telemetry/state")
def telemetry_state() -> str:
    """Live aircraft-state snapshot as a resource (mirrors get_aircraft_state)."""
    return get_aircraft_state()


@mcp.resource("msfs://catalog/simvars")
def resource_simvars() -> str:
    """The full SimVar catalog as a resource."""
    return list_simvars()


@mcp.resource("msfs://catalog/events")
def resource_events() -> str:
    """The full Event catalog as a resource."""
    return list_events()


# ======================================================================= #
# Prompts — ready-made operator workflows
# ======================================================================= #
@mcp.prompt()
def preflight_briefing() -> str:
    """Generate a preflight briefing from current sim state."""
    return (
        "Call get_aircraft_state and connection_status, then give me a concise preflight "
        "briefing: aircraft, position, fuel, configuration (gear/flaps/brakes), and whether "
        "we're on the ground and ready. Flag anything unusual (stall/overspeed warnings, low fuel)."
    )


@mcp.prompt()
def fly_to_heading_altitude(heading: str, altitude: str) -> str:
    """Set up the autopilot to fly a heading and altitude."""
    return (
        f"Engage the autopilot for heading {heading}° and altitude {altitude} ft: confirm AP master, "
        f"set the heading bug, set target altitude, then read back AUTOPILOT_* SimVars to verify."
    )


def main() -> None:
    """Console entry point (stdio transport)."""
    log.info("Starting MSFS 2024 MCP server (stdio). Layers: SC=%s FSUIPC=%s MEM=%s",
             CONFIG.enable_simconnect, CONFIG.enable_fsuipc, CONFIG.enable_memory)
    mcp.run()


if __name__ == "__main__":
    main()
