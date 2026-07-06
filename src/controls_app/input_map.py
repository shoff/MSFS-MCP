"""Physical input maps: which physical button/axis drives each logical control.

Model (v2): each control owns an ORDERED list of physical button indices, one
per semantic action slot (e.g. flaps = [downNotchBtn, upNotchBtn], magneto =
[off, r, l, both, start]). Axes are one index per control. This ordering is
what the MSFS profile writer binds against, so "learned in order" == "written
in order" — no more relying on sorted index == semantic order.

Learned maps persist to ~/.msfs_companion/input_maps.json and win over the
shipped defaults. Learning a control REPLACES its whole mapping (no stale
default indices survive) and steals those indices from any other control.
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


def lookup_control(label: str, control_ids: dict[str, str]) -> str | None:
    """Resolve a plan's control label to a device control id, prefix-tolerant.

    Shared by the profile writer and the live verifier so they always resolve
    the same plan the same way.
    """
    if label in control_ids:
        return control_ids[label]
    lowered = label.lower()
    for full_label, cid in control_ids.items():
        fl = full_label.lower()
        if fl.startswith(lowered) or lowered.startswith(fl):
            return cid
    return None


# control_id -> ordered physical button indices (semantic-slot order).
DEFAULT_MAPS: dict[str, dict] = {
    "honeycomb_alpha": {
        "axes": {"0": "aileron", "1": "elevator"},
        "buttons": {
            "ap_disc": [0],
            "wheel_l": [1, 2],
            "wheel_r": [3, 4],
            "rocker_r": [5, 6],
            "sw_alt": [13, 14],
            "sw_bat": [15, 16],
            "sw_avionics1": [17, 18],
            "sw_avionics2": [19, 20],
            "sw_light_bcn": [21, 22],
            "sw_light_land": [23],
            "sw_light_taxi": [24],
            "sw_light_nav": [25],
            "sw_light_strobe": [26],
            "magneto": [29, 30, 31, 32, 33],
        },
        "hats": {"0": "hat"},
    },
    "honeycomb_bravo": {
        "axes": {"0": "lever1", "1": "lever2", "2": "lever3", "3": "lever4"},
        "buttons": {
            "ap_hdg": [0],
            "ap_nav": [1],
            "ap_apr": [2],
            "ap_rev": [3],
            "ap_alt": [4],
            "ap_vs": [5],
            "ap_ias": [6],
            "ap_master": [7],
            "flaps": [8, 9],
            "ap_knob": [10, 11],
            "ap_selector": [12, 13, 14, 15, 16],
            "go_around": [18],
            "trim_wheel": [21, 22],
            "gear": [29, 30],
            "sw1": [32, 33],
            "sw2": [34, 35],
            "sw3": [36, 37],
            "sw4": [38, 39],
            "sw5": [40, 41],
            "sw6": [42, 43],
            "sw7": [44, 45],
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
        # control_id -> ordered button indices
        self.buttons: dict[str, list[int]] = {
            cid: [int(i) for i in idxs] for cid, idxs in data.get("buttons", {}).items()
        }
        self.hats: dict[int, str] = {int(k): v for k, v in data.get("hats", {}).items()}

    # -- reads -------------------------------------------------------------
    def control_for_button(self, index: int) -> str | None:
        for cid, idxs in self.buttons.items():
            if index in idxs:
                return cid
        return None

    def control_for_axis(self, index: int) -> str | None:
        return self.axes.get(index)

    def buttons_for_control(self, control_id: str) -> list[int]:
        return list(self.buttons.get(control_id, []))

    def axis_for_control(self, control_id: str) -> int | None:
        for i, c in self.axes.items():
            if c == control_id:
                return i
        return None

    # -- learning ----------------------------------------------------------
    def set_control_buttons(self, control_id: str, indices: list[int]) -> None:
        """Replace a control's whole ordered button mapping.

        A physical button drives exactly one control, so the given indices are
        also removed from every other control — this is what stops stale
        default indices from surviving a Learn pass and being written instead.
        """
        wanted = set(indices)
        for cid in list(self.buttons):
            if cid == control_id:
                continue
            remaining = [i for i in self.buttons[cid] if i not in wanted]
            if remaining:
                self.buttons[cid] = remaining
            else:
                del self.buttons[cid]
        self.buttons[control_id] = list(indices)

    def learn_axis(self, index: int, control_id: str) -> None:
        # An axis maps to exactly one control; drop stale entries for it.
        self.axes = {i: c for i, c in self.axes.items() if c != control_id}
        self.axes[index] = control_id

    def to_dict(self) -> dict:
        return {
            "axes": {str(k): v for k, v in self.axes.items()},
            "buttons": {cid: list(idxs) for cid, idxs in self.buttons.items()},
            "hats": {str(k): v for k, v in self.hats.items()},
        }


def _normalize_buttons(raw: dict) -> dict[str, list[int]]:
    """Accept both the v2 format (control_id -> [indices]) and the legacy v1
    format (index -> control_id), returning v2. Bad entries are dropped."""
    if not isinstance(raw, dict) or not raw:
        return {}
    # v1 if the values are strings (control ids); v2 if they are lists.
    if all(isinstance(v, str) for v in raw.values()):
        out: dict[str, list[int]] = {}
        for index, cid in raw.items():
            try:
                out.setdefault(cid, []).append(int(index))
            except (TypeError, ValueError):
                continue
        for cid in out:
            out[cid].sort()  # legacy had no order; best-effort
        return out
    out = {}
    for cid, idxs in raw.items():
        if isinstance(idxs, list):
            try:
                out[cid] = [int(i) for i in idxs]
            except (TypeError, ValueError):
                continue
    return out


def load_maps(user_path: Path | None = None) -> dict[str, InputMap]:
    """Defaults overlaid with any user-learned mappings (learned wins per control)."""
    user_path = user_path or USER_MAP_PATH
    merged = {k: json.loads(json.dumps(v)) for k, v in DEFAULT_MAPS.items()}
    try:
        with open(user_path, encoding="utf-8") as f:
            user = json.load(f)
        for device_id, data in user.items():
            base = merged.setdefault(device_id, {"axes": {}, "buttons": {}, "hats": {}})
            base.setdefault("axes", {}).update(data.get("axes", {}))
            base.setdefault("hats", {}).update(data.get("hats", {}))
            # A learned control replaces its default button list wholesale.
            learned_buttons = _normalize_buttons(data.get("buttons", {}))
            base["buttons"] = _normalize_buttons(base.get("buttons", {}))
            learned_idx = {i for idxs in learned_buttons.values() for i in idxs}
            for cid in list(base["buttons"]):
                base["buttons"][cid] = [i for i in base["buttons"][cid] if i not in learned_idx]
                if not base["buttons"][cid]:
                    del base["buttons"][cid]
            base["buttons"].update(learned_buttons)
    except (OSError, json.JSONDecodeError):
        pass
    return {device_id: InputMap(device_id, data) for device_id, data in merged.items()}


def save_maps(maps: dict[str, InputMap], user_path: Path | None = None) -> None:
    user_path = user_path or USER_MAP_PATH
    user_path.parent.mkdir(parents=True, exist_ok=True)
    with open(user_path, "w", encoding="utf-8") as f:
        json.dump({device_id: m.to_dict() for device_id, m in maps.items()}, f, indent=2)
