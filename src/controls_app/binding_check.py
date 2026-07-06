"""Which SimVar proves each binding works, and the per-device test list.

A binding passes live verification when BOTH sides are observed:
  hardware — the mapped physical input moved (InputMonitor)
  sim      — the expected SimVar changed from its baseline (SimLink)

Hardware moving without the SimVar reacting = the MSFS binding is wrong.

The SimVar / threshold / hint for each setting come from the canonical
settings_registry, so the writer and this verifier can never disagree about
what a binding means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .input_map import lookup_control
from .settings_registry import SettingSpec, spec_for_setting


@dataclass
class BindingTest:
    control: str            # physical control label
    control_id: str
    assignment: str
    var: str                # SimVar expected to react
    threshold: float
    hint: str
    status: str = "pending"     # pending | active | passed | hw_only | failed | skipped
    hw_seen: bool = False
    sim_seen: bool = False

    # kept for the dialog's older attribute access
    @property
    def spec(self):
        return self


@dataclass
class TestPlanResult:
    tests: list[BindingTest] = field(default_factory=list)
    untestable: list[tuple[str, str]] = field(default_factory=list)  # (control, reason)


def _testable(spec: SettingSpec | None) -> bool:
    return spec is not None and spec.check_var is not None


def build_tests(plan_bindings, control_ids: dict[str, str], input_map) -> TestPlanResult:
    """Testable bindings for one device: needs an observable SimVar AND a mapping."""
    out = TestPlanResult()
    for b in plan_bindings:
        if "UNBOUND" in b.assignment.upper():
            continue
        control_id = lookup_control(b.control, control_ids)
        if control_id is None:
            out.untestable.append((b.control, "not in the device profile"))
            continue
        spec = spec_for_setting(b.msfs_setting)
        if not _testable(spec):
            out.untestable.append((b.control, "no observable SimVar — check by eye in the cockpit"))
            continue
        has_phys = (
            input_map.axis_for_control(control_id) is not None
            or bool(input_map.buttons_for_control(control_id))
        )
        if not has_phys:
            out.untestable.append((b.control, "no physical mapping — run Learn mode first"))
            continue
        out.tests.append(
            BindingTest(
                control=b.control, control_id=control_id, assignment=b.assignment,
                var=spec.check_var, threshold=spec.check_threshold, hint=spec.check_hint,
            )
        )
    return out
