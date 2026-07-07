"""Drive MSFS directly from the hardware the app reads.

The normal flow is: write bindings into an MSFS input profile and let the sim
read the device itself. That CANNOT work for a device the sim can't enumerate
(the VelocityOne rudder pedals, read here off the raw USB-HID bus) — MSFS has no
device to bind. The bridge closes that gap: it takes the same live input events
the diagram already receives and pushes them straight into the sim as SimConnect
events (``RUDDER_SET``, ``THROTTLE_SET``, ``FLAPS_INCR`` …). The pedals then fly
the aircraft even though MSFS never saw them.

Two halves:
  * ``resolve_bridge_routes`` — pure. Turns a device's plan + learned InputMap
    into ``{axis_index -> event}`` / ``{button_index -> event}`` routes, reusing
    the one canonical ``settings_registry`` so the bridge, the profile writer and
    the verifier can never disagree about what a control does.
  * ``SimBridge`` — a worker thread that owns the SimConnect connection and fires
    those events. All connect/retry happens off the GUI thread; the GUI only ever
    hands it already-resolved (event, value) pairs, coalesced per axis.

SimConnect axis SET value conventions (from the SDK / catalog):
  signed   -16383..16383  ailerons, elevator, rudder
  unsigned      0..16383  throttle, mixture, brakes
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal

AXIS_FULL = 16383

# Canonical spec id -> (SimConnect event, value mode). These prefer the plain
# ``*_SET`` events (documented in catalog.py) over the raw ``AXIS_*_SET`` forms.
# Anything not listed falls back to stripping the profile action's KEY_ prefix
# and a signed range — safe for the symmetric flight-control axes.
AXIS_EVENTS: dict[str, tuple[str, str]] = {
    "aileron_axis": ("AILERON_SET", "signed"),
    "elevator_axis": ("ELEVATOR_SET", "signed"),
    "rudder_axis": ("RUDDER_SET", "signed"),
    "throttle_axis": ("THROTTLE_SET", "unsigned"),
    "mixture_axis": ("MIXTURE_SET", "unsigned"),
    "left_brake_axis": ("AXIS_LEFT_BRAKE_SET", "unsigned"),
    "right_brake_axis": ("AXIS_RIGHT_BRAKE_SET", "unsigned"),
}


def event_from_action(action: str) -> str:
    """Profile action name (KEY_FLAPS_INCR) -> SimConnect event (FLAPS_INCR)."""
    return action[4:] if action.startswith("KEY_") else action


def scale_axis(value: float, mode: str) -> int:
    """Map a pygame/HID axis (-1..1) to a SimConnect axis value."""
    v = max(-1.0, min(1.0, value))
    if mode == "unsigned":
        return int(round((v + 1.0) / 2.0 * AXIS_FULL))
    return int(round(v * AXIS_FULL))


@dataclass
class AxisRoute:
    axis_index: int
    event: str
    mode: str
    control: str


@dataclass
class ButtonRoute:
    button_index: int
    event: str
    control: str


@dataclass
class DeviceRoutes:
    axes: dict[int, AxisRoute] = field(default_factory=dict)
    buttons: dict[int, ButtonRoute] = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (control, reason)

    def __bool__(self) -> bool:
        return bool(self.axes or self.buttons)


def resolve_bridge_routes(plan_bindings, control_ids: dict[str, str], input_map) -> DeviceRoutes:
    """Physical input index -> SimConnect event, for one device.

    Mirrors ``msfs_profiles.resolve_writes`` but emits live-event routes instead
    of profile writes, so the bridge binds exactly what the writer would have.
    """
    from .input_map import lookup_control
    from .settings_registry import spec_for_setting

    routes = DeviceRoutes()
    for b in plan_bindings:
        if "UNBOUND" in b.assignment.upper():
            continue
        spec = spec_for_setting(b.msfs_setting)
        if spec is None:
            continue
        control_id = lookup_control(b.control, control_ids)
        if control_id is None:
            continue

        if spec.kind == "axis":
            idx = input_map.axis_for_control(control_id)
            if idx is None:
                routes.skipped.append((b.control, "no axis learned — use Learn/Calibrate"))
                continue
            event, mode = AXIS_EVENTS.get(
                spec.canonical, (event_from_action(spec.actions[0]), "signed")
            )
            routes.axes[idx] = AxisRoute(idx, event, mode, b.control)
            continue

        buttons = input_map.buttons_for_control(control_id)
        if len(buttons) < len(spec.actions):
            routes.skipped.append((b.control, "buttons not learned — use Learn"))
            continue
        for action, btn in zip(spec.actions, buttons):
            routes.buttons[btn] = ButtonRoute(btn, event_from_action(action), b.control)
    return routes


class SimBridge(QThread):
    """Owns the SimConnect link and fires control events off the GUI thread."""

    state_changed = pyqtSignal(str)      # disabled | offline | connecting | live
    action_sent = pyqtSignal(str, int)   # event, value (0 for valueless events)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._enabled = False
        self._axis_targets: dict[str, int] = {}   # event -> latest value (coalesced)
        self._axis_sent: dict[str, int] = {}      # event -> last value actually sent
        self._buttons: list[tuple[str, int | None]] = []  # edge events, never dropped
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._client = None
        self._state = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------- control
    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        if not on:
            with self._lock:
                self._axis_sent.clear()
                self._axis_targets.clear()
                self._buttons.clear()
        self._wake.set()

    def submit_axis(self, event: str, value_int: int) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._axis_targets[event] = value_int
        self._wake.set()

    def submit_button(self, event: str, value: int | None = None) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._buttons.append((event, value))
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # -------------------------------------------------------------- worker
    def _emit_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _make_client(self):
        try:
            from msfs_mcp.simconnect_client import SimConnectClient

            return SimConnectClient()
        except Exception:
            return None

    def _send(self, client, event: str, value: int | None) -> bool:
        try:
            client.trigger(event, value)
        except Exception:
            return False
        self.action_sent.emit(event, value if value is not None else 0)
        return True

    def run(self):  # noqa: C901 - a plain connect/drain loop
        while not self._stop.is_set():
            if not self._enabled:
                self._emit_state("disabled")
                self._wake.wait(timeout=0.25)
                self._wake.clear()
                continue

            if self._client is None:
                self._client = self._make_client()
            client = self._client
            if client is None:
                self._emit_state("offline")
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue

            if not client.connected:
                self._emit_state("connecting")
                try:
                    client.connect()
                except Exception:
                    self._emit_state("offline")
                    self._wake.wait(timeout=2.0)
                    self._wake.clear()
                    continue
            self._emit_state("live")

            with self._lock:
                buttons = self._buttons
                self._buttons = []
                axes = dict(self._axis_targets)

            ok = True
            for event, value in buttons:
                ok = self._send(client, event, value) and ok
            for event, value in axes.items():
                if self._axis_sent.get(event) != value:
                    if self._send(client, event, value):
                        self._axis_sent[event] = value
                    else:
                        ok = False

            if not ok:
                # A trigger failed — assume the sim went away and reconnect.
                try:
                    client.disconnect()
                except Exception:
                    pass
                self._axis_sent.clear()
                self._emit_state("offline")
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue

            self._wake.wait(timeout=0.03)  # ~30 Hz, matches the input poll
            self._wake.clear()
