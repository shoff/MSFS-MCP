"""Shared infrastructure for the MSFS 2024 companion GUI apps.

Neutral home for code both ``checklist_app`` and ``controls_app`` depend on —
the dark theme and the background sim link — so neither app has to reach into
the other's package. No app-specific domain logic lives here.
"""

__version__ = "0.1.0"
