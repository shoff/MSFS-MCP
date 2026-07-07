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


class HidAxisDevice:
    """Turn a HID device's raw input reports into normalized axes.

    HID doesn't self-describe its axis layout here, so we parse every 16-bit
    little-endian field of the report as an axis. The fields that actually move
    when you operate the control ARE the real axes — the diagram/raw-view show
    them and calibration maps them, so the device is usable even without the
    report descriptor. A leading constant byte (a report id) is auto-skipped.
    """

    def __init__(self, path) -> None:
        self._reader = HidReader(path)
        self._id_byte = None          # value of a suspected constant report-id byte
        self._id_stable = 0
        self._offset = 0
        self.axes: list[float] = []

    @property
    def ok(self) -> bool:
        return self._reader.ok

    def _update_offset(self, data: list[int]) -> None:
        # A byte-0 that stays constant and non-zero across the first several
        # reports is a HID report id that hidapi prepends; skip it so the 16-bit
        # axis fields align. (We can't use length parity to detect this: hidapi's
        # read length is our 64-byte buffer, not the true report length. The
        # VelocityOne rudder, for instance, streams `01 .. <rudder@5:7> ..`.)
        if self._id_stable >= 6 or not data:
            return
        if self._id_byte is None:
            self._id_byte = data[0]
            self._id_stable = 1
        elif data[0] == self._id_byte:
            self._id_stable += 1
            if self._id_stable >= 6 and self._id_byte != 0:
                self._offset = 1
        else:
            self._id_byte, self._id_stable, self._offset = None, 0, 0

    def poll(self) -> list[float]:
        data = self._reader.read()
        if not data:
            return self.axes
        self._update_offset(data)
        body = data[self._offset:]
        vals = []
        for i in range(0, len(body) - 1, 2):
            raw = body[i] | (body[i + 1] << 8)     # 16-bit little-endian
            vals.append(raw / 32767.5 - 1.0)       # -> roughly -1..1
        self.axes = vals
        return vals

    def close(self) -> None:
        self._reader.close()


def find_for_device(usb_ids, match_names) -> dict | None:
    """Find a HID device matching a DeviceProfile (by USB id, vendor, or product
    name) — used to pick up gear SDL couldn't enumerate.

    A USB id / vendor match is trusted regardless of the reported HID usage page
    (that's the whole point — SDL skipped it because of an odd usage page). The
    name heuristic is only used as a looser fallback for game-like devices.
    """
    vendors = {vid for vid, _pid in usb_ids}
    norm_names = ["".join(ch for ch in n.lower() if ch.isalnum()) for n in match_names]
    devices = enumerate_devices()

    def is_axis_iface(h) -> bool:
        # The axes live on the Generic-Desktop joystick/gamepad interface, NOT on
        # a vendor/config interface. A multi-interface device (e.g. the VelocityOne
        # rudder: MI_00 gamepad + MI_01 vendor page) must be read on the game one.
        return h["usage_page"] == 0x01 and h["usage"] in _GAME_USAGES_GD

    # 1) exact-id or vendor match, PREFERRING the game interface over any others.
    id_matches = [
        h for h in devices
        if (h["vid"], h["pid"]) in usb_ids or (h["vid"] and h["vid"] in vendors)
    ]
    if id_matches:
        game = [h for h in id_matches if is_axis_iface(h)]
        return (game or id_matches)[0]
    # 2) fall back to product-name match on game-like devices
    for h in devices:
        if not h["looks_game"]:
            continue
        prod = "".join(ch for ch in (h["product"] or "").lower() if ch.isalnum())
        if prod and any(n and n in prod for n in norm_names):
            return h
    return None
