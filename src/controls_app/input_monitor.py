"""Live joystick polling -> Qt signals. Drives the device visualizers."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .devices import DEVICES, vid_pid_from_guid

POLL_MS = 33  # ~30 Hz
AXIS_EPSILON = 0.01

# Manual device assignments persist here, keyed by the joystick *name* SDL
# reports (indices shuffle between sessions; the name is stable), so a device
# the app can't auto-detect stays assigned across launches.
ASSIGN_PATH = Path.home() / ".msfs_companion" / "device_assignments.json"


def _load_assignments() -> dict[str, str]:
    try:
        data = json.loads(ASSIGN_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_assignments(data: dict[str, str]) -> None:
    try:
        ASSIGN_PATH.parent.mkdir(parents=True, exist_ok=True)
        ASSIGN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


class InputMonitor(QObject):
    """Polls pygame joysticks and emits per-device input events.

    Signals carry the *device_id* from our DeviceProfile registry plus the raw
    pygame index — mapping raw indices to logical controls is the InputMap's
    job, so Learn mode can watch the same signals.
    """

    button_changed = pyqtSignal(str, int, bool)      # device_id, button index, pressed
    axis_changed = pyqtSignal(str, int, float)       # device_id, axis index, value -1..1
    hat_changed = pyqtSignal(str, int, int, int)     # device_id, hat index, x, y
    devices_changed = pyqtSignal(dict)               # device_id -> detected

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pygame = None
        self._sticks: dict[str, object] = {}     # device_id -> pygame joystick
        self._state: dict[str, dict] = {}        # device_id -> {buttons: [], axes: [], hats: []}
        self._manual: dict[str, str] = _load_assignments()  # device_id -> joystick name
        self.available = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    def start(self) -> None:
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            import pygame

            pygame.init()
            pygame.joystick.init()
            self._pygame = pygame
            self.available = True
        except Exception:
            self.available = False
            return
        self.rescan()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._pygame:
            try:
                self._pygame.joystick.quit()
            except Exception:
                pass

    def _bind(self, device_id: str, stick) -> None:
        self._sticks[device_id] = stick
        self._state[device_id] = {
            "buttons": [False] * stick.get_numbuttons(),
            "axes": [0.0] * stick.get_numaxes(),
            "hats": [(0, 0)] * stick.get_numhats(),
        }

    def rescan(self) -> None:
        """Re-enumerate joysticks and match them to known device profiles.

        Manual assignments (see ``assign``) win over automatic name/USB
        matching, so a device the app doesn't recognize can still be driven.
        """
        if not self._pygame:
            return
        pygame = self._pygame
        pygame.joystick.quit()
        pygame.joystick.init()
        self._sticks.clear()
        self._state.clear()

        sticks = {}
        for i in range(pygame.joystick.get_count()):
            stick = pygame.joystick.Joystick(i)
            stick.init()
            sticks[i] = stick

        used: set[int] = set()
        # 1) manual overrides first (matched by the joystick's stable name)
        for device_id, want_name in self._manual.items():
            for i, stick in sticks.items():
                if i not in used and stick.get_name() == want_name:
                    self._bind(device_id, stick)
                    used.add(i)
                    break
        # 2) automatic name / USB-id matching for the rest
        for i, stick in sticks.items():
            if i in used:
                continue
            name = stick.get_name()
            guid = stick.get_guid() if hasattr(stick, "get_guid") else None
            vid, pid = vid_pid_from_guid(guid)
            for device in DEVICES:
                if device.always_present or device.id in self._sticks:
                    continue
                if device.matches(name, vid, pid):
                    self._bind(device.id, stick)
                    used.add(i)
                    break
        detected = {d.id: (d.always_present or d.id in self._sticks) for d in DEVICES}
        self.devices_changed.emit(detected)

    def assign(self, device_id: str, joystick_name: str | None) -> None:
        """Force a physical joystick (by its SDL name) to drive a device slot,
        or pass None to clear. Persists across launches and takes effect now."""
        if joystick_name is None:
            self._manual.pop(device_id, None)
        else:
            self._manual[device_id] = joystick_name
        _save_assignments(self._manual)
        self.rescan()

    def raw_snapshot(self) -> list[dict]:
        """Live state of EVERY connected joystick, matched or not — the data the
        diagnostics view renders so the user can see what the app actually sees."""
        if not self._pygame:
            return []
        pygame = self._pygame
        try:
            pygame.event.pump()
        except Exception:
            return []
        out = []
        for i in range(pygame.joystick.get_count()):
            try:
                stick = pygame.joystick.Joystick(i)
                if hasattr(stick, "get_init") and not stick.get_init():
                    stick.init()
                name = stick.get_name()
                guid = stick.get_guid() if hasattr(stick, "get_guid") else None
                vid, pid = vid_pid_from_guid(guid)
                matched = next(
                    (d.id for d in DEVICES
                     if not d.always_present and d.matches(name, vid, pid)),
                    None,
                )
                # honor a manual override (by name) in what we report as matched
                for dev_id, nm in self._manual.items():
                    if nm == name:
                        matched = dev_id
                out.append({
                    "index": i, "name": name, "guid": guid, "vid": vid, "pid": pid,
                    "matched": matched,
                    "axes": [round(stick.get_axis(a), 2) for a in range(stick.get_numaxes())],
                    "buttons": [b for b in range(stick.get_numbuttons()) if stick.get_button(b)],
                    "num_buttons": stick.get_numbuttons(),
                    "hats": [stick.get_hat(h) for h in range(stick.get_numhats())],
                })
            except Exception:
                continue
        return out

    # ------------------------------------------------------------------
    def _poll(self) -> None:
        if not self._pygame:
            return
        try:
            self._pygame.event.pump()
        except Exception:
            return
        for device_id, stick in self._sticks.items():
            state = self._state[device_id]
            for i in range(len(state["buttons"])):
                pressed = bool(stick.get_button(i))
                if pressed != state["buttons"][i]:
                    state["buttons"][i] = pressed
                    self.button_changed.emit(device_id, i, pressed)
            for i in range(len(state["axes"])):
                value = float(stick.get_axis(i))
                if abs(value - state["axes"][i]) > AXIS_EPSILON:
                    state["axes"][i] = value
                    self.axis_changed.emit(device_id, i, value)
            for i in range(len(state["hats"])):
                hat = stick.get_hat(i)
                if hat != state["hats"][i]:
                    state["hats"][i] = hat
                    self.hat_changed.emit(device_id, i, hat[0], hat[1])
