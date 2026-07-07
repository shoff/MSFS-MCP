"""Physical input map: ordered button slots and two-position switch direction."""

from pathlib import Path

from controls_app.input_map import DEFAULT_MAPS, InputMap, load_maps


def _switch_direction(imap: InputMap, control_id: str, index: int, pressed: bool):
    """Mirror app._on_button's rule: slot 0 == up (+1), slot 1 == down (-1),
    release == neutral (0). Returns None when the control isn't a two-slot
    switch (the diagram should then fall back to a plain pressed state)."""
    slots = imap.buttons_for_control(control_id)
    if len(slots) < 2:
        return None
    slot = imap.button_slot(control_id, index)
    return (1 if slot == 0 else -1) if pressed else 0


def _bravo_map() -> InputMap:
    return InputMap("honeycomb_bravo", DEFAULT_MAPS["honeycomb_bravo"])


def test_button_slot_reports_ordered_position():
    imap = _bravo_map()
    # sw1 defaults to [32, 33] -> 32 is the up slot, 33 the down slot.
    assert imap.button_slot("sw1", 32) == 0
    assert imap.button_slot("sw1", 33) == 1
    assert imap.button_slot("sw1", 99) is None
    assert imap.button_slot("nonexistent", 32) is None


def test_rocker_up_and_down_render_differently():
    imap = _bravo_map()
    # The whole point of the fix: the two buttons of one rocker must NOT collapse
    # to the same visual state.
    assert _switch_direction(imap, "sw1", 32, pressed=True) == 1    # flipped up
    assert _switch_direction(imap, "sw1", 33, pressed=True) == -1   # flipped down
    assert _switch_direction(imap, "sw1", 32, pressed=False) == 0   # released


def test_single_button_switch_falls_back_to_pressed():
    # A switch the user re-learned as a single button has no up/down split;
    # the direction helper declines so the diagram uses a plain pressed state.
    imap = InputMap("honeycomb_bravo", {"axes": {}, "buttons": {"sw1": [32]}, "hats": {}})
    assert _switch_direction(imap, "sw1", 32, pressed=True) is None


def test_relearn_replaces_switch_mapping_in_order():
    imap = _bravo_map()
    imap.set_control_buttons("sw1", [50, 51])   # re-learned UP then DOWN
    assert imap.buttons_for_control("sw1") == [50, 51]
    assert imap.button_slot("sw1", 50) == 0
    assert imap.button_slot("sw1", 51) == 1
    # the new indices are stolen from any other control that had them
    for cid, idxs in imap.buttons.items():
        if cid != "sw1":
            assert 50 not in idxs and 51 not in idxs


def test_all_default_bravo_switches_have_two_slots():
    # Guards the assumption behind up/down rendering: shipped rocker defaults are
    # two-button. If a default drops to one slot, up/down silently stops working.
    imap = load_maps(user_path=Path("/nonexistent"))["honeycomb_bravo"]
    for n in range(1, 8):
        assert len(imap.buttons_for_control(f"sw{n}")) == 2, f"sw{n} lost its down slot"
