"""Validate the aircraft checklist data files (no GUI required)."""

import pytest

from checklist_app.models import GROUP_ORDER, load_aircraft


@pytest.fixture(scope="module")
def fleet():
    return load_aircraft()


def test_expected_aircraft_present(fleet):
    names = {a.name for a in fleet}
    assert "Cessna 172S Skyhawk" in names
    assert "Piper PA-28-181 Archer II" in names


def test_every_aircraft_has_core_phases(fleet):
    for aircraft in fleet:
        section_names = " | ".join(s.name.lower() for s in aircraft.sections)
        assert "preflight" in section_names, aircraft.name
        assert "landing" in section_names, aircraft.name
        groups = {s.group for s in aircraft.sections}
        assert "Normal" in groups, aircraft.name
        assert "Emergency" in groups, aircraft.name


def test_items_are_well_formed(fleet):
    for aircraft in fleet:
        assert aircraft.vspeeds, aircraft.name
        for label, value in aircraft.vspeeds:
            assert label and value
        for section in aircraft.sections:
            assert section.group in GROUP_ORDER, section.name
            assert section.items, section.name
            for item in section.items:
                assert item.challenge, f"{aircraft.name} / {section.name}"
                if item.checkable:
                    assert item.response, f"{aircraft.name} / {section.name} / {item.challenge}"
                else:
                    assert item.kind == "note"


def test_groups_are_ordered(fleet):
    for aircraft in fleet:
        indices = [GROUP_ORDER.index(s.group) for s in aircraft.sections]
        assert indices == sorted(indices), aircraft.name


def test_progress_tracking(fleet):
    section = fleet[0].sections[0]
    assert section.done_count == 0
    section.checkable_items[0].checked = True
    assert section.done_count == 1
    assert not section.complete
    for item in section.checkable_items:
        item.checked = True
    assert section.complete
    section.reset()
    assert section.done_count == 0
