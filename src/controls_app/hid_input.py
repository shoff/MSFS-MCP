"""Direct USB-HID access for devices SDL/pygame can't see.

pygame/SDL only enumerates HID devices whose *usage page* it recognizes
(generic-desktop joystick/gamepad). Some flight peripherals — notably certain
rudder pedals — declare a Simulation-Controls usage page that SDL skips, so
they're invisible to it even though Windows lists them fine. ``hidapi``
enumerates the raw HID bus the way Windows does, so we can SEE those devices and
read their live input-report bytes.

Everything degrades gracefully if the ``hid`` package isn't installed (the
controls extra pulls in ``hidapi``; import name is ``hid``).
"""

from __future__ import annotations

# HID usage: generic-desktop (0x01) joystick(4)/gamepad(5)/multi-axis(8),
# or the Simulation-Controls page (0x02) that trips up SDL.
_GAME_USAGE_PAGES = {0x01, 0x02}
_GAME_USAGES_GD = {0x04, 0x05, 0x08}


def available() -> bool:
    try:
        import hid  # noqa: F401
        return True
    except Exception:
        return False


def looks_like_game_device(usage_page: int, usage: int) -> bool:
    if usage_page == 0x02:  # simulation controls (flight gear often lives here)
        return True
    return usage_page == 0x01 and usage in _GAME_USAGES_GD


def enumerate_devices() -> list[dict]:
    """Every HID device on the bus (like Windows), with game-controller flag."""
    try:
        import hid
    except Exception:
        return []
    out = []
    try:
        for d in hid.enumerate():
            up = int(d.get("usage_page", 0) or 0)
            usage = int(d.get("usage", 0) or 0)
            out.append({
                "vid": d.get("vendor_id"),
                "pid": d.get("product_id"),
                "product": (d.get("product_string") or "").strip(),
                "manufacturer": (d.get("manufacturer_string") or "").strip(),
                "path": d.get("path"),
                "usage_page": up,
                "usage": usage,
                "looks_game": looks_like_game_device(up, usage),
            })
    except Exception:
        return out
    return out


class HidReader:
    """Non-blocking reader for one HID device's input reports (raw bytes)."""

    def __init__(self, path) -> None:
        self._dev = None
        self.last: list[int] = []
        try:
            import hid

            self._dev = hid.device()
            self._dev.open_path(path)
            self._dev.set_nonblocking(True)
        except Exception:
            self._dev = None

    @property
    def ok(self) -> bool:
        return self._dev is not None

    def read(self) -> list[int]:
        if self._dev is None:
            return self.last
        try:
            data = self._dev.read(64)
            if data:
                self.last = list(data)
        except Exception:
            pass
        return self.last

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None
