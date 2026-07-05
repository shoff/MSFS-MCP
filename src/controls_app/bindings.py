"""Binding plan data model + built-in default plans (offline fallback)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PLANS_DIR = Path(__file__).parent / "data" / "plans"

PRIORITIES = ("essential", "recommended", "optional")


@dataclass
class Binding:
    control: str          # human label of the physical control
    assignment: str       # what it should do in the sim
    msfs_setting: str     # what to search for in MSFS Options -> Controls
    usage_tip: str        # how/when to use it while flying
    priority: str = "recommended"


@dataclass
class ControlPlan:
    aircraft_key: str
    aircraft_name: str
    summary: str
    aircraft_notes: str
    coaching: list[str] = field(default_factory=list)
    devices: dict[str, list[Binding]] = field(default_factory=dict)  # device_id -> bindings
    source: str = "built-in defaults"

    @classmethod
    def from_dict(cls, raw: dict, source: str = "built-in defaults") -> "ControlPlan":
        devices = {
            device_id: [
                Binding(
                    control=b["control"],
                    assignment=b["assignment"],
                    msfs_setting=b.get("msfs_setting", ""),
                    usage_tip=b.get("usage_tip", ""),
                    priority=b.get("priority", "recommended"),
                )
                for b in binding_list
            ]
            for device_id, binding_list in raw.get("devices", {}).items()
        }
        return cls(
            aircraft_key=raw["aircraft_key"],
            aircraft_name=raw["aircraft_name"],
            summary=raw.get("summary", ""),
            aircraft_notes=raw.get("aircraft_notes", ""),
            coaching=list(raw.get("coaching", [])),
            devices=devices,
            source=source,
        )

    def to_dict(self) -> dict:
        return {
            "aircraft_key": self.aircraft_key,
            "aircraft_name": self.aircraft_name,
            "summary": self.summary,
            "aircraft_notes": self.aircraft_notes,
            "coaching": self.coaching,
            "devices": {
                device_id: [
                    {
                        "control": b.control,
                        "assignment": b.assignment,
                        "msfs_setting": b.msfs_setting,
                        "usage_tip": b.usage_tip,
                        "priority": b.priority,
                    }
                    for b in binding_list
                ]
                for device_id, binding_list in self.devices.items()
            },
        }


def load_default_plans(plans_dir: Path = PLANS_DIR) -> dict[str, ControlPlan]:
    """Load bundled plans keyed by aircraft_key."""
    plans = {}
    for path in sorted(plans_dir.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            plan = ControlPlan.from_dict(json.load(f))
        plans[plan.aircraft_key] = plan
    return plans
