"""Raw-HID device matching and axis parsing (no real hardware needed).

Pinned to what the real VelocityOne rudder reports (VID 0x10F5, PID 0x7012):
two interfaces — a vendor page (0xff01) and a Generic-Desktop gamepad (0x01/0x05)
that carries the axes — and 64-byte input reports led by a 0x01 report id, with
the rudder as a centered 16-bit field.
"""

from controls_app import hid_input
from controls_app.hid_input import HidAxisDevice


def _iface(vid, pid, up, us, product="VelocityOne Rudder", path=b"p"):
    return {
        "vid": vid, "pid": pid, "product": product, "manufacturer": "Turtle Beach",
        "path": path, "usage_page": up, "usage": us,
        "looks_game": hid_input.looks_like_game_device(up, us),
    }


def test_find_prefers_gamepad_interface_over_vendor_page(monkeypatch):
    # Order matters: the vendor page comes FIRST in enumeration, like the real
    # device — the picker must still choose the gamepad interface.
    vendor = _iface(0x10F5, 0x7012, 0xFF01, 0x01, path=b"vendor")
    gamepad = _iface(0x10F5, 0x7012, 0x01, 0x05, path=b"gamepad")
    monkeypatch.setattr(hid_input, "enumerate_devices", lambda: [vendor, gamepad])

    match = hid_input.find_for_device([(0x10F5, 0x7012)], ["velocityone rudder"])
    assert match["path"] == b"gamepad"


def test_find_matches_by_vendor_when_pid_differs(monkeypatch):
    # PID guesses drift; a vendor-only match must still work (and pick the game one).
    gamepad = _iface(0x10F5, 0x9999, 0x01, 0x04, path=b"gp")
    monkeypatch.setattr(hid_input, "enumerate_devices", lambda: [gamepad])
    match = hid_input.find_for_device([(0x10F5, 0x7008)], [])
    assert match is not None and match["path"] == b"gp"


def test_find_returns_none_when_absent(monkeypatch):
    other = _iface(0x046D, 0xC08B, 0x01, 0x02, product="Some Mouse")
    monkeypatch.setattr(hid_input, "enumerate_devices", lambda: [other])
    assert hid_input.find_for_device([(0x10F5, 0x7012)], ["rudder"]) is None


class _FakeReader:
    def __init__(self, frame):
        self.frame = frame
        self.ok = True

    def read(self):
        return self.frame

    def close(self):
        pass


def test_report_id_byte_is_stripped_and_rudder_reads_centered():
    # Real resting report: 0x01 report id, brakes at 0x0000, rudder at 0x7fff.
    report = [0x01, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x7F] + [0x00] * 57
    dev = HidAxisDevice(b"unused")     # HidReader fails on a bogus path; we swap it
    dev._reader = _FakeReader(report)

    axes = []
    for _ in range(8):                 # let the report-id detector settle (>=6)
        axes = dev.poll()
    assert dev._offset == 1            # the constant 0x01 lead byte was skipped
    # With the byte stripped, fields align: brakes released (-1), rudder centered.
    assert abs(axes[0] - (-1.0)) < 0.01   # brake_left
    assert abs(axes[1] - (-1.0)) < 0.01   # brake_right
    assert abs(axes[2] - 0.0) < 0.001     # rudder — the whole point


def test_zero_lead_byte_is_not_treated_as_report_id():
    # A constant *zero* first byte is ambiguous (could be an axis LSB) — don't
    # strip it, or a device with no report id would misalign.
    report = [0x00, 0x00, 0x80, 0x7F] + [0x00] * 60
    dev = HidAxisDevice(b"unused")
    dev._reader = _FakeReader(report)
    for _ in range(8):
        dev.poll()
    assert dev._offset == 0
