"""Instructor-style post-flight debrief, written by Claude from the flight log.

Returns STRUCTURED data (report-card grades + findings) so the dialog can
render it graphically instead of as one text blob.
"""

from __future__ import annotations

import json

from companion_common import claude

GRADE_AREAS = [
    "Checklist discipline",
    "Speed control",
    "Configuration management",
    "Takeoff & landing technique",
]

DEBRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "2-3 sentence summary of the flight"},
        "grades": {
            "type": "array",
            "description": "Report card, one entry per area, score 1 (poor) to 5 (excellent)",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "comment": {"type": "string", "description": "One evidence-based sentence"},
                },
                "required": ["area", "score", "comment"],
                "additionalProperties": False,
            },
        },
        "went_well": {"type": "array", "items": {"type": "string"}},
        "work_on": {
            "type": "array",
            "description": "The 3 most valuable improvements, most important first",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short imperative headline"},
                    "evidence": {"type": "string", "description": "The numbers from THIS flight"},
                    "why": {"type": "string", "description": "Why it matters aeronautically"},
                    "fix": {"type": "string", "description": "Concrete technique to apply next flight"},
                },
                "required": ["title", "evidence", "why", "fix"],
                "additionalProperties": False,
            },
        },
        "next_flight": {"type": "string", "description": "One concrete, flyable exercise"},
    },
    "required": ["overview", "grades", "went_well", "work_on", "next_flight"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""\
You are an experienced, encouraging CFI giving a post-flight debrief to a student
practicing real-world procedures in Microsoft Flight Simulator 2024. You receive a
JSON flight log: derived events (engine start, takeoff with rotation speed, touchdown
with descent rate in fpm), a downsampled telemetry trace, limit exceedances measured
against the aircraft's own V-speeds, and the pilot's checklist activity (which
checklists were completed, in what order, and which items the sim verified live).

Ground every claim in the log; if data is missing, say so in the relevant field
rather than inventing figures. Warm but honest — a good instructor names the
problem plainly.

Grade exactly these areas (in this order): {", ".join(GRADE_AREAS)}.
Each grade comment must cite a number from the log (e.g. 'rotated at 62 vs Vr 55').
'work_on' items must each tie evidence -> aeronautical why -> concrete fix.
"""


class DebriefUnavailable(RuntimeError):
    pass


def build_prompt(summary: dict) -> str:
    return (
        "Here is the flight log from my session just now. Please give me my debrief.\n\n"
        + json.dumps(summary, indent=2)
    )


def generate_debrief(summary: dict) -> dict:
    """Blocking Claude call — run from a worker thread. Returns the structured debrief."""
    return claude.call_json(
        system=SYSTEM_PROMPT,
        user=build_prompt(summary),
        schema=DEBRIEF_SCHEMA,
        error_cls=DebriefUnavailable,
        no_credentials_msg=(
            "No Anthropic credentials found — set ANTHROPIC_API_KEY to enable the "
            "instructor debrief. The flight statistics above are still saved locally."
        ),
    )


def debrief_to_markdown(data: dict) -> str:
    """Plain-Markdown rendering, used when saving the debrief to disk."""
    lines = ["# Instructor debrief", "", data["overview"], "", "## Report card", ""]
    for grade in data["grades"]:
        stars = "★" * grade["score"] + "☆" * (5 - grade["score"])
        lines.append(f"- **{grade['area']}** {stars} ({grade['score']}/5) — {grade['comment']}")
    lines += ["", "## What went well", ""]
    lines += [f"- {w}" for w in data["went_well"]]
    lines += ["", "## What to work on", ""]
    for i, item in enumerate(data["work_on"], 1):
        lines += [
            f"### {i}. {item['title']}",
            f"- **Evidence:** {item['evidence']}",
            f"- **Why it matters:** {item['why']}",
            f"- **The fix:** {item['fix']}",
            "",
        ]
    lines += ["## Next flight", "", data["next_flight"], ""]
    return "\n".join(lines)
