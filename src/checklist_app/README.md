# MSFS Flight Checklist

A sleek, dark, minimal electronic checklist app built with PyQt6, designed to run
alongside Microsoft Flight Simulator 2024 so you can learn and practice real
procedures — preflight, run-up, takeoff, landing, and emergencies.

![aircraft](../../docs/checklist-app.png)

## Aircraft

| Aircraft | Data file | Based on |
| --- | --- | --- |
| Cessna 172S Skyhawk | `data/c172s.json` | Leading Edge Aviation C172S checklist / Cessna 172S POH |
| Piper PA-28-181 Archer II | `data/pa28_181.json` | Northampton Airport & mattbeyer.com Archer II checklists / Piper POH |

Both include the full **normal procedures** (cabin + exterior preflight, engine
start, taxi, run-up, takeoff variants, climb, cruise, descent, landing variants,
go-around, after landing, shutdown), **emergency procedures** (engine failure,
engine/electrical/cabin/wing fire, emergency landing, spin recovery on the
Archer), **abnormal procedures** (alternator/electrical problems, flat tires,
flooded start, lost procedure), and a **V-speeds reference** page.

> ⚠️ For simulation and training familiarization only — not for real-world
> flight. Always use the POH/AFM for the actual aircraft you fly.

## Install & run

```bash
pip install -e ".[checklist]"
msfs-checklist          # or: python -m checklist_app
```

## Using it with MSFS 2024

1. Run MSFS in **borderless windowed mode** (General Options → Graphics →
   Display Mode: Windowed) or on a second monitor.
2. Keep the **⏏ On top** toggle enabled (it is by default) so the checklist
   floats above the sim.
3. Use `Ctrl+↓` to make the window translucent over the cockpit, `Ctrl+↑` to
   bring it back.

## Keyboard flow

Everything is one-handed so your other hand stays on the stick/yoke:

| Key | Action |
| --- | --- |
| `Space` / `Enter` | Check the highlighted item and advance |
| `↑` / `↓` (or `K` / `J`) | Move the highlight |
| `[` / `]` (or `PgUp` / `PgDn`) | Previous / next checklist |
| `E` | Jump straight to the first emergency checklist |
| `R` | Reset the current checklist |
| `Ctrl+↑` / `Ctrl+↓` | Window opacity up / down |

Red-dotted items are **memory items** — procedures you should eventually be able
to fly without reading.

## Adding aircraft

Drop another JSON file in `src/checklist_app/data/`. Schema:

```json
{
  "name": "Aircraft Full Name",
  "short_name": "SHORT",
  "source": "where the checklist came from",
  "vspeeds": [["Vr (rotate)", "55 KIAS"]],
  "sections": [
    {
      "name": "Before Start",
      "group": "Normal",            // Normal | Emergency | Abnormal
      "items": [
        {"challenge": "Brakes", "response": "SET"},
        {"challenge": "Mixture", "response": "FULL RICH", "memory": true},
        {"kind": "note", "challenge": "If engine is warm, skip priming."}
      ]
    }
  ]
}
```

It will appear in the aircraft dropdown automatically.
