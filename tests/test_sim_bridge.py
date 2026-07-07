"""SimConnect bridge: axis scaling and plan -> live-event route resolution."""

import threading
import time
from pathlib import Path

import pytest

from controls_app.bindings import load_default_plans
from controls_app.devices import HONEYCOMB_BRAVO, VELOCITYONE_RUDDER
from controls_app.input_map import load_maps
from controls_app.sim_bridge import (
    AXIS_FULL,
    event_from_action,
    resolve_bridge_routes,
    scale_axis,
)


def test_event_from_action_strips_key_prefix():
    assert event_from_action("KEY_AXIS_RUDDER_SET") == "AXIS_RUDDER_SET"
    assert event_from_action("KEY_FLAPS_INCR") == "FLAPS_INCR"
    assert event_from_action("AP_MASTER") == "AP_MASTER"  # already bare


def test_scale_axis_signed_is_symmetric():
    assert scale_axis(0.0, "signed") == 0
    assert scale_axis(1.0, "signed") == AXIS_FULL
    assert scale_axis(-1.0, "signed") == -AXIS_FULL
    assert scale_axis(2.0, "signed") == AXIS_FULL      # clamped
    assert scale_axis(-9.0, "signed") == -AXIS_FULL    # clamped


def test_scale_axis_unsigned_maps_to_zero_full():
    assert scale_axis(-1.0, "unsigned") == 0
    assert scale_axis(0.0, "unsigned") == AXIS_FULL // 2 + 1  # midpoint rounds up
    assert scale_axis(1.0, "unsigned") == AXIS_FULL


def _routes_for(device, device_id, aircraft="c172s"):
    plan = load_default_plans()[aircraft]
    imap = load_maps(user_path=Path("/nonexistent"))[device_id]
    control_ids = {c.label: c.id for c in device.inputs}
    return resolve_bridge_routes(plan.devices[device_id], control_ids, imap)


def test_rudder_pedals_route_to_simconnect_events():
    # The whole reason the bridge exists: the SDL-invisible pedals get live events.
    routes = _routes_for(VELOCITYONE_RUDDER, "velocityone_rudder")
    events = {r.event for r in routes.axes.values()}
    assert "RUDDER_SET" in events
    assert "AXIS_LEFT_BRAKE_SET" in events
    assert "AXIS_RIGHT_BRAKE_SET" in events
    # rudder axis is a centered, signed control
    rudder = next(r for r in routes.axes.values() if r.event == "RUDDER_SET")
    assert rudder.mode == "signed"


def test_bravo_axes_and_buttons_resolve():
    routes = _routes_for(HONEYCOMB_BRAVO, "honeycomb_bravo")
    axis_events = {r.event for r in routes.axes.values()}
    assert "THROTTLE_SET" in axis_events
    assert "MIXTURE_SET" in axis_events
    # flaps is a two-action button -> both increments map to their own buttons
    button_events = {r.event for r in routes.buttons.values()}
    assert "FLAPS_INCR" in button_events and "FLAPS_DECR" in button_events


def test_unlearned_axis_is_skipped_not_routed():
    # An empty map (nothing learned) yields no axis routes and records why.
    from controls_app.input_map import InputMap

    empty = InputMap("velocityone_rudder", {"axes": {}, "buttons": {}, "hats": {}})
    plan = load_default_plans()["c172s"]
    control_ids = {c.label: c.id for c in VELOCITYONE_RUDDER.inputs}
    routes = resolve_bridge_routes(plan.devices["velocityone_rudder"], control_ids, empty)
    assert not routes.axes
    assert routes.skipped  # each control noted as needing Learn/Calibrate


class _FakeClient:
    """Stands in for SimConnectClient: records triggers, no real sim."""

    def __init__(self):
        self.connected = True
        self.calls = []

    def connect(self):
        self.connected = True
        return {}

    def disconnect(self):
        self.connected = False

    def trigger(self, name, value=None):
        self.calls.append((name, value))


def test_bridge_worker_thread_fires_events():
    # Exercises the real QThread run/drain loop with a fake client — proves an
    # axis value and a button edge both reach SimConnect off the GUI thread.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6", reason="PyQt6 not installed (GUI extra)")
    from PyQt6.QtWidgets import QApplication

    from controls_app.sim_bridge import SimBridge

    _ = QApplication.instance() or QApplication([])
    bridge = SimBridge()
    fake = _FakeClient()
    bridge._make_client = lambda: fake  # inject the fake connection

    bridge.start()
    try:
        bridge.set_enabled(True)
        bridge.submit_axis("RUDDER_SET", 16383)
        bridge.submit_button("FLAPS_INCR")
        deadline = time.monotonic() + 3.0
        while len(fake.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        bridge.stop()
        bridge.wait(3000)

    assert ("RUDDER_SET", 16383) in fake.calls
    assert ("FLAPS_INCR", None) in fake.calls


def test_bridge_disabled_sends_nothing():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6", reason="PyQt6 not installed (GUI extra)")
    from PyQt6.QtWidgets import QApplication

    from controls_app.sim_bridge import SimBridge

    _ = QApplication.instance() or QApplication([])
    bridge = SimBridge()
    fake = _FakeClient()
    bridge._make_client = lambda: fake
    bridge.start()
    try:
        # never enabled: submits are dropped, nothing is triggered
        bridge.submit_axis("RUDDER_SET", 5000)
        bridge.submit_button("FLAPS_INCR")
        time.sleep(0.3)
    finally:
        bridge.stop()
        bridge.wait(3000)
    assert fake.calls == []
