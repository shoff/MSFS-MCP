"""Hardware profiles and detection. No Qt imports so tests stay headless."""

from __future__ import annotations

from dataclasses import dataclass, field

# Input kinds: axis | lever | button | switch | rotary | hat | wheel


@dataclass
class ControlInput:
    id: str
    label: str
    kind: str
    notes: str = ""


@dataclass
class DeviceProfile:
    id: str
    name: str
    manufacturer: str
    # USB vendor/product IDs for exact detection (parsed from the SDL joystick
    # GUID), with name substrings as a fallback when the GUID carries no IDs.
    usb_ids: list[tuple[int, int]] = field(default_factory=list)
    match_names: list[str] = field(default_factory=list)
    inputs: list[ControlInput] = field(default_factory=list)
    always_present: bool = False  # keyboard/mouse

    def matches(self, name: str, vid: int | None = None, pid: int | None = None) -> bool:
        if vid is not None and pid is not None and (vid, pid) in self.usb_ids:
            return True
        lowered = name.lower()
        return any(m.lower() in lowered for m in self.match_names)


HONEYCOMB_ALPHA = DeviceProfile(
    id="honeycomb_alpha",
    name="Alpha Flight Controls (Yoke)",
    manufacturer="Honeycomb Aeronautical",
    usb_ids=[(0x294B, 0x1900)],
    match_names=["alpha flight controls", "honeycomb alpha"],
    inputs=[
        ControlInput("aileron", "Yoke roll (X axis)", "axis"),
        ControlInput("elevator", "Yoke pitch (Y axis)", "axis"),
        ControlInput("ap_disc", "Red button (left horn)", "button"),
        ControlInput("hat", "8-way hat (left thumb)", "hat"),
        ControlInput("rocker_r", "Vertical rocker (right thumb)", "switch"),
        ControlInput("wheel_l", "White button pair (left horn)", "button"),
        ControlInput("wheel_r", "White button pair (right horn)", "button"),
        ControlInput("sw_alt", "ALT rocker (switch panel)", "switch"),
        ControlInput("sw_bat", "BAT rocker (switch panel)", "switch"),
        ControlInput("sw_avionics1", "AVIONICS BUS 1 rocker", "switch"),
        ControlInput("sw_avionics2", "AVIONICS BUS 2 rocker", "switch"),
        ControlInput("sw_light_bcn", "BCN light rocker", "switch"),
        ControlInput("sw_light_land", "LAND light rocker", "switch"),
        ControlInput("sw_light_taxi", "TAXI light rocker", "switch"),
        ControlInput("sw_light_nav", "NAV light rocker", "switch"),
        ControlInput("sw_light_strobe", "STROBE light rocker", "switch"),
        ControlInput("magneto", "Ignition rotary (OFF/R/L/BOTH/START)", "rotary"),
    ],
)

HONEYCOMB_BRAVO = DeviceProfile(
    id="honeycomb_bravo",
    name="Bravo Throttle Quadrant",
    manufacturer="Honeycomb Aeronautical",
    usb_ids=[(0x294B, 0x1901)],
    match_names=["bravo throttle", "honeycomb bravo"],
    inputs=[
        ControlInput("lever1", "Lever 1 (black — throttle handle)", "lever"),
        ControlInput("lever2", "Lever 2 (blue — propeller handle)", "lever"),
        ControlInput("lever3", "Lever 3 (red — mixture handle)", "lever"),
        ControlInput("lever4", "Lever 4", "lever", "Spare in single-engine GA setup"),
        ControlInput("go_around", "GA button (back of throttle handle)", "button"),
        ControlInput("trim_wheel", "Trim wheel", "wheel"),
        ControlInput("flaps", "Flap lever (increment up/down)", "lever"),
        ControlInput("gear", "Landing gear lever", "lever"),
        ControlInput("ap_master", "AUTO PILOT button", "button"),
        ControlInput("ap_hdg", "HDG button", "button"),
        ControlInput("ap_nav", "NAV button", "button"),
        ControlInput("ap_apr", "APR button", "button"),
        ControlInput("ap_rev", "REV button", "button"),
        ControlInput("ap_alt", "ALT button", "button"),
        ControlInput("ap_vs", "VS button", "button"),
        ControlInput("ap_ias", "IAS button", "button"),
        ControlInput("ap_selector", "Rotary selector (IAS/CRS/HDG/VS/ALT)", "rotary"),
        ControlInput("ap_knob", "Increase/decrease knob", "rotary"),
        ControlInput("sw1", "Rocker switch 1", "switch"),
        ControlInput("sw2", "Rocker switch 2", "switch"),
        ControlInput("sw3", "Rocker switch 3", "switch"),
        ControlInput("sw4", "Rocker switch 4", "switch"),
        ControlInput("sw5", "Rocker switch 5", "switch"),
        ControlInput("sw6", "Rocker switch 6", "switch"),
        ControlInput("sw7", "Rocker switch 7", "switch"),
    ],
)

