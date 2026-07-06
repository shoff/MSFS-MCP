"""Tiny, safe condition language for sim-verified checklist items.

A verify spec is one condition or a list of conditions (AND-ed):

    "ELECTRICAL_MASTER_BATTERY == 1"
    ["GENERAL_ENG_RPM:1 >= 1650", "GENERAL_ENG_RPM:1 <= 1950"]

Left side is a SimVar name exactly as python-SimConnect spells it (indexed
vars use ':N'). Operators: == != >= <= > <. Right side is a number.
No eval(), no surprises.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass

_EPSILON = 0.01

_OPS = {
    "==": lambda a, b: abs(a - b) <= _EPSILON,
    "!=": lambda a, b: abs(a - b) > _EPSILON,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}

_CONDITION_RE = re.compile(
    r"^\s*([A-Z0-9_]+(?::\d+)?)\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$"
)


@dataclass(frozen=True)
class Condition:
    var: str
    op: str
    value: float

    def holds(self, values: dict) -> bool:
        raw = values.get(self.var)
        if raw is None or isinstance(raw, dict):  # missing / error payloads
            return False
        try:
            actual = float(raw)
        except (TypeError, ValueError):
            return False
        return _OPS[self.op](actual, self.value)


def parse_condition(text: str) -> Condition:
    match = _CONDITION_RE.match(text)
    if not match:
        raise ValueError(f"Bad verify condition: {text!r} (expected 'SIMVAR op number')")
    var, op, value = match.groups()
    return Condition(var=var, op=op, value=float(value))


def parse_verify(spec) -> list[Condition]:
    """Accept a single condition string or a list of them."""
    if spec is None:
        return []
    if isinstance(spec, str):
        spec = [spec]
    return [parse_condition(s) for s in spec]


def satisfied(conditions: list[Condition], values: dict) -> bool:
    return bool(conditions) and all(c.holds(values) for c in conditions)


def vars_needed(conditions: list[Condition]) -> set[str]:
    return {c.var for c in conditions}
