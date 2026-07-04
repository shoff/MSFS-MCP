"""Platform-independent tests — catalog integrity and graceful degradation.

These run anywhere (including this Linux container): they don't need MSFS,
SimConnect, FSUIPC, or pymem. They verify the catalog is well-formed and that
each layer reports cleanly when it can't service a request.
"""

from __future__ import annotations

from msfs_mcp import catalog
from msfs_mcp.simconnect_client import LayerUnavailable, SimConnectClient


def test_simvars_unique_and_well_formed():
    names = [s.name for s in catalog.SIMVARS]
    assert len(names) == len(set(names)), "duplicate SimVar names"
    for s in catalog.SIMVARS:
        assert s.name and s.units and s.category and s.description
        assert isinstance(s.settable, bool)


def test_events_unique_and_well_formed():
    names = [e.name for e in catalog.EVENTS]
    assert len(names) == len(set(names)), "duplicate event names"
    for e in catalog.EVENTS:
        assert e.name and e.category and e.description
        assert isinstance(e.takes_value, bool)


def test_search_simvars_by_keyword_and_category():
    assert any("ALTITUDE" in s.name for s in catalog.search_simvars("altitude"))
    assert all(s.category == "autopilot" for s in catalog.search_simvars(category="autopilot"))
    assert catalog.search_simvars("definitely-not-a-var") == []


def test_search_events_by_keyword():
    assert any(e.name == "GEAR_TOGGLE" for e in catalog.search_events("gear"))


def test_categories_exposed():
    assert "autopilot" in catalog.SIMVAR_CATEGORIES
    assert "engine" in catalog.EVENT_CATEGORIES


def test_simconnect_degrades_gracefully_off_windows():
    # On a non-Windows host the import fails; a read must raise LayerUnavailable,
    # never an unguarded exception.
    client = SimConnectClient()
    if client._import_error is None:
        # On Windows without a running sim, connect() should still fail cleanly.
        try:
            client.connect()
        except LayerUnavailable:
            pass
        return
    try:
        client.get("PLANE_ALTITUDE")
        assert False, "expected LayerUnavailable"
    except LayerUnavailable as exc:
        assert "Windows" in str(exc) or "unavailable" in str(exc)


def test_status_shape():
    st = SimConnectClient().status()
    assert set(st) >= {"layer", "enabled", "import_ok", "connected"}
