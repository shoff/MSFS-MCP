"""Curated catalog of MSFS SimVars and Events.

This is *not* exhaustive — the SimConnect SDK exposes thousands of variables.
It's a high-value, grouped subset so an LLM can discover what's available and
build bundles, while the generic ``get_simvar`` / ``trigger_event`` tools can
still reach anything by name. Names follow the official SDK exactly.

References:
  - SimVars:  https://docs.flightsimulator.com/html/Programming_Tools/SimVars/Simulation_Variables.htm
  - Events:   https://docs.flightsimulator.com/html/Programming_Tools/Event_IDs/Event_IDs.htm
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimVarSpec:
    name: str          # SDK SimVar name (use this with get/set)
    units: str         # default units for read/write
    settable: bool     # whether the sim accepts writes
    category: str
    description: str


@dataclass(frozen=True)
class EventSpec:
    name: str          # SDK Event ID (use this with trigger_event)
    category: str
    takes_value: bool  # whether the event consumes a numeric parameter
    description: str


# --------------------------------------------------------------------------- #
# SimVars — readable (and many settable) simulation state.
# --------------------------------------------------------------------------- #
SIMVARS: list[SimVarSpec] = [
    # --- Position / geo ---
    SimVarSpec("PLANE_LATITUDE", "degrees", True, "position", "Aircraft latitude"),
    SimVarSpec("PLANE_LONGITUDE", "degrees", True, "position", "Aircraft longitude"),
    SimVarSpec("PLANE_ALTITUDE", "feet", True, "position", "Altitude above MSL"),
    SimVarSpec("PLANE_ALT_ABOVE_GROUND", "feet", False, "position", "Altitude above ground (AGL)"),
    SimVarSpec("GROUND_ALTITUDE", "meters", False, "position", "Ground elevation under aircraft"),
    # --- Attitude ---
    SimVarSpec("PLANE_PITCH_DEGREES", "degrees", True, "attitude", "Pitch (negative = nose up)"),
    SimVarSpec("PLANE_BANK_DEGREES", "degrees", True, "attitude", "Bank angle"),
    SimVarSpec("PLANE_HEADING_DEGREES_TRUE", "degrees", True, "attitude", "True heading"),
    SimVarSpec("PLANE_HEADING_DEGREES_MAGNETIC", "degrees", True, "attitude", "Magnetic heading"),
    # --- Speeds ---
    SimVarSpec("AIRSPEED_INDICATED", "knots", False, "speed", "Indicated airspeed (IAS)"),
    SimVarSpec("AIRSPEED_TRUE", "knots", False, "speed", "True airspeed (TAS)"),
    SimVarSpec("GROUND_VELOCITY", "knots", False, "speed", "Groundspeed"),
    SimVarSpec("VERTICAL_SPEED", "feet per minute", False, "speed", "Vertical speed"),
    SimVarSpec("AIRSPEED_MACH", "mach", False, "speed", "Mach number"),
    # --- Engines (index 1; SimConnect supports :1.. suffixes) ---
    SimVarSpec("GENERAL_ENG_RPM:1", "rpm", False, "engine", "Engine 1 RPM"),
    SimVarSpec("GENERAL_ENG_THROTTLE_LEVER_POSITION:1", "percent", True, "engine", "Engine 1 throttle %"),
    SimVarSpec("TURB_ENG_N1:1", "percent", False, "engine", "Turbine engine 1 N1"),
    SimVarSpec("TURB_ENG_N2:1", "percent", False, "engine", "Turbine engine 1 N2"),
    SimVarSpec("ENG_COMBUSTION:1", "bool", False, "engine", "Engine 1 running"),
    SimVarSpec("NUMBER_OF_ENGINES", "number", False, "engine", "Engine count"),
    # --- Fuel ---
    SimVarSpec("FUEL_TOTAL_QUANTITY", "gallons", False, "fuel", "Total fuel onboard"),
    SimVarSpec("FUEL_TOTAL_CAPACITY", "gallons", False, "fuel", "Total fuel capacity"),
    SimVarSpec("FUEL_TOTAL_QUANTITY_WEIGHT", "pounds", False, "fuel", "Total fuel weight"),
    # --- Gear / flaps / brakes / spoilers ---
    SimVarSpec("GEAR_HANDLE_POSITION", "bool", True, "config", "Gear handle (1=down)"),
    SimVarSpec("GEAR_TOTAL_PCT_EXTENDED", "percent", False, "config", "Gear extension %"),
    SimVarSpec("FLAPS_HANDLE_INDEX", "number", True, "config", "Flaps detent index"),
    SimVarSpec("FLAPS_HANDLE_PERCENT", "percent", False, "config", "Flaps handle %"),
    SimVarSpec("BRAKE_PARKING_POSITION", "bool", True, "config", "Parking brake (1=set)"),
    SimVarSpec("SPOILERS_HANDLE_POSITION", "percent", True, "config", "Spoiler handle %"),
    # --- Autopilot ---
    SimVarSpec("AUTOPILOT_MASTER", "bool", False, "autopilot", "AP master engaged"),
    SimVarSpec("AUTOPILOT_HEADING_LOCK_DIR", "degrees", True, "autopilot", "AP heading bug"),
    SimVarSpec("AUTOPILOT_ALTITUDE_LOCK_VAR", "feet", True, "autopilot", "AP target altitude"),
    SimVarSpec("AUTOPILOT_AIRSPEED_HOLD_VAR", "knots", True, "autopilot", "AP target airspeed"),
    SimVarSpec("AUTOPILOT_VERTICAL_HOLD_VAR", "feet per minute", True, "autopilot", "AP target VS"),
    SimVarSpec("AUTOPILOT_HEADING_LOCK", "bool", False, "autopilot", "AP HDG hold mode"),
    SimVarSpec("AUTOPILOT_ALTITUDE_LOCK", "bool", False, "autopilot", "AP ALT hold mode"),
    # --- Electrical / systems ---
    SimVarSpec("ELECTRICAL_MASTER_BATTERY", "bool", True, "systems", "Master battery"),
    SimVarSpec("LIGHT_LANDING", "bool", True, "systems", "Landing lights"),
    SimVarSpec("LIGHT_BEACON", "bool", True, "systems", "Beacon light"),
    SimVarSpec("LIGHT_NAV", "bool", True, "systems", "Nav lights"),
    SimVarSpec("LIGHT_STROBE", "bool", True, "systems", "Strobe lights"),
    # --- Environment / time ---
    SimVarSpec("AMBIENT_WIND_VELOCITY", "knots", False, "environment", "Wind speed at aircraft"),
    SimVarSpec("AMBIENT_WIND_DIRECTION", "degrees", False, "environment", "Wind direction (true)"),
    SimVarSpec("AMBIENT_TEMPERATURE", "celsius", False, "environment", "Outside air temperature"),
    SimVarSpec("BAROMETER_PRESSURE", "millibars", False, "environment", "Barometric pressure"),
    SimVarSpec("SEA_LEVEL_PRESSURE", "millibars", False, "environment", "QNH sea-level pressure"),
    SimVarSpec("ZULU_TIME", "seconds", False, "environment", "Sim UTC time (sec since midnight)"),
    SimVarSpec("SIMULATION_RATE", "number", False, "environment", "Sim time multiplier"),
    # --- Status flags ---
    SimVarSpec("SIM_ON_GROUND", "bool", False, "status", "Aircraft on the ground"),
    SimVarSpec("STALL_WARNING", "bool", False, "status", "Stall warning active"),
    SimVarSpec("OVERSPEED_WARNING", "bool", False, "status", "Overspeed warning active"),
    SimVarSpec("G_FORCE", "gforce", False, "status", "Current G load"),
    SimVarSpec("TITLE", "string", False, "status", "Loaded aircraft title"),
]


# --------------------------------------------------------------------------- #
# Events — controls / commands you can trigger.
# --------------------------------------------------------------------------- #
EVENTS: list[EventSpec] = [
    # --- Engine / throttle ---
    EventSpec("THROTTLE_SET", "engine", True, "Set all throttles (0..16383)"),
    EventSpec("THROTTLE_FULL", "engine", False, "Throttles to full"),
    EventSpec("THROTTLE_CUT", "engine", False, "Throttles to idle/cut"),
    EventSpec("ENGINE_AUTO_START", "engine", False, "Auto-start engines (Ctrl+E)"),
    EventSpec("ENGINE_AUTO_SHUTDOWN", "engine", False, "Auto-shutdown engines"),
    EventSpec("MIXTURE_SET", "engine", True, "Set mixture (0..16383)"),
    # --- Gear / flaps / brakes / spoilers ---
    EventSpec("GEAR_TOGGLE", "config", False, "Toggle landing gear"),
    EventSpec("GEAR_UP", "config", False, "Gear up"),
    EventSpec("GEAR_DOWN", "config", False, "Gear down"),
    EventSpec("FLAPS_UP", "config", False, "Flaps fully up"),
    EventSpec("FLAPS_DOWN", "config", False, "Flaps fully down"),
    EventSpec("FLAPS_INCR", "config", False, "Flaps one notch down"),
    EventSpec("FLAPS_DECR", "config", False, "Flaps one notch up"),
    EventSpec("PARKING_BRAKES", "config", False, "Toggle parking brake"),
    EventSpec("BRAKES", "config", False, "Apply wheel brakes"),
    EventSpec("SPOILERS_TOGGLE", "config", False, "Toggle spoilers"),
    EventSpec("SPOILERS_ARM_TOGGLE", "config", False, "Toggle spoiler auto-arm"),
    # --- Autopilot ---
    EventSpec("AP_MASTER", "autopilot", False, "Toggle AP master"),
    EventSpec("AP_HDG_HOLD", "autopilot", False, "Toggle heading hold"),
    EventSpec("AP_ALT_HOLD", "autopilot", False, "Toggle altitude hold"),
    EventSpec("AP_NAV1_HOLD", "autopilot", False, "Toggle NAV hold"),
    EventSpec("AP_APR_HOLD", "autopilot", False, "Toggle approach mode"),
    EventSpec("AP_VS_HOLD", "autopilot", False, "Toggle vertical-speed hold"),
    EventSpec("AP_SPD_VAR_SET", "autopilot", True, "Set AP airspeed reference"),
    EventSpec("HEADING_BUG_SET", "autopilot", True, "Set heading bug (degrees)"),
    EventSpec("AP_ALT_VAR_SET_ENGLISH", "autopilot", True, "Set AP altitude (feet)"),
    EventSpec("AP_VS_VAR_SET_ENGLISH", "autopilot", True, "Set AP vertical speed (fpm)"),
    EventSpec("AP_PANEL_HEADING_HOLD", "autopilot", False, "Hold current heading"),
    # --- Flight controls (trim/surfaces) ---
    EventSpec("ELEV_TRIM_UP", "controls", False, "Elevator trim up"),
    EventSpec("ELEV_TRIM_DN", "controls", False, "Elevator trim down"),
    EventSpec("AILERON_SET", "controls", True, "Set ailerons (-16383..16383)"),
    EventSpec("ELEVATOR_SET", "controls", True, "Set elevator (-16383..16383)"),
    EventSpec("RUDDER_SET", "controls", True, "Set rudder (-16383..16383)"),
    # --- Lights / electrical ---
    EventSpec("LANDING_LIGHTS_TOGGLE", "systems", False, "Toggle landing lights"),
    EventSpec("TOGGLE_BEACON_LIGHTS", "systems", False, "Toggle beacon"),
    EventSpec("TOGGLE_NAV_LIGHTS", "systems", False, "Toggle nav lights"),
    EventSpec("STROBES_TOGGLE", "systems", False, "Toggle strobes"),
    EventSpec("TOGGLE_MASTER_BATTERY", "systems", False, "Toggle master battery"),
    # --- Sim meta ---
    EventSpec("SIM_RATE_INCR", "sim", False, "Increase sim rate"),
    EventSpec("SIM_RATE_DECR", "sim", False, "Decrease sim rate"),
    EventSpec("PAUSE_TOGGLE", "sim", False, "Toggle pause"),
    EventSpec("SITUATION_RESET", "sim", False, "Reset flight"),
]


def search_simvars(query: str = "", category: str = "") -> list[SimVarSpec]:
    q, c = query.lower(), category.lower()
    return [
        s for s in SIMVARS
        if (not q or q in s.name.lower() or q in s.description.lower())
        and (not c or c == s.category.lower())
    ]


def search_events(query: str = "", category: str = "") -> list[EventSpec]:
    q, c = query.lower(), category.lower()
    return [
        e for e in EVENTS
        if (not q or q in e.name.lower() or q in e.description.lower())
        and (not c or c == e.category.lower())
    ]


SIMVAR_CATEGORIES = sorted({s.category for s in SIMVARS})
EVENT_CATEGORIES = sorted({e.category for e in EVENTS})
