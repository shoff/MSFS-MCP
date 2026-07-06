"""Canonical registry of bindable MSFS settings — one source of truth.

Every place that reasons about a plan's ``msfs_setting`` string consumes this:
  - msfs_profiles.resolve_writes  -> which MSFS actions to write, and in what order
  - binding_check.spec_for        -> which SimVar proves the binding live
  - the Learn flow                -> how many physical inputs a control needs and
                                     what to prompt for each ('FLAPS UP', 'FLAPS DOWN')

Previously this knowledge was split across three tables matched by fragile
substring, which drifted (e.g. 'TOGGLE CARBURETOR HEAT' vs '...(ANTI-ICE)').
Keeping it in one place makes writer, verifier and Learn agree by construction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingSpec:
    canonical: str                       # stable id, e.g. "flaps_notch"
    match: tuple[str, ...]               # UPPER substrings of msfs_setting that map here
    kind: str                            # "axis" | "button"
    actions: tuple[str, ...] = ()        # MSFS action names, in semantic order
    slots: tuple[str, ...] = ()          # Learn-mode prompt per button (parallel to actions)
    check_var: str | None = None         # SimVar that reacts, for live verify
    check_threshold: float = 0.5         # min change from baseline that counts
    check_hint: str = ""                 # what to tell the pilot during verify

    @property
    def arity(self) -> int:
        """How many physical inputs this control needs (1 for axes/toggles)."""
        return max(1, len(self.actions)) if self.kind == "button" else 1


# Order matters only for display; matching picks the first spec whose any-substring
# is contained in the (uppercased) msfs_setting.
REGISTRY: tuple[SettingSpec, ...] = (
    # ---- axes ----
    SettingSpec("aileron_axis", ("AILERONS AXIS",), "axis",
                ("KEY_AXIS_AILERONS_SET",), ("roll axis",),
                "AILERON_POSITION", 0.10, "roll the yoke left and right"),
    SettingSpec("elevator_axis", ("ELEVATOR AXIS",), "axis",
                ("KEY_AXIS_ELEVATOR_SET",), ("pitch axis",),
                "ELEVATOR_POSITION", 0.10, "push and pull the yoke"),
    SettingSpec("rudder_axis", ("RUDDER AXIS",), "axis",
                ("KEY_AXIS_RUDDER_SET",), ("rudder axis",),
                "RUDDER_POSITION", 0.10, "press each pedal"),
    SettingSpec("throttle_axis", ("THROTTLE AXIS",), "axis",
                ("KEY_AXIS_THROTTLE_SET",), ("throttle axis",),
                "GENERAL_ENG_THROTTLE_LEVER_POSITION:1", 5.0, "run the lever through its travel"),
    SettingSpec("mixture_axis", ("MIXTURE AXIS",), "axis",
                ("KEY_AXIS_MIXTURE_SET",), ("mixture axis",),
                "GENERAL_ENG_MIXTURE_LEVER_POSITION:1", 5.0, "run the lever through its travel"),
    SettingSpec("left_brake_axis", ("LEFT BRAKE AXIS",), "axis",
                ("KEY_AXIS_LEFT_BRAKE_SET",), ("left brake axis",),
                "BRAKE_LEFT_POSITION", 0.10, "press the left toe brake"),
    SettingSpec("right_brake_axis", ("RIGHT BRAKE AXIS",), "axis",
                ("KEY_AXIS_RIGHT_BRAKE_SET",), ("right brake axis",),
                "BRAKE_RIGHT_POSITION", 0.10, "press the right toe brake"),
    # ---- single-action buttons/toggles ----
    SettingSpec("master_battery", ("TOGGLE MASTER BATTERY",), "button",
                ("KEY_TOGGLE_MASTER_BATTERY",), ("battery switch",),
                "ELECTRICAL_MASTER_BATTERY", 0.5, "flip it once"),
    SettingSpec("master_alternator", ("TOGGLE MASTER ALTERNATOR",), "button",
                ("KEY_TOGGLE_MASTER_ALTERNATOR",), ("alternator switch",),
                "GENERAL_ENG_MASTER_ALTERNATOR:1", 0.5, "flip it once"),
    SettingSpec("avionics_master", ("TOGGLE AVIONICS MASTER",), "button",
                ("KEY_TOGGLE_AVIONICS_MASTER",), ("avionics switch",),
                "AVIONICS_MASTER_SWITCH", 0.5, "flip it once (battery must be on)"),
    SettingSpec("beacon", ("TOGGLE BEACON LIGHTS",), "button",
                ("KEY_TOGGLE_BEACON_LIGHTS",), ("beacon switch",),
                "LIGHT_BEACON", 0.5, "flip it once"),
    SettingSpec("landing_light", ("LANDING LIGHTS TOGGLE",), "button",
                ("KEY_LANDING_LIGHTS_TOGGLE",), ("landing light switch",),
                "LIGHT_LANDING", 0.5, "flip it once"),
    SettingSpec("taxi_light", ("TOGGLE TAXI LIGHTS",), "button",
                ("KEY_TOGGLE_TAXI_LIGHTS",), ("taxi light switch",),
                "LIGHT_TAXI", 0.5, "flip it once"),
    SettingSpec("nav_light", ("TOGGLE NAV LIGHTS",), "button",
                ("KEY_TOGGLE_NAV_LIGHTS",), ("nav light switch",),
                "LIGHT_NAV", 0.5, "flip it once"),
    SettingSpec("strobe", ("TOGGLE STROBES",), "button",
                ("KEY_STROBES_TOGGLE",), ("strobe switch",),
                "LIGHT_STROBE", 0.5, "flip it once"),
    SettingSpec("fuel_pump", ("TOGGLE ELECTRIC FUEL PUMP",), "button",
                ("KEY_TOGGLE_ELECT_FUEL_PUMP",), ("fuel pump switch",),
                "GENERAL_ENG_FUEL_PUMP_SWITCH:1", 0.5, "flip it once"),
    SettingSpec("pitot_heat", ("TOGGLE PITOT HEAT",), "button",
                ("KEY_PITOT_HEAT_TOGGLE",), ("pitot heat switch",),
                "PITOT_HEAT", 0.5, "flip it once"),
    SettingSpec("carb_heat", ("TOGGLE CARBURETOR HEAT",), "button",
                ("KEY_ANTI_ICE_TOGGLE_ENG1",), ("carb heat switch",),
                "GENERAL_ENG_ANTI_ICE_POSITION:1", 0.5, "flip it once"),
    SettingSpec("ap_disconnect", ("AUTOPILOT OFF", "DISCONNECT"), "button",
                ("KEY_AUTOPILOT_OFF",), ("AP disconnect button",),
                "AUTOPILOT_MASTER", 0.5, "engage the AP in the cockpit first, then press"),
    SettingSpec("ap_master", ("TOGGLE AUTOPILOT MASTER",), "button",
                ("KEY_AP_MASTER",), ("AP master button",),
                "AUTOPILOT_MASTER", 0.5, "press it once"),
    SettingSpec("ap_hdg", ("TOGGLE AUTOPILOT HEADING HOLD",), "button",
                ("KEY_AP_HDG_HOLD",), ("HDG button",),
                "AUTOPILOT_HEADING_LOCK", 0.5, "press it once"),
    SettingSpec("ap_nav", ("TOGGLE AUTOPILOT NAV1 HOLD",), "button",
                ("KEY_AP_NAV1_HOLD",), ("NAV button",),
                "AUTOPILOT_NAV1_LOCK", 0.5, "press it once"),
    SettingSpec("ap_apr", ("TOGGLE AUTOPILOT APPROACH HOLD",), "button",
                ("KEY_AP_APR_HOLD",), ("APR button",),
                "AUTOPILOT_APPROACH_HOLD", 0.5, "press it once"),
    SettingSpec("ap_rev", ("TOGGLE AUTOPILOT REVERSE HOLD",), "button",
                ("KEY_AP_BC_HOLD",), ("REV button",),
                "AUTOPILOT_BACKCOURSE_HOLD", 0.5, "press it once"),
    SettingSpec("ap_alt", ("TOGGLE AUTOPILOT ALTITUDE HOLD",), "button",
                ("KEY_AP_ALT_HOLD",), ("ALT button",),
                "AUTOPILOT_ALTITUDE_LOCK", 0.5, "press it once"),
    SettingSpec("ap_vs", ("TOGGLE AUTOPILOT VS HOLD",), "button",
                ("KEY_AP_VS_HOLD",), ("VS button",),
                "AUTOPILOT_VERTICAL_HOLD", 0.5, "press it once"),
    SettingSpec("toga", ("AUTO THROTTLE GO AROUND", "TOGA"), "button",
                ("KEY_AUTO_THROTTLE_TO_GA",), ("GA button",),
                None, 0.5, "press it once (no SimVar to confirm — check by eye)"),
    SettingSpec("heading_bug", ("HEADING BUG INC/DEC",), "button",
                ("HEADING_BUG_INC", "HEADING_BUG_DEC"), ("bug LEFT/-", "bug RIGHT/+"),
                "AUTOPILOT_HEADING_LOCK_DIR", 0.9, "selector on HDG, twist the knob"),
    # ---- multi-action controls (ordered!) ----
    SettingSpec("elev_trim", ("ELEVATOR TRIM UP / DOWN", "ELEVATOR TRIM AXIS"), "button",
                ("KEY_ELEV_TRIM_UP", "KEY_ELEV_TRIM_DN"),
                ("trim UP (nose down)", "trim DOWN (nose up)"),
                "ELEVATOR_TRIM_PCT", 0.01, "click several times in one direction"),
    SettingSpec("flaps_notch", ("INCREASE / DECREASE FLAPS",), "button",
                ("KEY_FLAPS_INCR", "KEY_FLAPS_DECR"),
                ("flaps DOWN one notch", "flaps UP one notch"),
                "FLAPS_HANDLE_INDEX", 0.5, "move the flap lever one notch"),
    SettingSpec("magneto", ("MAGNETO OFF",), "button",
                ("KEY_MAGNETO_OFF", "KEY_MAGNETO_RIGHT", "KEY_MAGNETO_LEFT",
                 "KEY_MAGNETO_BOTH", "KEY_MAGNETO_START"),
                ("rotate to OFF", "rotate to R", "rotate to L", "rotate to BOTH", "rotate to START"),
                "RECIP_ENG_LEFT_MAGNETO:1", 0.5, "rotate BOTH -> L and back"),
)

_BY_CANONICAL = {s.canonical: s for s in REGISTRY}


def spec_for_setting(msfs_setting: str) -> SettingSpec | None:
    """Match a plan's free-text msfs_setting to a canonical spec, or None."""
    setting = (msfs_setting or "").strip().upper()
    if not setting or setting in ("—", "-"):
        return None
    for spec in REGISTRY:
        if any(m in setting for m in spec.match):
            return spec
    return None


def spec_by_canonical(canonical: str) -> SettingSpec | None:
    return _BY_CANONICAL.get(canonical)
