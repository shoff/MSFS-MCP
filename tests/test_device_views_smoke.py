"""Offscreen render smoke for the device diagram — proves the switch up/down
paint branch is exercised without crashing. Skipped where PyQt6 is absent."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6", reason="PyQt6 not installed (GUI extra)")

from PyQt6.QtGui import QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from controls_app.device_views import DeviceView, _bravo  # noqa: E402


@pytest.fixture(scope="module")
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


def _render(view: DeviceView) -> None:
    view.render(QPixmap(view.size()))


def test_switch_directions_render(_app):
    elements, decor = _bravo()
    view = DeviceView("honeycomb_bravo", elements, decor)
    view.resize(1000, 460)

    for direction, lit in ((1, True), (-1, True), (0, False)):
        view.set_switch("sw1", direction)
        assert view.switch_dir["sw1"] == direction
        assert view.pressed["sw1"] is lit
        _render(view)  # must not raise

    # the legacy single-boolean path still renders for controls with no direction
    view.set_pressed("sw2", True)
    _render(view)


def test_calibrated_border_state(_app):
    elements, decor = _bravo()
    view = DeviceView("honeycomb_bravo", elements, decor)
    view.resize(1000, 460)

    assert "lever1" not in view.calibrated
    view.set_calibrated("lever1")
    assert "lever1" in view.calibrated      # green border, stays
    _render(view)                            # renders with the green pen
    view.set_calibrated("lever1", done=False)
    assert "lever1" not in view.calibrated
    view.set_calibrated("lever2")
    view.clear_calibrated()                  # fresh run wipes all green
    assert not view.calibrated


def test_yoke_grip_switches_are_three_position(_app):
    from controls_app.device_views import _alpha
    from controls_app.devices import DEVICE_BY_ID

    # LEFT grip pushes forward/back (vertical), RIGHT grip pushes left/right (horizontal).
    expect = {
        "left_rocker_l": "switch3", "left_rocker_r": "switch3",
        "right_rocker_top": "switch3h", "right_rocker_bot": "switch3h",
    }
    model = {c.id: c.kind for c in DEVICE_BY_ID["honeycomb_alpha"].inputs}
    assert {g: model[g] for g in expect} == expect
    elements, decor = _alpha()
    ekind = {e.id: e.kind for e in elements}
    assert {g: ekind[g] for g in expect} == expect

    view = DeviceView("honeycomb_alpha", elements, decor)
    view.resize(1000, 460)
    _render(view)                       # at rest (no switch_dir) -> center neutral, must render
    for cid in ("left_rocker_l", "right_rocker_top"):
        for d in (1, -1, 0):            # fwd/back or left/right, then spring-centered
            view.set_switch(cid, d)
            _render(view)


def test_toggle_switch_flips_position(_app):
    elements, decor = _bravo()
    view = DeviceView("honeycomb_bravo", elements, decor)
    # neutral -> up -> down -> up (click to sync a maintained switch)
    assert view.toggle_switch("sw1") == 1
    assert view.switch_dir["sw1"] == 1
    assert view.toggle_switch("sw1") == -1
    assert view.toggle_switch("sw1") == 1
    _render(view)
