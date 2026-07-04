"""Physical input maps: pygame button/axis indices -> logical control ids.

Ships best-effort defaults for the supported hardware; every mapping can be
corrected in the app's Learn mode (click a control on the diagram, press the
physical input). Learned maps are persisted to ~/.msfs_companion/input_maps.json
and win over the defaults. The same map drives the live visualizer AND the
MSFS profile writer (button index N -> JOYSTICK_BUTTON_{N+1}).
"""

from __future__ import annotations

import json
from pathlib import Path

USER_MAP_PATH = Path.home() / ".msfs_companion" / "input_maps.json"

# MSFS keycode names by pygame axis index (DirectInput ordering).
AXIS_KEYCODES = [
    "JOYSTICK_L_AXIS_X",
    "JOYSTICK_L_AXIS_Y",
    "JOYSTICK_L_AXIS_Z",
    "JOYSTICK_R_AXIS_X",
    "JOYSTICK_R_AXIS_Y",
    "JOYSTICK_R_AXIS_Z",
    "JOYSTICK_SLIDER_X",
    "JOYSTICK_SLIDER_Y",
]

# Defaults are approximate (community-observed orderings) — the visualizer's
# Learn mode is the source of truth on a real rig.
DEFAULT_MAPS: dict[str, dict] = {
    "honeycomb_alpha": {
        "axes": {"0": "aileron", "1": "elevator"},
        "buttons": {
            "0": "ap_disc",
            "1": "wheel_l", "2": "wheel_l",
            "3": "wheel_r", "4": "wheel_r",
            "5": "rocker_r", "6": "rocker_r",
            "13": "sw_alt", "14": "sw_alt",
            "15": "sw_bat", "16": "sw_bat",
            "17": "sw_avionics1", "18": "sw_avionics1",
            "19": "sw_avionics2", "20": "sw_avionics2",
            "21": "sw_light_bcn", "22": "sw_light_land",
            "23": "sw_light_taxi", "24": "sw_light_nav", "25": "sw_light_strobe",
            "29": "magneto", "30": "magneto", "31": "magneto", "32": "magneto", "33": "magneto",
        },
        "hats": {"0": "hat"},
    },
    "honeycomb_bravo": {
        "axes": {"0": "lever1", "1": "lever2", "2": "lever3", "3": "lever4"},
        "buttons": {
            "0": "ap_hdg", "1": "ap_nav", "2": "ap_apr", "3": "ap_rev",
            "4": "ap_alt", "5": "ap_vs", "6": "ap_ias", "7": "ap_master",
            "8": "flaps", "9": "flaps",
            "10": "ap_knob", "11": "ap_knob",
            "12": "ap_selector", "13": "ap_selector", "14": "ap_selector",
            "15": "ap_selector", "16": "ap_selector",
            "18": "go_around",
            "21": "trim_wheel", "22": "trim_wheel",
            "29": "gear", "30": "gear",
            "32": "sw1", "33": "sw1", "34": "sw2", "35": "sw2",
            "36": "sw3", "37": "sw3", "38": "sw4", "39": "sw4",
            "40": "sw5", "41": "sw5", "42": "sw6", "43": "sw6",
            "44": "sw7", "45": "sw7",
        },
        "hats": {},
    },
    "velocityone_rudder": {
        "axes": {"0": "brake_left", "1": "brake_right", "2": "rudder"},
        "buttons": {},
        "hats": {},
    },
    "keyboard_mouse": {"axes": {}, "buttons": {}, "hats": {}},
}


class InputMap:
    """Merged default + user-learned physical map for one device."""

    def __init__(self, device_id: str, data: dict):
        self.device_id = device_id
        self.axes: dict[int, str] = {int(k): v for k, v in data.get("axes", {}).items()}
        self.buttons: dict[int, str] = {int(k): v for k, v in data.get("buttons", {}).items()}
        self.hats: dict[int, str] = {int(k): v for k, v in data.get("hats", {}).items()}

    def control_for_button(self, index: int) -> str | None:
        return self.buttons.get(index)

    def control_for_axis(self, index: int) -> str | None:
        return self.axes.get(index)

    def buttons_for_control(self, control_id: str) -> list[int]:
        return sorted(i for i, c in self.buttons.items() if c == control_id)

    def axis_for_control(self, control_id: str) -> int | None:
        for i, c in self.axes.items():
            if c == control_id:
                return i
        return None

    def learn_button(self, index: int, control_id: str) -> None:
        self.buttons[index] = control_id

    def learn_axis(self, index: int, control_id: str) -> None:
        # An axis maps to exactly one control; drop stale entries for it.
        self.axes = {i: c for i, c in self.axes.items() if c != control_id}
        self.axes[index] = control_id

    def to_dict(self) -> dict:
        return {
            "axes": {str(k): v for k, v in self.axes.items()},
            "buttons": {str(k): v for k, v in self.buttons.items()},
            "hats": {str(k): v for k, v in self.hats.items()},
        }


def load_maps(user_path: Path | None = None) -> dict[str, InputMap]:
    """Defaults overlaid with any user-learned mappings."""
    user_path = user_path or USER_MAP_PATH
    merged = {k: json.loads(json.dumps(v)) for k, v in DEFAULT_MAPS.items()}
    try:
        with open(user_path, encoding="utf-8") as f:
            user = json.load(f)
        for device_id, data in user.items():
            merged.setdefault(device_id, {"axes": {}, "buttons": {}, "hats": {}})
            for section in ("axes", "buttons", "hats"):
                merged[device_id].setdefault(section, {}).update(data.get(section, {}))
    except (OSError, json.JSONDecodeError):
        pass
    return {device_id: InputMap(device_id, data) for device_id, data in merged.items()}


def save_maps(maps: dict[str, InputMap], user_path: Path | None = None) -> None:
    user_path = user_path or USER_MAP_PATH
    user_path.parent.mkdir(parents=True, exist_ok=True)
    with open(user_path, "w", encoding="utf-8") as f:
        json.dump({device_id: m.to_dict() for device_id, m in maps.items()}, f, indent=2)
