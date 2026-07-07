"""Binding-verification specs and test-plan construction (headless)."""

from pathlib import Path

from controls_app.binding_check import build_tests
from controls_app.bindings import load_default_plans
from controls_app.devices import HONEYCOMB_ALPHA, HONEYCOMB_BRAVO, VELOCITYONE_RUDDER
from controls_app.input_map import InputMap, load_maps
from controls_app.settings_registry import spec_for_setting


def test_spec_for_matching():
    assert spec_for_setting("THROTTLE AXIS").check_var == "GENERAL_ENG_THROTTLE_LEVER_POSITION:1"
    assert spec_for_setting("TOGGLE MASTER BATTERY").check_var == "ELECTRICAL_MASTER_BATTERY"
    # writer and verifier now share one table: the carb-heat wording drift is gone
    assert spec_for_setting("TOGGLE CARBURETOR HEAT (ANTI-ICE)").check_var == "GENERAL_ENG_ANTI_ICE_POSITION:1"
    assert spec_for_setting("TOGGLE CARBURETOR HEAT").check_var == "GENERAL_ENG_ANTI_ICE_POSITION:1"
    assert spec_for_setting("MAGNETO OFF / RIGHT / LEFT / BOTH / START (PER POSITION)") is not None
    assert spec_for_setting("—") is None
    assert spec_for_setting("") is None
    assert spec_for_setting("(default 'Cockpit interaction' bindings)") is None


def _tests_for(device, device_id, aircraft="c172s"):
    plan = load_default_plans()[aircraft]
    imap = load_maps(user_path=Path("/nonexistent"))[device_id]
    control_ids = {c.label: c.id for c in device.inputs}
    return build_tests(plan.devices[device_id], control_ids, imap)


def test_bravo_c172_test_plan():
    result = _tests_for(HONEYCOMB_BRAVO, "honeycomb_bravo")
    controls = {t.control_id for t in result.tests}
    # essentials are testable
    assert {"lever1", "lever3", "flaps", "trim_wheel", "ap_master", "sw1"} <= controls
    # deliberately-unbound controls are excluded entirely
    assert "lever2" not in controls and "gear" not in controls
    untestable = dict(result.untestable)
    assert not any("lever 2" in c.lower() for c in untestable)


def test_rudder_all_axes_testable():
    result = _tests_for(VELOCITYONE_RUDDER, "velocityone_rudder")
    assert {t.control_id for t in result.tests} == {"rudder", "brake_left", "brake_right"}
    assert not result.untestable


def test_alpha_magneto_and_switches_testable():
    result = _tests_for(HONEYCOMB_ALPHA, "honeycomb_alpha")
    controls = {t.control_id for t in result.tests}
    assert {"aileron", "elevator", "magneto", "sw_bat", "sw_light_strobe", "right_red"} <= controls


def test_unmapped_control_reported_as_untestable():
    plan = load_default_plans()["c172s"]
    empty_map = InputMap("honeycomb_bravo", {"axes": {}, "buttons": {}, "hats": {}})
    control_ids = {c.label: c.id for c in HONEYCOMB_BRAVO.inputs}
    result = build_tests(plan.devices["honeycomb_bravo"], control_ids, empty_map)
    assert not result.tests
    assert all("Learn mode" in reason for _c, reason in result.untestable
               if "SimVar" not in reason and "profile" not in reason)
