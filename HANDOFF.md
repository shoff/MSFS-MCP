# Handoff — MSFS 2024 Companion (controls app focus)

This document hands off the current state of the `controls_app` work to a new
agent. Read it fully before touching code. The user is frustrated because the
graphical controls app does not yet work reliably with their real hardware —
that is the whole point of the app, so **do not suggest turning it into a
text-only advisor.**

## The user's setup (critical context)

- **OS:** Windows. Runs the app *alongside* MSFS 2024.
- **Hardware:**
  - Honeycomb **Alpha** yoke (USB `294B:1900`) — detected fine by SDL/pygame.
  - Honeycomb **Bravo** throttle quadrant (USB `294B:1901`) — detected fine.
  - Turtle Beach **VelocityOne Rudder** pedals (USB vendor `10F5`) — **NOT seen by
    SDL/pygame** even though Windows + MSFS see it. This is the #1 pain point.
- The dev environment (where you, the agent, run) is **Linux with no pygame,
  no hidapi, and none of the physical devices.** You cannot reproduce the
  hardware behavior. Everything hardware-related must be reasoned about and
  covered with fakes/mocks in offscreen smokes. **Be honest about this limit.**

## Repo / workflow

- GitHub: `shoff/MSFS-MCP`. Work on `main`, commit + push each change.
- Three packages under `src/`: `msfs_mcp` (MCP server), `checklist_app`,
  `controls_app`, plus shared `companion_common`. Install extras:
  `pip install -e ".[controls,openai]"`.
- Tests: `python -m pytest -q` (79 passing, pure-logic, no Qt/hardware).
- **GUI smokes are NOT in the repo** — they were written ad-hoc under a scratch
  dir and run with `QT_QPA_PLATFORM=offscreen python <file>`. You'll need to
  recreate them as needed (patterns below). Consider moving them into `tests/`.
- Commit trailer used this session (keep or adapt):
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and a
  `Claude-Session:` line. Do NOT put a model identifier in commits.

## How live input flows (controls app)

```
physical device
  -> InputMonitor (src/controls_app/input_monitor.py)
       - SDL/pygame path: _sticks[device_id], polled 30Hz in _poll()
       - HID fallback path: _hid[device_id] (HidAxisDevice), polled in _poll_hid()
       - emits Qt signals: button_changed / axis_changed / hat_changed (device_id, index, value)
  -> MainWindow._on_button/_on_axis/_on_hat (src/controls_app/app.py)
       - updates the diagram (DeviceView) and raw panel (RawDeviceView)
       - during Learn/Calibrate: captures index -> control via InputMap
  -> InputMap (src/controls_app/input_map.py): control_id <-> physical index
  -> resolve_writes (src/controls_app/msfs_profiles.py): plan + InputMap -> MSFS AceXML bindings
```

Key idea: **the app cannot know which pygame axis/button index maps to which
control** — it differs per unit and per platform, and pygame indices are not the
same as MSFS's. So the design relies on **Calibrate** (user operates each
control once) to learn the real indices. Defaults in `input_map.DEFAULT_MAPS`
are only guesses.

## OPEN ISSUES (in priority order)

### 1. Rudder pedals not working (HIGHEST — user is furious)
- Root cause: SDL/pygame filters HID devices by *usage page*; the VelocityOne
  Rudder declares a Simulation-Controls usage page (0x02) that SDL skips, so it
  never appears in pygame's joystick list.
- Fix in progress: read the device directly off the USB HID bus via **hidapi**.
  - `src/controls_app/hid_input.py`: `enumerate_devices()`, `HidReader`,
    `HidAxisDevice` (parses 16-bit LE axes from raw reports), `find_for_device()`.
  - `InputMonitor._open_hid_fallback()` matches a bindable device SDL missed to a
    HID device (by USB id / vendor `10F5` / product name) and opens it.
  - `InputMonitor._poll_hid()` emits `axis_changed` under `velocityone_rudder`.
