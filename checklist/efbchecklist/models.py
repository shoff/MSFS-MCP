"""Data models for aircraft checklists.

Checklist data lives in JSON files under efbchecklist/data. Each file is one
aircraft. Schema:

{
  "id": "c172s",
  "name": "Cessna 172S Skyhawk",
  "subtitle": "...",
  "vspeeds": [{"label": "...", "value": "..."}],
  "groups": [
    {
      "name": "Normal Procedures",
      "kind": "normal" | "emergency",
      "checklists": [
        {"id": "...", "name": "...", "items": [{"c": challenge, "r": response, "note": optional}]}
      ]
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@dataclass
class ChecklistItem:
    challenge: str
    response: str
    note: str | None = None
    checked: bool = False


@dataclass
class Checklist:
    id: str
    name: str
    kind: str  # "normal" or "emergency"
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def done(self) -> int:
        return sum(1 for item in self.items if item.checked)

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.done == self.total

    def reset(self) -> None:
        for item in self.items:
            item.checked = False

    def firstUnchecked(self) -> int:
        for index, item in enumerate(self.items):
            if not item.checked:
                return index
        return max(0, self.total - 1)


@dataclass
class ChecklistGroup:
    name: str
    kind: str
    checklists: list[Checklist] = field(default_factory=list)


@dataclass
class VSpeed:
    label: str
    value: str


@dataclass
class Aircraft:
    id: str
    name: str
    subtitle: str
    vspeeds: list[VSpeed] = field(default_factory=list)
    groups: list[ChecklistGroup] = field(default_factory=list)

    def allChecklists(self) -> list[Checklist]:
        return [cl for group in self.groups for cl in group.checklists]

    def resetAll(self) -> None:
        for cl in self.allChecklists():
            cl.reset()


def loadAircraft(path: Path) -> Aircraft:
    raw = json.loads(path.read_text(encoding="utf-8"))
    groups = []
    for rawGroup in raw.get("groups", []):
        kind = rawGroup.get("kind", "normal")
        checklists = []
        for rawList in rawGroup.get("checklists", []):
            items = [
                ChecklistItem(
                    challenge=rawItem["c"],
                    response=rawItem["r"],
                    note=rawItem.get("note"),
                )
                for rawItem in rawList.get("items", [])
            ]
            checklists.append(
                Checklist(
                    id=rawList["id"],
                    name=rawList["name"],
                    kind=kind,
                    items=items,
                )
            )
        groups.append(ChecklistGroup(name=rawGroup["name"], kind=kind, checklists=checklists))
    return Aircraft(
        id=raw["id"],
        name=raw["name"],
        subtitle=raw.get("subtitle", ""),
        vspeeds=[VSpeed(v["label"], v["value"]) for v in raw.get("vspeeds", [])],
        groups=groups,
    )


def loadAllAircraft() -> list[Aircraft]:
    aircraft = [loadAircraft(path) for path in sorted(DATA_DIR.glob("*.json"))]
    if not aircraft:
        raise FileNotFoundError(f"No aircraft JSON files found in {DATA_DIR}")
    return aircraft
