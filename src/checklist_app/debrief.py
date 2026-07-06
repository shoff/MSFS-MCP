"""Instructor-style post-flight debrief, written by Claude from the flight log."""

from __future__ import annotations

import json
import os

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
You are an experienced, encouraging CFI giving a post-flight debrief to a student
practicing real-world procedures in Microsoft Flight Simulator 2024. You receive a
JSON flight log: derived events (engine start, takeoff with rotation speed, touchdown
with descent rate in fpm), a downsampled telemetry trace, limit exceedances measured
against the aircraft's own V-speeds, and the pilot's checklist activity (which
checklists were completed, in what order, and which items the sim verified live).

Write the debrief in Markdown:

## Flight overview — two or three sentences on what the flight was.
## What went well — specific, evidence-based praise; cite the numbers.
## What to work on — the 3 most valuable improvements, each tied to data in the log
   and to the correct POH number (e.g. rotation at 62 vs Vr 55; touchdown at -450 fpm;
   flaps extended above Vfe; run-up RPM off target; checklists skipped or run out of
   order; items that had to be checked manually because the cockpit state never
   matched). Explain WHY each matters aeronautically.
## By the numbers — a small table of key figures vs targets.
## Next flight — one concrete, flyable exercise for the next session.

Ground every claim in the log. If data is missing or ambiguous, say so rather than
inventing figures. Warm but honest — a good instructor names the problem plainly.
"""


class DebriefUnavailable(RuntimeError):
    pass


def build_prompt(summary: dict) -> str:
    return (
        "Here is the flight log from my session just now. Please give me my debrief.\n\n"
        + json.dumps(summary, indent=2)
    )


def generate_debrief(summary: dict) -> str:
    """Blocking Claude call — run from a worker thread."""
    try:
        import anthropic
    except ImportError as exc:
        raise DebriefUnavailable(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        ) from exc

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise DebriefUnavailable(
            "No Anthropic credentials found — set ANTHROPIC_API_KEY to enable the "
            "instructor debrief. The flight statistics above are still saved locally."
        )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(summary)}],
        )
    except anthropic.AuthenticationError as exc:
        raise DebriefUnavailable("Anthropic API key was rejected — check ANTHROPIC_API_KEY.") from exc
    except anthropic.APIConnectionError as exc:
        raise DebriefUnavailable("Could not reach the Anthropic API — check your connection.") from exc

    if response.stop_reason == "refusal":
        raise DebriefUnavailable("Claude declined this request.")
    return next(block.text for block in response.content if block.type == "text")
