"""Flight recorder: telemetry trace + derived events + checklist activity.

Rides along on the checklist app's SimLink. Pure Python (no Qt) so the
detection logic is unit-testable: feed it value dicts with timestamps and it
derives engine start/stop, takeoff (with rotation speed), touchdown (with
descent rate computed from altitude deltas — unit-safe), and limit
exceedances against the aircraft's own V-speeds.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

FLIGHTS_DIR = Path.home() / ".msfs_companion" / "flights"

# Watched continuously (merged into SimLink's per-section watch set).
RECORDER_VARS = [
    "SIM_ON_GROUND",
    "AIRSPEED_INDICATED",
    "INDICATED_ALTITUDE",
    "GENERAL_ENG_COMBUSTION:1",
    "GENERAL_ENG_RPM:1",
    "GENERAL_ENG_THROTTLE_LEVER_POSITION:1",
    "GENERAL_ENG_MIXTURE_LEVER_POSITION:1",
    "FLAPS_HANDLE_INDEX",
]

SAMPLE_INTERVAL_S = 1.0
MAX_SAMPLES = 7200  # ~2 h at 1 Hz; past this the trail decimates (see _decimate_if_full)


def parse_limits(vspeeds: list[tuple[str, str]]) -> dict[str, float]:
    """Pull Vne/Vno/Vfe(full) numbers out of the aircraft's V-speed table."""
    limits: dict[str, float] = {}
    for label, value in vspeeds:
        match = re.search(r"(\d+)", value)
        if not match:
            continue
        speed = float(match.group(1))
        lowered = label.lower()
        if "vne" in lowered:
            limits["vne"] = speed
        elif "vno" in lowered:
            limits["vno"] = speed
        elif "vfe" in lowered:
            # Track the least-restrictive flap limit; we can't map a flap detent
            # to its specific Vfe generically, so we only flag speeds above the
            # HIGHEST Vfe — a real violation at any flap setting, never a false one.
            limits["vfe_max"] = max(limits.get("vfe_max", 0.0), speed)
        elif "vr" in lowered and "rotate" in lowered:
            limits["vr"] = speed
    return limits


