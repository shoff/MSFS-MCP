"""Which SimVar proves each binding works, and the per-device test list.

A binding passes live verification when BOTH sides are observed:
  hardware — the mapped physical input moved (InputMonitor)
  sim      — the expected SimVar changed from its baseline (SimLink)

Hardware moving without the SimVar reacting = the MSFS binding is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CheckSpec:
    var: str            # SimVar expected to react
    threshold: float    # minimum change from baseline that counts
    hint: str = ""      # extra instruction shown to the pilot


# Keyed by (substring of) the plan's msfs_setting, like msfs_profiles.BUTTON_ACTIONS.
SPECS: dict[str, CheckSpec] = {
    "AILERONS AXIS": CheckSpec("AILERON_POSITION", 0.10, "roll the yoke left and right"),
    "ELEVATOR AXIS": CheckSpec("ELEVATOR_POSITION", 0.10, "push and pull the yoke"),
    "RUDDER AXIS": CheckSpec("RUDDER_POSITION", 0.10, "press each pedal"),
    "THROTTLE AXIS": CheckSpec("GENERAL_ENG_THROTTLE_LEVER_POSITION:1", 5.0, "run the lever through its travel"),
    "MIXTURE AXIS": CheckSpec("GENERAL_ENG_MIXTURE_LEVER_POSITION:1", 5.0, "run the lever through its travel"),
    "LEFT BRAKE AXIS": CheckSpec("BRAKE_LEFT_POSITION", 0.10, "press the left toe brake"),
    "RIGHT BRAKE AXIS": CheckSpec("BRAKE_RIGHT_POSITION", 0.10, "press the right toe brake"),
    "TOGGLE MASTER BATTERY": CheckSpec("ELECTRICAL_MASTER_BATTERY", 0.5, "flip it once"),
    "TOGGLE MASTER ALTERNATOR": CheckSpec("GENERAL_ENG_MASTER_ALTERNATOR:1", 0.5, "flip it once"),
    "TOGGLE AVIONICS MASTER 1": CheckSpec("AVIONICS_MASTER_SWITCH", 0.5, "flip it once (battery must be on)"),
    "TOGGLE BEACON LIGHTS": CheckSpec("LIGHT_BEACON", 0.5, "flip it once"),
    "LANDING LIGHTS TOGGLE": CheckSpec("LIGHT_LANDING", 0.5, "flip it once"),
    "TOGGLE TAXI LIGHTS": CheckSpec("LIGHT_TAXI", 0.5, "flip it once"),
    "TOGGLE NAV LIGHTS": CheckSpec("LIGHT_NAV", 0.5, "flip it once"),
    "TOGGLE STROBES": CheckSpec("LIGHT_STROBE", 0.5, "flip it once"),
    "TOGGLE ELECTRIC FUEL PUMP": CheckSpec("GENERAL_ENG_FUEL_PUMP_SWITCH:1", 0.5, "flip it once"),
    "TOGGLE PITOT HEAT": CheckSpec("PITOT_HEAT", 0.5, "flip it once"),
    "TOGGLE CARBURETOR HEAT": CheckSpec("GENERAL_ENG_ANTI_ICE_POSITION:1", 0.5, "flip it once"),
    "AUTOPILOT OFF / DISCONNECT": CheckSpec("AUTOPILOT_MASTER", 0.5, "engage the AP in the cockpit first, then press"),
    "TOGGLE AUTOPILOT MASTER": CheckSpec("AUTOPILOT_MASTER", 0.5, "press it once"),
    "TOGGLE AUTOPILOT HEADING HOLD": CheckSpec("AUTOPILOT_HEADING_LOCK", 0.5, "press it once"),
    "TOGGLE AUTOPILOT NAV1 HOLD": CheckSpec("AUTOPILOT_NAV1_LOCK", 0.5, "press it once"),
    "TOGGLE AUTOPILOT APPROACH HOLD": CheckSpec("AUTOPILOT_APPROACH_HOLD", 0.5, "press it once"),
    "TOGGLE AUTOPILOT REVERSE HOLD": CheckSpec("AUTOPILOT_BACKCOURSE_HOLD", 0.5, "press it once"),
    "TOGGLE AUTOPILOT ALTITUDE HOLD": CheckSpec("AUTOPILOT_ALTITUDE_LOCK", 0.5, "press it once"),
    "TOGGLE AUTOPILOT VS HOLD": CheckSpec("AUTOPILOT_VERTICAL_HOLD", 0.5, "press it once"),
    "ELEVATOR TRIM UP / DOWN": CheckSpec("ELEVATOR_TRIM_PCT", 0.01, "click several times in one direction"),
    "ELEVATOR TRIM AXIS": CheckSpec("ELEVATOR_TRIM_PCT", 0.01, "spin the wheel a few turns"),
    "INCREASE / DECREASE FLAPS": CheckSpec("FLAPS_HANDLE_INDEX", 0.5, "move the flap lever one notch"),
    "MAGNETO OFF / RIGHT / LEFT / BOTH / START": CheckSpec(
        "RECIP_ENG_LEFT_MAGNETO:1", 0.5, "rotate BOTH → L and back"
    ),
    "HEADING BUG INC/DEC": CheckSpec("AUTOPILOT_HEADING_LOCK_DIR", 0.9, "selector on HDG, twist the knob"),
}


def spec_for(msfs_setting: str) -> CheckSpec | None:
    setting = msfs_setting.strip().upper()
    if not setting or setting in ("—", "-"):
        return None
    for key, spec in SPECS.items():
        if key in setting:
            return spec
    return None


@dataclass
class BindingTest:
    control: str            # physical control label
    control_id: str
    assignment: str
    spec: CheckSpec
    status: str = "pending"     # pending | active | passed | hw_only | failed | skipped
    hw_seen: bool = False
    sim_seen: bool = False


@dataclass
class TestPlanResult:
    tests: list[BindingTest] = field(default_factory=list)
    untestable: list[tuple[str, str]] = field(default_factory=list)  # (control, reason)


def build_tests(plan_bindings, control_ids: dict[str, str], input_map) -> TestPlanResult:
    """Testable bindings for one device: needs a CheckSpec AND a physical mapping."""

    def lookup(label: str) -> str | None:
        if label in control_ids:
            return control_ids[label]
        lowered = label.lower()
        for full, cid in control_ids.items():
            fl = full.lower()
            if fl.startswith(lowered) or lowered.startswith(fl):
                return cid
        return None

    out = TestPlanResult()
    for b in plan_bindings:
        if "UNBOUND" in b.assignment.upper():
            continue
        control_id = lookup(b.control)
        if control_id is None:
            out.untestable.append((b.control, "not in the device profile"))
            continue
        spec = spec_for(b.msfs_setting)
        if spec is None:
            out.untestable.append((b.control, "no observable SimVar — check by eye in the cockpit"))
            continue
        has_phys = (
            input_map.axis_for_control(control_id) is not None
            or bool(input_map.buttons_for_control(control_id))
        )
        if not has_phys:
            out.untestable.append((b.control, "no physical mapping — run Learn mode first"))
            continue
        out.tests.append(
            BindingTest(control=b.control, control_id=control_id, assignment=b.assignment, spec=spec)
        )
    return out
