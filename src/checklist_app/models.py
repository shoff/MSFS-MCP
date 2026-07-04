"""Checklist data model. No Qt imports here so tests can load data headless."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

GROUP_ORDER = ("Normal", "Emergency", "Abnormal")


@dataclass
class ChecklistItem:
    challenge: str
    response: str = ""
    kind: str = "item"  # "item" (checkable) or "note" (informational line)
    memory: bool = False  # memory item — should be committed to memory
    checked: bool = False

    @property
    def checkable(self) -> bool:
        return self.kind == "item"


@dataclass
class ChecklistSection:
    name: str
    group: str  # Normal | Emergency | Abnormal
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def is_emergency(self) -> bool:
        return self.group == "Emergency"

    @property
    def checkable_items(self) -> list[ChecklistItem]:
        return [i for i in self.items if i.checkable]

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.checkable_items if i.checked)

    @property
    def total_count(self) -> int:
        return len(self.checkable_items)

    @property
    def complete(self) -> bool:
        return self.total_count > 0 and self.done_count == self.total_count

    def reset(self) -> None:
        for item in self.items:
            item.checked = False


@dataclass
class Aircraft:
    name: str
    short_name: str
    source: str
    vspeeds: list[tuple[str, str]]
    sections: list[ChecklistSection]

    def reset(self) -> None:
        for section in self.sections:
            section.reset()


def _parse_aircraft(raw: dict) -> Aircraft:
    sections = []
    for sec in raw["sections"]:
        items = [
            ChecklistItem(
                challenge=it["challenge"],
                response=it.get("response", ""),
                kind=it.get("kind", "item"),
                memory=bool(it.get("memory", False)),
            )
            for it in sec["items"]
        ]
        sections.append(ChecklistSection(name=sec["name"], group=sec["group"], items=items))
    # Keep JSON order within a group but order groups Normal -> Emergency -> Abnormal
    sections.sort(key=lambda s: GROUP_ORDER.index(s.group))
    return Aircraft(
        name=raw["name"],
        short_name=raw.get("short_name", raw["name"]),
        source=raw.get("source", ""),
        vspeeds=[tuple(v) for v in raw.get("vspeeds", [])],
        sections=sections,
    )


def load_aircraft(data_dir: Path = DATA_DIR) -> list[Aircraft]:
    """Load every aircraft JSON in the data directory, sorted by name."""
    aircraft = []
    for path in sorted(data_dir.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            aircraft.append(_parse_aircraft(json.load(f)))
    aircraft.sort(key=lambda a: a.name)
    return aircraft