def _num(values: dict, key: str) -> float | None:
    raw = values.get(key)
    if raw is None or isinstance(raw, dict):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class FlightRecorder:
    aircraft: str = ""
    limits: dict[str, float] = field(default_factory=dict)

    started_at: float | None = None
    samples: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    checklist_log: list[dict] = field(default_factory=list)
    exceedances: dict[str, dict] = field(default_factory=dict)  # kind -> {seconds, max_ias}

    _prev: dict = field(default_factory=dict)
    _last_sample_t: float | None = None
    _sample_interval: float = SAMPLE_INTERVAL_S  # grows as the trail decimates
    saved: bool = False  # set once persisted, so we don't double-save on close

    # ------------------------------------------------------------- config
    def set_aircraft(self, name: str, vspeeds: list[tuple[str, str]]) -> None:
        if self.aircraft and name != self.aircraft:
            self._event("aircraft_changed", {"to": name})
        self.aircraft = name
        self.limits = parse_limits(vspeeds)

    # ------------------------------------------------------------ logging
    def _t(self, now: float) -> float:
        if self.started_at is None:
            self.started_at = now
        return round(now - self.started_at, 1)

    def _event(self, kind: str, data: dict | None = None, now: float | None = None) -> None:
        self.events.append({"t": self._t(now if now is not None else time.time()),
                            "event": kind, **(data or {})})

    def log_item(self, section: str, challenge: str, response: str, via_sim: bool,
                 now: float | None = None) -> None:
        self.checklist_log.append({
            "t": self._t(now if now is not None else time.time()),
            "section": section,
            "item": f"{challenge} — {response}",
            "verified_by_sim": via_sim,
        })

    def log_section_complete(self, section: str, now: float | None = None) -> None:
        self._event("checklist_complete", {"section": section}, now=now)

    # ----------------------------------------------------------- sampling
    def update(self, values: dict, now: float | None = None) -> None:
        """Feed a SimLink values snapshot; derives events and samples at 1 Hz."""
        now = now if now is not None else time.time()
        on_ground = _num(values, "SIM_ON_GROUND")
        ias = _num(values, "AIRSPEED_INDICATED")
        alt = _num(values, "INDICATED_ALTITUDE")
        combustion = _num(values, "GENERAL_ENG_COMBUSTION:1")
        flaps = _num(values, "FLAPS_HANDLE_INDEX")

        prev = self._prev

        # engine
        if combustion is not None and prev.get("combustion") is not None:
            if combustion > 0.5 and prev["combustion"] <= 0.5:
                self._event("engine_start", now=now)
            elif combustion <= 0.5 and prev["combustion"] > 0.5:
                self._event("engine_stop", now=now)

        # takeoff / landing
        if on_ground is not None and prev.get("on_ground") is not None:
            if prev["on_ground"] > 0.5 and on_ground <= 0.5:
                self._event("takeoff", {
                    "rotation_ias": round(ias, 1) if ias is not None else None,
                    "flaps_index": flaps,
                }, now=now)
            elif prev["on_ground"] <= 0.5 and on_ground > 0.5:
                self._event("touchdown", {
                    "ias": round(ias, 1) if ias is not None else None,
                    "fpm": prev.get("fpm"),
                }, now=now)

        # vertical speed from altitude deltas (unit-safe)
        fpm = None
        if alt is not None and prev.get("alt") is not None and prev.get("now") is not None:
            dt = now - prev["now"]
            if dt > 0:
                fpm = round((alt - prev["alt"]) * 60.0 / dt)

        # limit exceedances (airborne only). Accumulate real elapsed time between
        # polls, not a per-callback +1 (SimLink polls at 2 Hz, not 1 Hz).
        dt = now - prev["now"] if prev.get("now") is not None else 0.0
        if ias is not None and on_ground is not None and on_ground <= 0.5 and 0 < dt <= 5:
            checks = []
            if "vne" in self.limits and ias > self.limits["vne"]:
                checks.append("Vne exceeded")
            elif "vno" in self.limits and ias > self.limits["vno"]:
                checks.append("above Vno")
            if "vfe_max" in self.limits and flaps is not None and flaps > 0.5 and ias > self.limits["vfe_max"]:
                checks.append("flaps above Vfe")
            for kind in checks:
                entry = self.exceedances.setdefault(kind, {"seconds": 0.0, "max_ias": 0.0})
                entry["seconds"] = round(entry["seconds"] + dt, 1)
                entry["max_ias"] = max(entry["max_ias"], round(ias, 1))

        # sample trail (1 Hz, coarsening after MAX_SAMPLES to bound memory)
        if self._last_sample_t is None or now - self._last_sample_t >= self._sample_interval:
            self._last_sample_t = now
            self.samples.append({
                "t": self._t(now),
                "ias": round(ias, 1) if ias is not None else None,
                "alt": round(alt) if alt is not None else None,
                "fpm": fpm,
                "rpm": round(_num(values, "GENERAL_ENG_RPM:1") or 0),
                "flaps": flaps,
                "throttle": round(_num(values, "GENERAL_ENG_THROTTLE_LEVER_POSITION:1") or 0),
                "mixture": round(_num(values, "GENERAL_ENG_MIXTURE_LEVER_POSITION:1") or 0),
                "on_ground": bool(on_ground) if on_ground is not None else None,
            })
            self._decimate_if_full()

        self._prev = {
            "on_ground": on_ground if on_ground is not None else prev.get("on_ground"),
            "combustion": combustion if combustion is not None else prev.get("combustion"),
            "alt": alt, "now": now, "fpm": fpm if fpm is not None else prev.get("fpm"),
        }

    def _decimate_if_full(self) -> None:
        """Halve the sample resolution when the trail gets long, so a marathon
        flight uses bounded memory (keeps the whole flight, coarser over time)."""
        if len(self.samples) > MAX_SAMPLES:
            self.samples = self.samples[::2]
            self._sample_interval *= 2  # future samples come in at the coarser rate

    # ------------------------------------------------------------ summary
    @property
    def has_data(self) -> bool:
        return bool(self.samples or self.checklist_log)

    def summary(self) -> dict:
        airborne = [s for s in self.samples if s.get("on_ground") is False]
        takeoffs = [e for e in self.events if e["event"] == "takeoff"]
        touchdowns = [e for e in self.events if e["event"] == "touchdown"]
        duration_min = round(self.samples[-1]["t"] / 60.0, 1) if self.samples else 0.0

        sections_done = [e["section"] for e in self.events if e["event"] == "checklist_complete"]
        sim_verified = sum(1 for c in self.checklist_log if c["verified_by_sim"])

        stride = max(1, len(self.samples) // 80)
        return {
            "aircraft": self.aircraft,
            "duration_min": duration_min,
            "limits": self.limits,
            "takeoffs": takeoffs,
            "touchdowns": touchdowns,
            "max_ias": max((s["ias"] for s in airborne if s["ias"] is not None), default=None),
            "max_alt": max((s["alt"] for s in airborne if s["alt"] is not None), default=None),
            "exceedances": self.exceedances,
            "events": self.events,
            "checklist_sections_completed": sections_done,
            "checklist_items_done": len(self.checklist_log),
            "checklist_items_sim_verified": sim_verified,
            "checklist_log": self.checklist_log[-120:],
            "trace": self.samples[::stride][:100],
        }

    def save(self, directory: Path = FLIGHTS_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = directory / f"flight-{stamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, indent=2)
        self.saved = True
        return path
