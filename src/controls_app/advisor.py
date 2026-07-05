"""Claude-powered controls advisor.

Sends the chosen aircraft, the hardware inventory (with detection state) and
the current binding plan to Claude, and gets back a reviewed/improved plan as
validated JSON (structured outputs), plus coaching on how to fly with it.
"""

from __future__ import annotations

import json
import os

from .bindings import ControlPlan
from .devices import DEVICES

MODEL = "claude-opus-4-8"

BINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "control": {"type": "string", "description": "Physical control, exactly as named in the inventory"},
        "assignment": {"type": "string", "description": "What it does in the sim (or 'LEAVE UNBOUND (reason)')"},
        "msfs_setting": {"type": "string", "description": "Action name to search in MSFS 2024 Options > Controls"},
        "usage_tip": {"type": "string", "description": "When/how to use it in real procedures, tied to checklist phases"},
        "priority": {"type": "string", "enum": ["essential", "recommended", "optional"]},
    },
    "required": ["control", "assignment", "msfs_setting", "usage_tip", "priority"],
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentence overview of the setup philosophy for this aircraft"},
        "aircraft_notes": {"type": "string", "description": "Aircraft-specific control gotchas (fixed-pitch, carb heat, fuel selector, ...)"},
        "coaching": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered setup + flying guidance steps, referencing MSFS 2024 menus and checklist phases",
        },
        "devices": {
            "type": "object",
            "properties": {
                "honeycomb_alpha": {"type": "array", "items": BINDING_SCHEMA},
                "honeycomb_bravo": {"type": "array", "items": BINDING_SCHEMA},
                "velocityone_rudder": {"type": "array", "items": BINDING_SCHEMA},
                "keyboard_mouse": {"type": "array", "items": BINDING_SCHEMA},
            },
            "required": ["honeycomb_alpha", "honeycomb_bravo", "velocityone_rudder", "keyboard_mouse"],
            "additionalProperties": False,
        },
    },
    "required": ["summary", "aircraft_notes", "coaching", "devices"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are a flight-sim controls expert and flight instructor helping a student pilot set up
Microsoft Flight Simulator 2024 hardware bindings so they can practice real-world procedures
(they fly alongside an electronic checklist app with real POH-based checklists).

Rules:
- Recommend bindings only for controls that exist in the provided hardware inventory, using
  the exact control names given.
- MSFS 2024 bindings live in Options > Controls; give the searchable action name for each
  binding (e.g. 'TOGGLE MASTER BATTERY'). If something is better clicked in the cockpit,
  say so and explain why (procedure training value).
- Respect the aircraft's systems: never bind a prop lever on a fixed-pitch aircraft or a gear
  lever on fixed gear — explicitly recommend LEAVE UNBOUND with the reason, that teaches the
  student something.
- usage_tip must connect the control to actual procedures/checklist phases (before start,
  run-up, takeoff, cruise, approach, emergencies) with real numbers where relevant.
- coaching is an ordered list: first the MSFS setup steps (profiles, sensitivity, clearing
  defaults, assistance settings), then how to fly the procedures with this hardware.
- If a device is NOT detected, still provide its plan but note in coaching how to substitute
  with keyboard/mouse for the missing hardware.
- Prefer improving the provided current plan over rewriting it wholesale; keep what is good.
"""


class AdvisorUnavailable(RuntimeError):
    """Raised when the Claude advisor can't run (no SDK / no credentials)."""


def _build_user_prompt(
    aircraft_name: str,
    aircraft_context: str,
    detected: dict[str, bool],
    current_plan: ControlPlan,
    user_notes: str,
) -> str:
    inventory = []
    for device in DEVICES:
        state = "DETECTED" if detected.get(device.id) else "not detected"
        controls = "\n".join(f"  - {c.label} ({c.kind}){' — ' + c.notes if c.notes else ''}" for c in device.inputs)
        inventory.append(f"{device.id}: {device.manufacturer} {device.name} [{state}]\n{controls}")

    sections = [
        f"Aircraft: {aircraft_name}",
        f"Aircraft reference data:\n{aircraft_context}" if aircraft_context else "",
        "Hardware inventory:\n" + "\n\n".join(inventory),
        "Current binding plan (JSON):\n" + json.dumps(current_plan.to_dict(), indent=2),
        f"Pilot's notes: {user_notes}" if user_notes.strip() else "",
        "Review the current plan for this aircraft and hardware, fix anything inappropriate, "
        "fill gaps, and return the full improved plan.",
    ]
    return "\n\n".join(s for s in sections if s)


def suggest_plan(
    aircraft_key: str,
    aircraft_name: str,
    aircraft_context: str,
    detected: dict[str, bool],
    current_plan: ControlPlan,
    user_notes: str = "",
) -> ControlPlan:
    """Ask Claude for an improved plan. Blocking — call from a worker thread."""
    try:
        import anthropic
    except ImportError as exc:
        raise AdvisorUnavailable(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        ) from exc

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise AdvisorUnavailable(
            "No Anthropic credentials found. Set the ANTHROPIC_API_KEY environment "
            "variable (https://platform.claude.com) and restart, or keep using the "
            "built-in default plan."
        )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        aircraft_name, aircraft_context, detected, current_plan, user_notes
                    ),
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        )
    except anthropic.AuthenticationError as exc:
        raise AdvisorUnavailable("Anthropic API key was rejected — check ANTHROPIC_API_KEY.") from exc
    except anthropic.APIConnectionError as exc:
        raise AdvisorUnavailable("Could not reach the Anthropic API — check your connection.") from exc

    if response.stop_reason == "refusal":
        raise AdvisorUnavailable("Claude declined this request; keeping the current plan.")

    text = next(block.text for block in response.content if block.type == "text")
    raw = json.loads(text)
    raw["aircraft_key"] = aircraft_key
    raw["aircraft_name"] = aircraft_name
    return ControlPlan.from_dict(raw, source=f"Claude ({MODEL})")
