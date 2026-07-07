"""Validate device profiles, default binding plans, and the advisor prompt (no GUI, no network)."""

import pytest

from controls_app.bindings import PRIORITIES, ControlPlan, load_default_plans
from controls_app.devices import DEVICE_BY_ID, DEVICES, HONEYCOMB_ALPHA, HONEYCOMB_BRAVO, VELOCITYONE_RUDDER


@pytest.fixture(scope="module")
def plans():
    return load_default_plans()


def test_supported_hardware_present():
    ids = {d.id for d in DEVICES}
    assert {"honeycomb_alpha", "honeycomb_bravo", "velocityone_rudder", "keyboard_mouse"} <= ids


def test_device_matching():
    assert HONEYCOMB_ALPHA.matches("Alpha Flight Controls")
    assert HONEYCOMB_ALPHA.matches("anything", vid=0x294B, pid=0x1900)
    assert HONEYCOMB_BRAVO.matches("Bravo Throttle Quadrant")
    assert VELOCITYONE_RUDDER.matches("VelocityOne Rudder")
    assert not HONEYCOMB_ALPHA.matches("Some Random Gamepad")


def test_rudder_detected_across_name_variants():
    # Whatever spacing/punctuation the driver reports, the Turtle Beach pedals
    # should still be recognized (normalized name match).
    for name in [
        "VelocityOne Rudder",
        "VelocityOne Rudder Pedals",
        "Velocity One Rudder",
        "Turtle Beach VelocityOne Rudder",
        "Turtle Beach - VelocityOne Rudder Pedals",
    ]:
        assert VELOCITYONE_RUDDER.matches(name), name
    assert not VELOCITYONE_RUDDER.matches("Honeycomb Bravo Throttle Quadrant")


def test_vid_pid_parsed_from_sdl_guid():
    from controls_app.devices import vid_pid_from_guid

    # SDL GUID: vendor 0x294B at bytes 4-5, product 0x1900 at bytes 8-9 (LE).
    guid = "03000000" "4b290000" "00190000" "00000000"
    assert vid_pid_from_guid(guid) == (0x294B, 0x1900)
    # A real Honeycomb Alpha reports exactly these — matching by GUID even when
    # the OS renames the device.
    vid, pid = vid_pid_from_guid(guid)
    assert HONEYCOMB_ALPHA.matches("Generic USB Joystick", vid=vid, pid=pid)
    # No USB IDs in the GUID (bus type only) -> (None, None), not a crash.
    assert vid_pid_from_guid("00000000000000000000000000000000") == (None, None)
    assert vid_pid_from_guid(None) == (None, None)
    assert vid_pid_from_guid("short") == (None, None)


def test_plans_exist_for_both_aircraft(plans):
    assert "c172s" in plans
    assert "pa28_181" in plans


def test_plan_devices_and_bindings_are_valid(plans):
    for plan in plans.values():
        assert plan.summary and plan.aircraft_notes
        assert len(plan.coaching) >= 4
        for device_id, bindings in plan.devices.items():
            assert device_id in DEVICE_BY_ID, device_id
            assert bindings, device_id
            for b in bindings:
                assert b.control and b.assignment
                assert b.priority in PRIORITIES


def test_fixed_pitch_aircraft_leave_prop_lever_unbound(plans):
    """Both aircraft are fixed-pitch — the plan must teach that, not bind the prop lever."""
    for plan in plans.values():
        bravo = plan.devices["honeycomb_bravo"]
        prop = next(b for b in bravo if "propeller" in b.control.lower())
        assert "unbound" in prop.assignment.lower(), plan.aircraft_key


def test_essential_axes_covered(plans):
    for plan in plans.values():
        assignments = " ".join(
            b.msfs_setting for bindings in plan.devices.values() for b in bindings
        ).upper()
        for axis in ("AILERONS AXIS", "ELEVATOR AXIS", "THROTTLE AXIS", "MIXTURE AXIS", "RUDDER AXIS"):
            assert axis in assignments, f"{plan.aircraft_key} missing {axis}"


def test_advisor_prompt_and_schema_shape():
    from controls_app import advisor

    plans = load_default_plans()
    plan = plans["c172s"]
    prompt = advisor._build_user_prompt(
        aircraft_name=plan.aircraft_name,
        aircraft_context="V-speeds: Vr 55",
        detected={"honeycomb_alpha": True, "honeycomb_bravo": False},
        current_plan=plan,
        user_notes="no pedals yet",
    )
    assert "DETECTED" in prompt and "not detected" in prompt
    assert "Bravo" in prompt and "no pedals yet" in prompt
    assert plan.aircraft_name in prompt

    # Structured-output schema constraints: additionalProperties false everywhere.
    def walk(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                assert schema.get("additionalProperties") is False
                assert "required" in schema
            for value in schema.values():
                walk(value)
        elif isinstance(schema, list):
            for value in schema:
                walk(value)

    walk(advisor.PLAN_SCHEMA)


def test_plan_round_trip(plans):
    plan = plans["pa28_181"]
    clone = ControlPlan.from_dict(plan.to_dict(), source=plan.source)
    assert clone.to_dict() == plan.to_dict()
