"""Live joystick polling -> Qt signals. Drives the device visualizers."""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .devices import DEVICES, vid_pid_from_guid

POLL_MS = 33  # ~30 Hz
AXIS_EPSILON = 0.01


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

    def rescan(self) -> None:
        """Re-enumerate joysticks and match them to known device profiles."""
        if not self._pygame:
            return
        pygame = self._pygame
        pygame.joystick.quit()
        pygame.joystick.init()
        self._sticks.clear()
        self._state.clear()
        for i in range(pygame.joystick.get_count()):
            stick = pygame.joystick.Joystick(i)
            stick.init()
            name = stick.get_name()
            guid = stick.get_guid() if hasattr(stick, "get_guid") else None
            vid, pid = vid_pid_from_guid(guid)
            for device in DEVICES:
                if device.always_present or device.id in self._sticks:
                    continue
                if device.matches(name, vid, pid):
                    self._sticks[device.id] = stick
                    self._state[device.id] = {
                        "buttons": [False] * stick.get_numbuttons(),
                        "axes": [0.0] * stick.get_numaxes(),
                        "hats": [(0, 0)] * stick.get_numhats(),
                    }
                    break
        detected = {d.id: (d.always_present or d.id in self._sticks) for d in DEVICES}
        self.devices_changed.emit(detected)

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
