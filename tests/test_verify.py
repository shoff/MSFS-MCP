"""Verify-condition parser + every shipped verify spec must parse and be sane."""

import pytest

from checklist_app.models import load_aircraft
from checklist_app.verify import Condition, parse_condition, parse_verify, satisfied, vars_needed


def test_parse_basic():
    c = parse_condition("ELECTRICAL_MASTER_BATTERY == 1")
    assert c == Condition("ELECTRICAL_MASTER_BATTERY", "==", 1.0)
    c = parse_condition("GENERAL_ENG_RPM:1 >= 1650")
    assert c.var == "GENERAL_ENG_RPM:1" and c.op == ">=" and c.value == 1650


def test_parse_rejects_garbage():
    for bad in ("import os", "A ==", "== 1", "A ~ 1", "a == 1", "A == 1; B == 2"):
        with pytest.raises(ValueError):
            parse_condition(bad)


def test_evaluation():
    conds = parse_verify(["GENERAL_ENG_RPM:1 >= 800", "GENERAL_ENG_RPM:1 <= 1200"])
    assert satisfied(conds, {"GENERAL_ENG_RPM:1": 1000})
    assert not satisfied(conds, {"GENERAL_ENG_RPM:1": 1500})
    assert not satisfied(conds, {})  # missing var -> not satisfied
    assert not satisfied(conds, {"GENERAL_ENG_RPM:1": {"error": "boom"}})
    assert not satisfied([], {"X": 1})  # no conditions -> never auto-satisfied


def test_equality_uses_epsilon():
    conds = parse_verify("ELECTRICAL_MASTER_BATTERY == 1")
    assert satisfied(conds, {"ELECTRICAL_MASTER_BATTERY": 1.0000001})
    assert satisfied(conds, {"ELECTRICAL_MASTER_BATTERY": True})
    assert not satisfied(conds, {"ELECTRICAL_MASTER_BATTERY": 0})


def test_string_spec_becomes_single_condition():
    conds = parse_verify("PITOT_HEAT == 0")
    assert len(conds) == 1
    assert vars_needed(conds) == {"PITOT_HEAT"}


def test_all_shipped_verify_specs_parse():
    total = 0
    for aircraft in load_aircraft():
        for section in aircraft.sections:
            for item in section.items:
                if not item.verify:
                    continue
                conds = parse_verify(item.verify)  # raises on bad spec
                assert conds, f"{aircraft.name} / {section.name} / {item.challenge}"
                assert item.checkable, "notes must not carry verify specs"
                total += 1
    assert total >= 100  # both aircraft are well covered


def test_sim_checked_resets_with_section():
    aircraft = load_aircraft()[0]
    section = next(s for s in aircraft.sections if any(i.verifiable for i in s.items))
    item = next(i for i in section.items if i.verifiable)
    item.checked = True
    item.sim_checked = True
    section.reset()
    assert not item.checked and not item.sim_checked
