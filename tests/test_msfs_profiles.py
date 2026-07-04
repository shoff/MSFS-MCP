"""MSFS profile parse/write round-trip on a synthetic AceXML fixture (no MSFS needed)."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from controls_app.bindings import load_default_plans
from controls_app.devices import HONEYCOMB_BRAVO, VELOCITYONE_RUDDER
from controls_app.input_map import InputMap, load_maps, save_maps
from controls_app.msfs_profiles import (
    ActionWrite,
    ProfileError,
    parse_profile,
    resolve_writes,
    write_bindings,
)

FIXTURE = """<?xml version="1.0" encoding="Windows-1252"?>

<Version Num="66">
    <Descr>AceXML Document</Descr>
    <FriendlyName>My C172 profile</FriendlyName>
    <Device DeviceName="Bravo Throttle Quadrant" GUID="{ABC}" ProductID="6401">
        <Context ContextName="AIRCRAFT">
            <Action ActionName="KEY_AXIS_THROTTLE_SET" Flag="2">
                <Primary>
                    <KEY Information="Joystick L-Axis X" KeyCode="JOYSTICK_L_AXIS_X"/>
                </Primary>
            </Action>
        </Context>
    </Device>
</Version>
"""


@pytest.fixture
def profile_file(tmp_path):
    path = tmp_path / "inputprofile_0"
    path.write_text(FIXTURE, encoding="windows-1252")
    return path


def test_parse_profile(profile_file):
    prof = parse_profile(profile_file)
    assert prof.friendly_name == "My C172 profile"
    assert prof.device_names == ["Bravo Throttle Quadrant"]


def test_write_replaces_and_adds_actions(profile_file, tmp_path):
    backup_dir = tmp_path / "backups"
    backup = write_bindings(
        profile_file,
        "Bravo Throttle",
        [
            ActionWrite("KEY_AXIS_THROTTLE_SET", "JOYSTICK_L_AXIS_Z", "Lever 1"),
            ActionWrite("KEY_AXIS_MIXTURE_SET", "JOYSTICK_L_AXIS_Y", "Lever 3"),
            ActionWrite("KEY_TOGGLE_ELECT_FUEL_PUMP", "JOYSTICK_BUTTON_33", "SW1"),
        ],
        backup_dir=backup_dir,
    )
    assert backup is not None and backup.exists()
    assert backup.read_text(encoding="windows-1252") == FIXTURE  # untouched original

    text = profile_file.read_text(encoding="windows-1252")
    assert text.lower().startswith('<?xml version="1.0" encoding="windows-1252"?>')
    root = ET.fromstring(text)
    context = root.find(".//Device/Context")
    actions = {a.get("ActionName"): a for a in context.findall("Action")}
    # replaced, not duplicated
    assert len(context.findall("Action[@ActionName='KEY_AXIS_THROTTLE_SET']")) == 1
    assert actions["KEY_AXIS_THROTTLE_SET"].find("Primary/KEY").get("KeyCode") == "JOYSTICK_L_AXIS_Z"
    assert actions["KEY_AXIS_MIXTURE_SET"].find("Primary/KEY").get("KeyCode") == "JOYSTICK_L_AXIS_Y"
    assert actions["KEY_TOGGLE_ELECT_FUEL_PUMP"].find("Primary/KEY").get("KeyCode") == "JOYSTICK_BUTTON_33"

    # still parseable as a profile afterwards
    prof = parse_profile(profile_file)
    assert prof.friendly_name == "My C172 profile"


def test_write_wrong_device_raises(profile_file, tmp_path):
    with pytest.raises(ProfileError):
        write_bindings(profile_file, "Alpha Flight Controls", [], backup_dir=tmp_path)


def test_resolve_writes_bravo_c172():
    plans = load_default_plans()
    plan = plans["c172s"]
    maps = load_maps(user_path=Path("/nonexistent"))
    imap = maps["honeycomb_bravo"]
    control_ids = {c.label: c.id for c in HONEYCOMB_BRAVO.inputs}
    resolved = resolve_writes(plan.devices["honeycomb_bravo"], control_ids, imap)

    actions = {a.action_name: a.keycode for a in resolved.actions}
    assert actions["KEY_AXIS_THROTTLE_SET"] == "JOYSTICK_L_AXIS_X"
    assert actions["KEY_AXIS_MIXTURE_SET"] == "JOYSTICK_L_AXIS_Z"
    assert "KEY_FLAPS_INCR" in actions and "KEY_FLAPS_DECR" in actions
    assert "KEY_ELEV_TRIM_UP" in actions and "KEY_ELEV_TRIM_DN" in actions
    # fixed-pitch prop and fixed gear are deliberately NOT written
    assert "KEY_AXIS_PROPELLER_SET" not in actions
    written_controls = {a.information for a in resolved.actions}
    assert "Lever 2 (blue — propeller handle)" not in written_controls
    assert "Landing gear lever" not in written_controls


def test_resolve_writes_rudder():
    plans = load_default_plans()
    plan = plans["c172s"]
    maps = load_maps(user_path=Path("/nonexistent"))
    imap = maps["velocityone_rudder"]
    control_ids = {c.label: c.id for c in VELOCITYONE_RUDDER.inputs}
    resolved = resolve_writes(plan.devices["velocityone_rudder"], control_ids, imap)
    actions = {a.action_name: a.keycode for a in resolved.actions}
    assert actions["KEY_AXIS_RUDDER_SET"] == "JOYSTICK_L_AXIS_Z"
    assert actions["KEY_AXIS_LEFT_BRAKE_SET"] == "JOYSTICK_L_AXIS_X"
    assert actions["KEY_AXIS_RIGHT_BRAKE_SET"] == "JOYSTICK_L_AXIS_Y"
    assert not resolved.skipped


def test_input_map_learn_and_persist(tmp_path):
    path = tmp_path / "maps.json"
    maps = load_maps(user_path=path)
    imap = maps["honeycomb_bravo"]
    imap.learn_button(50, "sw7")
    imap.learn_axis(5, "lever4")
    save_maps(maps, user_path=path)

    reloaded = load_maps(user_path=path)["honeycomb_bravo"]
    assert reloaded.control_for_button(50) == "sw7"
    assert reloaded.control_for_axis(5) == "lever4"
    # defaults survive alongside learned entries
    assert reloaded.control_for_axis(0) == "lever1"


def test_input_map_axis_relearn_replaces_old():
    imap = InputMap("honeycomb_alpha", {"axes": {"0": "aileron"}, "buttons": {}, "hats": {}})
    imap.learn_axis(3, "aileron")
    assert imap.axis_for_control("aileron") == 3
    assert imap.control_for_axis(0) is None
