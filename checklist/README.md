# EFB Checklist

A dark, minimal, keyboard-first electronic checklist (PyQt6) built to float on top of Microsoft Flight Simulator 2024 while you learn real procedures. Ships with the **Cessna 172S Skyhawk** and **Piper PA-28-181 Archer**, covering normal procedures (preflight through shutdown), emergency procedures, and V-speed references, compiled from POH-based flight school checklists.

> **For simulation and training familiarization only. Not for real-world flight.** Real aircraft: use the POH/AFM for your specific serial number.

## Install

```powershell
cd checklist
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m efbchecklist
```

Python 3.10+. Works on Windows, macOS, and Linux.

## Running alongside MSFS 2024

1. Run MSFS in **windowed** or **borderless windowed** mode (exclusive fullscreen will fight the overlay on some setups).
2. The app starts **pinned always-on-top** (📌 button, `Ctrl+T` to toggle) at a 560px-wide portrait footprint — park it on a second monitor or over an unused corner of the panel.
3. Use the **opacity slider** (bottom right) to let the sim show through.
4. MSFS 2024's walkaround mode pairs well with the Preflight — Walkaround checklist.

## Keyboard flow

The point is to run checklists without reaching for the mouse:

| Key | Action |
| --- | --- |
| `Space` / `Enter` | Check current item, advance to next unchecked |
| `Backspace` | Uncheck / step back |
| `↑` `↓` | Move between items |
| `←` `→` | Previous / next checklist |
| `Ctrl+E` | Jump to emergency procedures |
| `Ctrl+R` | Reset current checklist |
| `Ctrl+T` | Toggle always-on-top |

Color language follows glass-cockpit conventions: white = pending, green = complete, cyan = data/accent, amber = cautionary note, red = emergency.

## Adding aircraft

Drop a JSON file in `efbchecklist/data/` — it's picked up automatically. Schema is documented in `efbchecklist/models.py`. Each item is a challenge/response pair with an optional amber note:

```json
{ "c": "Magnetos", "r": "CHECK", "note": "Max drop 150 RPM, max difference 50 RPM" }
```

## Sources

Checklist content compiled and cross-checked from POH-derived training checklists published by University of Dubuque Aviation, Purdue Aviation, Lake Elmo Aero, East Coast Aero Club, Hanscom Aero Club, and Beverly Flight Center. School-specific limits vary (e.g. mag-drop tolerances); when they conflicted, the POH values were used.
