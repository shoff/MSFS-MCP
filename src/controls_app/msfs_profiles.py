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


MAX_PROFILE_BYTES = 2_000_000
_HEAD_BYTES = 4096


def _looks_like_profile(path: Path) -> bool:
    try:
        st = path.stat()
        if st.st_size > MAX_PROFILE_BYTES or st.st_size == 0:
            return False
        with path.open("rb") as f:            # read only the head, not the whole file
            head = f.read(_HEAD_BYTES).decode("utf-8", errors="ignore")
    except OSError:
        return False
    return "<Device" in head and ("FriendlyName" in head or "ContextName" in head)


@dataclass
class InputProfile:
    path: Path
    source: str                   # which install it came from
    friendly_name: str
    device_names: list[str] = field(default_factory=list)


# Directory names that never hold an input profile but are enormous — the MSFS
# scenery/package/cache trees. Skipping them (and never descending into a
# junction/symlink) keeps the scan from walking gigabytes and, worse, following
# add-on junctions (e.g. NeoFly in Packages\Community) into other installs.
_SKIP_DIRS = frozenset({
    "packages", "community", "official", "onestore", "sceneryindexes",
    "cache", "rollingcache", "wasm", "weather", "raidumps", "ghosts",
    "simobjects", "missions", "flightplans", "layouts", "texturecache",
})
_MAX_SCAN_FILES = 30000  # backstop so a pathological tree can't hang the scan


def _walk_shallow(root: Path):
    """Yield files under ``root``, pruning the huge MSFS package/cache dirs and
    never following reparse points (junctions/symlinks). Windows ``rglob`` DOES
    follow junctions, which is what made this hang; ``os.walk`` lets us prune."""
    import stat as _stat

    reparse = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        kept = []
        for d in dirnames:
            if d.lower() in _SKIP_DIRS:
                continue
            try:
                attrs = getattr(os.stat(os.path.join(dirpath, d),
                                        follow_symlinks=False), "st_file_attributes", 0)
            except OSError:
                continue
            if attrs & reparse:      # a junction/symlink — don't descend
                continue
            kept.append(d)
        dirnames[:] = kept
        for f in filenames:
            seen += 1
            if seen > _MAX_SCAN_FILES:
                return
            yield Path(dirpath) / f


def find_profiles(extra_roots: list[Path] | None = None) -> list[InputProfile]:
    """Scan the known locations (plus any extra folders) for input profiles.

    Reads only each candidate's 4 KB head, skips oversized/empty files by stat,
    prunes the giant scenery/cache dirs, and never follows junctions — so it
    stays fast (and terminates) even on a big install with add-on junctions.
    """
    profiles: list[InputProfile] = []
    scan: list[tuple[str, Path]] = list(candidate_roots())
    for root in extra_roots or []:
        scan.append(("custom folder", root))
    for source, root in scan:
        if not root.is_dir():
            continue
        for path in _walk_shallow(root):
            name = path.name.lower()
            if not (name.startswith("inputprofile") or "wgs" in str(path).lower()
                    or source == "custom folder"):
                continue
            if not path.is_file() or not _looks_like_profile(path):
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
# Plan -> writable actions  (driven entirely by settings_registry)
# --------------------------------------------------------------------------


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
    from .input_map import AXIS_KEYCODES, lookup_control
    from .settings_registry import spec_for_setting

    out = ResolvedWrites()
    for b in plan_bindings:
        if "UNBOUND" in b.assignment.upper():
            continue
        spec = spec_for_setting(b.msfs_setting)
        if spec is None:
            if b.msfs_setting.strip() not in ("", "—", "-"):
                out.skipped.append((b.control, "no auto-writable MSFS action — set in the MSFS UI"))
            continue
        control_id = lookup_control(b.control, control_ids)
        if control_id is None:
            out.skipped.append((b.control, "control not in device profile"))
            continue

        if spec.kind == "axis":
            axis = input_map.axis_for_control(control_id)
            if axis is None or axis >= len(AXIS_KEYCODES):
                out.skipped.append((b.control, "no axis learned — use Learn mode first"))
                continue
            out.actions.append(ActionWrite(spec.actions[0], AXIS_KEYCODES[axis], b.control))
            continue

        # button spec: bind each action to the control's learned buttons IN ORDER
        buttons = input_map.buttons_for_control(control_id)
        if len(buttons) < len(spec.actions):
            out.skipped.append(
                (b.control, f"needs {len(spec.actions)} learned button(s), have {len(buttons)}"
                            " — use Learn mode")
            )
            continue
        for action_name, btn in zip(spec.actions, buttons):
            out.actions.append(ActionWrite(action_name, f"JOYSTICK_BUTTON_{btn + 1}", b.control))
    return out
