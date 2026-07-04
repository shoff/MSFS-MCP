"""Read and WRITE Microsoft Flight Simulator 2024/2020 input profiles.

MSFS stores each controls profile as an XML document ("AceXML"):

    <Version Num="...">
        <Descr>AceXML Document</Descr>
        <FriendlyName>My C172 profile</FriendlyName>
        <Device DeviceName="Bravo Throttle Quadrant" GUID="{...}" ProductID="...">
            <Context ContextName="AIRCRAFT">
                <Action ActionName="KEY_AXIS_THROTTLE_SET" Flag="2">
                    <Primary><KEY Information="Joystick L-Axis Z"
                                  KeyCode="JOYSTICK_L_AXIS_Z"/></Primary>
                </Action>
            </Context>
        </Device>
    </Version>

Steam builds keep these as ``inputprofile_*`` files under %APPDATA%; the
MS Store builds keep them as extensionless GUID-named files inside the Xbox
WGS container. In both cases we only ever UPDATE an existing profile file in
place (same path, same size class) — that is the approach the established
community profile editors use and it does not disturb ``containers.index``.
Creating brand-new profiles is deliberately left to the MSFS UI: make an
empty profile there once, then let this module populate it.

Every write goes through a timestamped backup first.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

BACKUP_DIR = Path.home() / ".msfs_companion" / "profile_backups"


# --------------------------------------------------------------------------
# Locating profile files
# --------------------------------------------------------------------------

def candidate_roots() -> list[tuple[str, Path]]:
    """Places MSFS keeps input profiles, most likely first."""
    roots: list[tuple[str, Path]] = []
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        roots.append(("MSFS 2024 (Steam)", Path(appdata) / "Microsoft Flight Simulator 2024"))
        roots.append(("MSFS 2020 (Steam)", Path(appdata) / "Microsoft Flight Simulator"))
    if localappdata:
        roots.append((
            "MSFS 2024 (Microsoft Store)",
            Path(localappdata) / "Packages" / "Microsoft.Limitless_8wekyb3d8bbwe" / "SystemAppData" / "wgs",
        ))
        roots.append((
            "MSFS 2020 (Microsoft Store)",
            Path(localappdata) / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "SystemAppData" / "wgs",
        ))
    return roots


def _looks_like_profile(path: Path) -> bool:
    try:
        if path.stat().st_size > 2_000_000:
            return False
        head = path.read_bytes()[:4096].decode("utf-8", errors="ignore")
    except OSError:
        return False
    return "<Device" in head and ("FriendlyName" in head or "ContextName" in head)


@dataclass
class InputProfile:
    path: Path
    source: str                   # which install it came from
    friendly_name: str
    device_names: list[str] = field(default_factory=list)


def find_profiles(extra_roots: list[Path] | None = None) -> list[InputProfile]:
    """Scan the known locations (plus any extra folders) for input profiles."""
    profiles: list[InputProfile] = []
    scan: list[tuple[str, Path]] = list(candidate_roots())
    for root in extra_roots or []:
        scan.append(("custom folder", root))
    for source, root in scan:
        if not root.is_dir():
            continue
        candidates = [p for p in root.rglob("*") if p.is_file()]
        for path in candidates:
            name = path.name.lower()
            if not (name.startswith("inputprofile") or "wgs" in str(path).lower()
                    or source == "custom folder"):
                continue
            if not _looks_like_profile(path):
                continue
            try:
                parsed = parse_profile(path)
            except ProfileError:
                continue
            parsed.source = source
            profiles.append(parsed)
    return profiles


# --------------------------------------------------------------------------
# Parsing / writing
# --------------------------------------------------------------------------

class ProfileError(RuntimeError):
    pass


def _read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    match = re.search(rb'encoding="([^"]+)"', data[:200])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return data.decode(encoding), encoding
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace"), "utf-8"


def parse_profile(path: Path) -> InputProfile:
    text, _ = _read_text(path)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProfileError(f"{path.name}: not valid XML ({exc})") from exc
    friendly = root.findtext(".//FriendlyName") or path.stem
    devices = [d.get("DeviceName", "?") for d in root.iter("Device")]
    if not devices:
        raise ProfileError(f"{path.name}: no <Device> elements")
    return InputProfile(path=path, source="", friendly_name=friendly.strip(), device_names=devices)


@dataclass
class ActionWrite:
    action_name: str        # e.g. KEY_AXIS_THROTTLE_SET
    keycode: str            # e.g. JOYSTICK_L_AXIS_Z or JOYSTICK_BUTTON_5
    information: str = ""   # human-readable label MSFS shows


def backup_profile(path: Path, backup_dir: Path = BACKUP_DIR) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def write_bindings(
    path: Path,
    device_name_fragment: str,
    actions: list[ActionWrite],
    context_name: str = "AIRCRAFT",
    make_backup: bool = True,
    backup_dir: Path = BACKUP_DIR,
) -> Path | None:
    """Inject/replace Action bindings for one device in an existing profile.

    Returns the backup path (None if make_backup=False). Raises ProfileError
    if the profile has no matching <Device>.
    """
    text, encoding = _read_text(path)
    root = ET.fromstring(text)

    fragment = device_name_fragment.lower()
    device = next(
        (d for d in root.iter("Device") if fragment in d.get("DeviceName", "").lower()),
        None,
    )
    if device is None:
        names = ", ".join(d.get("DeviceName", "?") for d in root.iter("Device"))
        raise ProfileError(
            f"No device matching '{device_name_fragment}' in this profile "
            f"(it has: {names}). Pick the profile MSFS created for that device."
        )

    context = next(
        (c for c in device.findall("Context") if c.get("ContextName") == context_name),
        None,
    )
    if context is None:
        context = ET.SubElement(device, "Context", {"ContextName": context_name})

    for aw in actions:
        action = next(
            (a for a in context.findall("Action") if a.get("ActionName") == aw.action_name),
            None,
        )
        if action is None:
            action = ET.SubElement(context, "Action", {"ActionName": aw.action_name, "Flag": "2"})
        # Replace the Primary binding; leave any Secondary untouched.
        for primary in action.findall("Primary"):
            action.remove(primary)
        primary = ET.SubElement(action, "Primary")
        ET.SubElement(primary, "KEY", {"Information": aw.information or aw.keycode, "KeyCode": aw.keycode})

    backup = backup_profile(path, backup_dir) if make_backup else None

    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    payload = f'<?xml version="1.0" encoding="{encoding}"?>\n\n{body}'
    path.write_bytes(payload.encode(encoding, errors="replace"))
    return backup


# --------------------------------------------------------------------------
# Plan -> writable actions
# --------------------------------------------------------------------------

# msfs_setting (normalized) -> action name(s). Multi-direction controls expand
# to several actions bound to consecutive learned button indices.
AXIS_ACTIONS = {
    "AILERONS AXIS": "KEY_AXIS_AILERONS_SET",
    "ELEVATOR AXIS": "KEY_AXIS_ELEVATOR_SET",
    "RUDDER AXIS": "KEY_AXIS_RUDDER_SET",
    "THROTTLE AXIS": "KEY_AXIS_THROTTLE_SET",
    "MIXTURE AXIS": "KEY_AXIS_MIXTURE_SET",
    "LEFT BRAKE AXIS": "KEY_AXIS_LEFT_BRAKE_SET",
    "RIGHT BRAKE AXIS": "KEY_AXIS_RIGHT_BRAKE_SET",
}

BUTTON_ACTIONS = {
    "TOGGLE MASTER BATTERY": ["KEY_TOGGLE_MASTER_BATTERY"],
    "TOGGLE MASTER ALTERNATOR": ["KEY_TOGGLE_MASTER_ALTERNATOR"],
    "TOGGLE AVIONICS MASTER 1": ["KEY_TOGGLE_AVIONICS_MASTER"],
    "TOGGLE BEACON LIGHTS": ["KEY_TOGGLE_BEACON_LIGHTS"],
    "LANDING LIGHTS TOGGLE": ["KEY_LANDING_LIGHTS_TOGGLE"],
    "TOGGLE TAXI LIGHTS": ["KEY_TOGGLE_TAXI_LIGHTS"],
    "TOGGLE NAV LIGHTS": ["KEY_TOGGLE_NAV_LIGHTS"],
    "TOGGLE STROBES": ["KEY_STROBES_TOGGLE"],
    "TOGGLE ELECTRIC FUEL PUMP": ["KEY_TOGGLE_ELECT_FUEL_PUMP"],
    "TOGGLE PITOT HEAT": ["KEY_PITOT_HEAT_TOGGLE"],
    "TOGGLE CARBURETOR HEAT (ANTI-ICE)": ["KEY_ANTI_ICE_TOGGLE_ENG1"],
    "AUTOPILOT OFF / DISCONNECT": ["KEY_AUTOPILOT_OFF"],
    "TOGGLE AUTOPILOT MASTER": ["KEY_AP_MASTER"],
    "TOGGLE AUTOPILOT HEADING HOLD": ["KEY_AP_HDG_HOLD"],
    "TOGGLE AUTOPILOT NAV1 HOLD": ["KEY_AP_NAV1_HOLD"],
    "TOGGLE AUTOPILOT APPROACH HOLD": ["KEY_AP_APR_HOLD"],
    "TOGGLE AUTOPILOT REVERSE HOLD": ["KEY_AP_BC_HOLD"],
    "TOGGLE AUTOPILOT ALTITUDE HOLD": ["KEY_AP_ALT_HOLD"],
    "TOGGLE AUTOPILOT VS HOLD": ["KEY_AP_VS_HOLD"],
    "AUTO THROTTLE GO AROUND / TOGA": ["KEY_AUTO_THROTTLE_TO_GA"],
    # Multi-direction controls: bound in order to the control's learned buttons
    "ELEVATOR TRIM UP / DOWN": ["KEY_ELEV_TRIM_UP", "KEY_ELEV_TRIM_DN"],
    "ELEVATOR TRIM AXIS (OR TRIM UP/DOWN)": ["KEY_ELEV_TRIM_UP", "KEY_ELEV_TRIM_DN"],
    "INCREASE / DECREASE FLAPS": ["KEY_FLAPS_INCR", "KEY_FLAPS_DECR"],
    "MAGNETO OFF / RIGHT / LEFT / BOTH / START (PER POSITION)": [
        "KEY_MAGNETO_OFF", "KEY_MAGNETO_RIGHT", "KEY_MAGNETO_LEFT",
        "KEY_MAGNETO_BOTH", "KEY_MAGNETO_START",
    ],
}


@dataclass
class ResolvedWrites:
    actions: list[ActionWrite] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (control, reason)


def resolve_writes(plan_bindings, control_ids: dict[str, str], input_map) -> ResolvedWrites:
    """Turn a device's binding plan into concrete profile writes.

    plan_bindings: list[Binding] for one device
    control_ids:   {control label -> control id} from the DeviceProfile
    input_map:     InputMap with the learned/default physical indices
    """
    from .input_map import AXIS_KEYCODES

    def lookup(label: str) -> str | None:
        if label in control_ids:
            return control_ids[label]
        # tolerate abbreviated labels ("Flap lever" vs "Flap lever (increment up/down)")
        lowered = label.lower()
        for full_label, cid in control_ids.items():
            fl = full_label.lower()
            if fl.startswith(lowered) or lowered.startswith(fl):
                return cid
        return None

    out = ResolvedWrites()
    for b in plan_bindings:
        setting = b.msfs_setting.strip().upper()
        control_id = lookup(b.control)
        if "UNBOUND" in b.assignment.upper() or setting in ("", "—", "-"):
            continue
        if control_id is None:
            out.skipped.append((b.control, "control not in device profile"))
            continue

        if setting in AXIS_ACTIONS:
            axis = input_map.axis_for_control(control_id)
            if axis is None or axis >= len(AXIS_KEYCODES):
                out.skipped.append((b.control, "no axis learned — use Learn mode first"))
                continue
            out.actions.append(ActionWrite(AXIS_ACTIONS[setting], AXIS_KEYCODES[axis], b.control))
            continue

        matched = next((acts for key, acts in BUTTON_ACTIONS.items() if key in setting), None)
        if matched:
            buttons = input_map.buttons_for_control(control_id)
            if len(buttons) < len(matched):
                out.skipped.append(
                    (b.control, f"needs {len(matched)} learned button(s), have {len(buttons)}")
                )
                continue
            for action_name, btn in zip(matched, buttons):
                out.actions.append(
                    ActionWrite(action_name, f"JOYSTICK_BUTTON_{btn + 1}", b.control)
                )
            continue

        out.skipped.append((b.control, "no auto-writable MSFS action — set in the MSFS UI"))
    return out
