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
    assert limits["vfe_max"] == 110  # least-restrictive flap limit (never false-flag)
    assert limits["vr"] == 55


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
    # 10° flaps at 100 kt is LEGAL (Vfe 110) — must NOT be flagged.
    t += 1; rec.update(sample(0, 100, 1500, flaps=1), now=t)
    assert "flaps above Vfe" not in rec.exceedances
    # Above the least-restrictive Vfe (110) with flaps out — real violation.
    for _ in range(3):
        t += 1; rec.update(sample(0, 115, 1500, flaps=1), now=t)
    assert rec.exceedances["flaps above Vfe"]["seconds"] == 3   # 3 x 1 s polls
    assert rec.exceedances["flaps above Vfe"]["max_ias"] == 115


def test_exceedance_seconds_track_real_time_at_2hz():
    """Regression: exceedance seconds must count elapsed time, not callbacks."""
    rec = c172_recorder()
    rec.update(sample(1, 0, 1000), now=0.0)
    # 10 half-second polls above Vne (163) = 5 real seconds, not 10.
    for i in range(1, 11):
        rec.update(sample(0, 170, 3000), now=i * 0.5)
    assert rec.exceedances["Vne exceeded"]["seconds"] == 5.0


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


FAKE_DEBRIEF = {
    "overview": "A short pattern flight with a late rotation.",
    "grades": [
        {"area": "Checklist discipline", "score": 4, "comment": "2 of 2 items sim-verified."},
        {"area": "Speed control", "score": 2, "comment": "Flaps out at 96 vs Vfe 85."},
        {"area": "Configuration management", "score": 3, "comment": "Flaps late on final."},
        {"area": "Takeoff & landing technique", "score": 3, "comment": "Rotated at 62 vs Vr 55; -480 fpm arrival."},
    ],
    "went_well": ["Run-up flow was complete."],
    "work_on": [
        {"title": "Rotate at Vr", "evidence": "62 KIAS vs Vr 55", "why": "Extends the ground roll",
         "fix": "Call 'airspeed alive, 55 rotate' aloud."},
    ],
    "next_flight": "Three circuits focusing on rotation at 55.",
}


def test_debrief_schema_is_strict():
    from checklist_app.debrief import DEBRIEF_SCHEMA

    def walk(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                assert schema.get("additionalProperties") is False
                assert "required" in schema
            for value in schema.values():
                walk(value)
        elif isinstance(schema, list):
            for value in schema:
                walk(value)

    walk(DEBRIEF_SCHEMA)


def test_debrief_markdown_rendering():
    from checklist_app.debrief import debrief_to_markdown

    md = debrief_to_markdown(FAKE_DEBRIEF)
    assert "★★★★☆" in md and "★★☆☆☆" in md  # star bars for scores 4 and 2
    assert "(4/5)" in md and "(2/5)" in md
    assert "Rotate at Vr" in md and "Next flight" in md


def test_build_tiles_status_colors():
    from companion_common import theme
    from checklist_app.debrief_dialog import build_tiles

    rec = c172_recorder()
    t = 0.0
    rec.update(sample(1, 0, 1000), now=t)
    t += 1; rec.update(sample(1, 55, 1000), now=t)
    t += 1; rec.update(sample(0, 62, 1010), now=t)                # rotate at 62 (Vr 55 -> +7 amber)
    for _ in range(3):
        t += 1; rec.update(sample(0, 115, 1200, flaps=1), now=t)  # flaps above Vfe_max 110
    t += 1; rec.update(sample(0, 60, 1005), now=t)
    t += 1; rec.update(sample(0, 60, 997), now=t)                 # -480 fpm
    t += 1; rec.update(sample(1, 54, 996), now=t)

    tiles = {label: (value, caption, color) for label, value, caption, color in build_tiles(rec.summary())}
    assert tiles["ROTATION"][2] == theme.AMBER and "(+7)" in tiles["ROTATION"][1]
    assert tiles["TOUCHDOWN"][1] == "hard" and tiles["TOUCHDOWN"][2] == theme.RED
    assert tiles["LIMITS"][2] == theme.RED and "flaps above Vfe" in tiles["LIMITS"][1]