VELOCITYONE_RUDDER = DeviceProfile(
    id="velocityone_rudder",
    name="VelocityOne Rudder (Pedals)",
    manufacturer="Turtle Beach",
    usb_ids=[(0x10F5, 0x7008)],
    match_names=["velocityone rudder", "velocity one rudder", "turtle beach rudder"],
    inputs=[
        ControlInput("rudder", "Rudder axis (slide pedals)", "axis"),
        ControlInput("brake_left", "Left toe brake", "axis"),
        ControlInput("brake_right", "Right toe brake", "axis"),
    ],
)

KEYBOARD_MOUSE = DeviceProfile(
    id="keyboard_mouse",
    name="Keyboard & Mouse",
    manufacturer="—",
    always_present=True,
    inputs=[
        ControlInput("mouse", "Mouse", "button"),
        ControlInput("keys", "Keyboard", "button"),
    ],
)

DEVICES: list[DeviceProfile] = [
    HONEYCOMB_ALPHA,
    HONEYCOMB_BRAVO,
    VELOCITYONE_RUDDER,
    KEYBOARD_MOUSE,
]

DEVICE_BY_ID = {d.id: d for d in DEVICES}


def vid_pid_from_guid(guid: str | None) -> tuple[int | None, int | None]:
    """Extract (vendor, product) from an SDL joystick GUID.

    SDL packs the USB vendor at bytes 4-5 and product at bytes 8-9, each
    little-endian, in the 32-hex-char GUID. Parsing it lets us match hardware
    by its real USB IDs even when the OS reports a generic joystick name
    (drivers and platforms rename devices; the IDs don't move). Returns
    (None, None) for a GUID that carries no USB IDs (e.g. bus type 0).
    """
    if not guid or len(guid) < 20:
        return None, None
    try:
        vendor = int.from_bytes(bytes.fromhex(guid[8:12]), "little")
        product = int.from_bytes(bytes.fromhex(guid[16:20]), "little")
    except ValueError:
        return None, None
    if vendor == 0:
        return None, None
    return vendor, product


def detect_connected() -> dict[str, bool]:
    """Return {device_id: detected} using pygame's joystick list if available.

    Matches by USB VID/PID (from the SDL GUID) first, then by name substring.
    Keyboard/mouse is always True. Runs headless-safe: any pygame problem
    (not installed, no SDL) degrades to "nothing detected".
    """
    detected = {d.id: d.always_present for d in DEVICES}
    try:
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        pygame.init()
        pygame.joystick.init()
        sticks = []  # (name, vid, pid)
        for i in range(pygame.joystick.get_count()):
            stick = pygame.joystick.Joystick(i)
            guid = stick.get_guid() if hasattr(stick, "get_guid") else None
            vid, pid = vid_pid_from_guid(guid)
            sticks.append((stick.get_name(), vid, pid))
        pygame.joystick.quit()
        for device in DEVICES:
            if device.always_present:
                continue
            detected[device.id] = any(device.matches(n, vid, pid) for n, vid, pid in sticks)
    except Exception:
        pass
    return detected