- **Why it may STILL not work on the user's machine:**
  1. **hidapi was very likely never installed** — their `.venv` predates adding
     `hidapi` to the extras, and the launcher's `.deps-installed` marker skipped
     reinstall. JUST fixed by versioning the marker (`DEP_VERSION=3` in the
     `.cmd` files) so it reinstalls. **The user must `git pull` and re-run
     `run-controls.cmd`** for hidapi to install. This is the single most likely
     unblock. CONFIRM THIS FIRST.
  2. If hidapi is installed but the rudder still doesn't appear: get the user to
     open **🔎 Hardware** and report exactly what the "Raw USB scan" section
     lists (product name + `VID:PID` + usage). Then adjust `find_for_device`.
  3. HID axis parsing (`HidAxisDevice.poll`) is a *guess* (16-bit LE fields,
     auto-skip a constant report-id byte). The axis count/scaling may be wrong
     for this specific device. Use the raw bytes the user reports (which bytes
     change when they press each pedal) to fix the parsing. This is the part you
     cannot get right without the user's byte data.
- Smoke pattern: `smoke_hidrudder` faked `hid_input` (available/enumerate/HidReader)
  and drove `_open_hid_fallback` + `_poll_hid`; recreate similarly.

### 2. Calibrate button "doesn't work" on Bravo / rudder
- For the **rudder**: same root cause as #1 — no input events reach the app, so
  calibration never advances. Fixing #1 fixes this.
- For the **Bravo**: axis capture was too strict (required a full-range sweep).
  Just changed to "capture the axis with the biggest sweep, clear leader >0.5"
  (see `_on_axis` learn branch in `app.py`). Also calibration now forces the
  diagram view and shows a prominent accent banner so it's obviously running.
  **Unverified on real hardware** — confirm with the user that Calibrate now
  advances when they sweep a Bravo lever.
- Calibration flow lives in `app.py`: `_start_calibration`, `_calib_next`,
  `_calib_skip`, `_calib_restart`, `_calib_jump`, `_after_capture`,
  `_finish_calibration`, plus capture in `_begin_capture` / `_on_axis` /
  `_on_button` / `_on_hat`. Learn-mode gate: `view.learn_mode` (set by the
  Learn toggle, which calibration turns on).

### 3. Device diagrams must match real hardware
- The Alpha was corrected this session (grips: left = hat + white + TWO
  side-by-side rockers + trigger; right = TWO stacked rockers + white + red;
  switch panel order ALT, BAT, AVI1, AVI2). Defined in FOUR places that must
  stay in sync:
  1. `devices.py` `HONEYCOMB_ALPHA.inputs` (control ids + labels + kind)
  2. `device_views.py` `_alpha()` (drawn elements + positions)
  3. `input_map.py` `DEFAULT_MAPS["honeycomb_alpha"]` (guessed indices)
  4. `data/plans/c172s.json` + `pa28_181.json` (bindings reference control
     *labels* — must match `inputs` labels or `resolve_writes` skips them)
- **The user may find more diagram errors.** When fixing, change all four places.
  The `RawDeviceView` (🎛 Raw view) sidesteps this entirely — it reads real
  axis/button counts from the device — so encourage its use where the pretty
  diagram is wrong.

## What works / was done this session

- Multi-provider LLM (`companion_common/llm.py`): anthropic | openai | local
  (Ollama), config via `msfs-companion.conf` (`companion_common/config.py`) or
  env. Fixed OpenAI `max_tokens` -> `max_completion_tokens`.
- Live **AI Activity** tab (bottom pane) streams exact system prompt / request /
  schema / response.
- **🎛 Raw view** — accurate device-read panel (real counts from SDL/HID).
- **🔎 Hardware** dialog — lists SDL joysticks + raw USB HID scan; force-assign a
  device to a slot (persisted by name in `~/.msfs_companion/device_assignments.json`).
- **🧭 Calibrate** guided flow; **Verify live** with raw-input readout + sim chip.
- Auto AI setup + optional auto-write into MSFS profiles (`auto_write` config).
- Flow guide strip; hardware-missing banner; MCP server autostart with no console
  window (`CREATE_NO_WINDOW`).
- Fixed `fsuipc>=2.0.0` (impossible pin) -> moved fsuipc/pymem to a `transports`
  extra so GUI installs work.

## Honest guidance for the next agent

- **You cannot verify hardware fixes yourself.** Make the change, cover it with a
  mocked offscreen smoke, and then get a specific observation from the user
  (exact device name/bytes, whether an axis moves). Do not claim it's fixed
  without their confirmation.
- The rudder's HID byte layout is the crux and needs the user's real data. Ask
  for: open 🔎 Hardware, press left pedal / right pedal / slide rudder, and
  report which "live bytes" change for each.
- Keep changes small and committed; the user pulls frequently.
- Run `python -m pytest -q` before every push; keep it green.
