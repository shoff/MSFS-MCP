"""Flight recorder: event detection, exceedances, summary shape (pure logic)."""

import json

from checklist_app.debrief import build_prompt
from checklist_app.flight_log import FlightRecorder, parse_limits
from checklist_app.models import load_aircraft


def c172_recorder() -> FlightRecorder:
    aircraft = next(a for a in load_aircraft() if "172" in a.name)
    rec = FlightRecorder()
    rec.set_aircraft(aircraft.name, aircraft.vspeeds)
    return rec


def sample(on_ground, ias, alt, combustion=1, flaps=0, rpm=2300):
    return {
        "SIM_ON_GROUND": on_ground,
        "AIRSPEED_INDICATED": ias,
        "INDICATED_ALTITUDE": alt,
        "GENERAL_ENG_COMBUSTION:1": combustion,
        "FLAPS_HANDLE_INDEX": flaps,
        "GENERAL_ENG_RPM:1": rpm,
        "GENERAL_ENG_THROTTLE_LEVER_POSITION:1": 100,
        "GENERAL_ENG_MIXTURE_LEVER_POSITION:1": 95,
    }


def test_parse_limits_c172():
    aircraft = next(a for a in load_aircraft() if "172" in a.name)
    limits = parse_limits(aircraft.vspeeds)
    assert limits["vne"] == 163 and limits["vno"] == 129
    assert limits["vfe"] == 85  # full-flap limit, not the 10° limit


def test_engine_takeoff_landing_detection():
    rec = c172_recorder()
    t = 0.0
    rec.update(sample(1, 0, 1000, combustion=0), now=t)
    t += 1; rec.update(sample(1, 0, 1000, combustion=1), now=t)          # engine start
    t += 1; rec.update(sample(1, 40, 1000), now=t)
    t += 1; rec.update(sample(1, 56, 1000), now=t)
    t += 1; rec.update(sample(0, 58, 1010), now=t)                        # liftoff at 58
    for i in range(5):
        t += 1; rec.update(sample(0, 75, 1010 + 10 * i), now=t)           # climb ~600 fpm
    t += 1; rec.update(sample(0, 65, 1005), now=t)                        # descending
    t += 1; rec.update(sample(0, 63, 998), now=t)                         # -420 fpm
    t += 1; rec.update(sample(1, 55, 997), now=t)                         # touchdown
    t += 1; rec.update(sample(1, 20, 997, combustion=0), now=t)           # engine stop

    kinds = [e["event"] for e in rec.events]
    assert kinds == ["engine_start", "takeoff", "touchdown", "engine_stop"]
    takeoff = rec.events[1]
    assert takeoff["rotation_ias"] == 58
    touchdown = rec.events[2]
    assert touchdown["ias"] == 55
    assert touchdown["fpm"] == -420  # descent rate from altitude deltas


def test_exceedance_flaps_above_vfe():
    rec = c172_recorder()
    t = 0.0
    rec.update(sample(1, 0, 1000), now=t)
    t += 1; rec.update(sample(0, 100, 1500, flaps=0), now=t)   # clean at 100 — fine
    for _ in range(3):
        t += 1; rec.update(sample(0, 95, 1500, flaps=1), now=t)  # flaps out above Vfe 85
    assert rec.exceedances["flaps above Vfe"]["seconds"] == 3
    assert rec.exceedances["flaps above Vfe"]["max_ias"] == 95
    assert "Vne exceeded" not in rec.exceedances


def test_checklist_logging_and_summary():
    rec = c172_recorder()
    rec.update(sample(1, 0, 1000), now=0.0)
    rec.log_item("Before Takeoff (Run-Up)", "Throttle", "1800 RPM", via_sim=True, now=10.0)
    rec.log_item("Before Takeoff (Run-Up)", "Departure briefing", "COMPLETE", via_sim=False, now=20.0)
    rec.log_section_complete("Before Takeoff (Run-Up)", now=21.0)

    summary = rec.summary()
    assert summary["aircraft"].startswith("Cessna")
    assert summary["checklist_items_done"] == 2
    assert summary["checklist_items_sim_verified"] == 1
    assert summary["checklist_sections_completed"] == ["Before Takeoff (Run-Up)"]
    assert summary["limits"]["vne"] == 163
    json.dumps(summary)  # must be serializable for saving + the Claude prompt


def test_trace_is_downsampled_and_capped():
    rec = c172_recorder()
    for i in range(600):
        rec.update(sample(0, 100, 3000), now=float(i))
    assert len(rec.samples) == 600
    assert len(rec.summary()["trace"]) <= 100


def test_save_roundtrip(tmp_path):
    rec = c172_recorder()
    rec.update(sample(1, 0, 1000), now=0.0)
    rec.log_item("Taxi", "Brakes", "CHECK", via_sim=False, now=5.0)
    path = rec.save(directory=tmp_path)
    data = json.loads(path.read_text())
    assert data["checklist_items_done"] == 1


def test_debrief_prompt_contains_the_log():
    rec = c172_recorder()
    rec.update(sample(1, 0, 1000), now=0.0)
    prompt = build_prompt(rec.summary())
    assert "flight log" in prompt.lower()
    assert "Cessna" in prompt and "vne" in prompt
