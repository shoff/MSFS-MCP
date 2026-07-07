"""Rudder / HID diagnostic — run this in the app's venv and share the output.

The controls app reads SDL-invisible gear (the VelocityOne rudder pedals) off
the raw USB-HID bus via the ``hid`` package. Every step of that path is wrapped
in try/except in the app so the GUI never crashes — which also means a failure
is completely silent. This script makes each step LOUD so we can see exactly
where it breaks and capture the byte layout needed to parse the axes.

Run it from the repo root with the app's virtual environment:

    .venv\\Scripts\\python scripts\\diag_hid.py

It does four things and prints a clear result for each:

  1. Can we import ``hid`` at all?  (prints the real error if not)
  2. Enumerate EVERY HID device Windows exposes, flagging rudder candidates.
  3. Open the best candidate for reading.
  4. Live-read it: press each pedal / slide the rudder, then Ctrl+C for a
     per-byte range summary that reveals which bytes are the axes.

Nothing here writes to your system or the sim; it only reads input reports.
"""

from __future__ import annotations

import sys
import traceback

# Turtle Beach vendor id; the product id is a guess, so we match on vendor.
RUDDER_VID = 0x10F5
NAME_HINTS = ("rudder", "velocity", "turtle", "pedal")


def hr(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def step1_import():
    hr("STEP 1 — import hid")
    try:
        import hid  # noqa: F401
    except Exception:
        print("FAILED to import the 'hid' package. Full error:\n")
        traceback.print_exc()
        print(
            "\nWhat this means:\n"
            "  * If it says the package is missing, hidapi didn't install.\n"
            "    Re-run run-controls.cmd, or:  pip install hidapi\n"
            "  * If it mentions a DLL / 'Unable to load library', the package\n"
            "    installed but its native hidapi.dll can't load. Tell me the\n"
            "    exact message — that's a different fix (a bundled-DLL problem),\n"
            "    not a missing-package problem.\n"
        )
        return None
    print("OK — 'hid' imported.")
    loc = getattr(hid, "__file__", "?")
    print(f"     module: {loc}")
    return hid


def step2_enumerate(hid):
    hr("STEP 2 — enumerate all HID devices")
    try:
        devices = list(hid.enumerate())
    except Exception:
        print("hid.enumerate() raised:\n")
        traceback.print_exc()
        return []
    if not devices:
        print("hid.enumerate() returned NOTHING. hidapi loaded but sees no HID\n"
              "devices at all — unusual on Windows. Tell me and we'll dig in.")
        return []

    print(f"{len(devices)} HID interface(s) found:\n")
    candidates = []
    for i, d in enumerate(devices):
        vid = int(d.get("vendor_id") or 0)
        pid = int(d.get("product_id") or 0)
        up = int(d.get("usage_page") or 0)
        usage = int(d.get("usage") or 0)
        product = (d.get("product_string") or "").strip()
        maker = (d.get("manufacturer_string") or "").strip()
        is_cand = vid == RUDDER_VID or any(
            h in (product + " " + maker).lower() for h in NAME_HINTS
        )
        flag = "  <-- RUDDER CANDIDATE" if is_cand else ""
        print(f"[{i:2}] VID:PID={vid:#06x}:{pid:#06x}  "
              f"usage_page={up:#04x} usage={usage:#04x}  "
              f"{maker!r} / {product!r}{flag}")
        if is_cand:
            candidates.append((i, d))

    if not candidates:
        print("\nNo device matched vendor 0x10F5 or a rudder-ish name.\n"
              "=> The pedals are NOT on the HID bus under the id we expect.\n"
              "   Copy the FULL list above to me — we'll find the real one\n"
              "   (or the pedals may present only via XInput/DirectInput).")
    else:
        print(f"\n{len(candidates)} candidate(s) flagged above.")
    return candidates


def step3_open(hid, candidates):
    hr("STEP 3 — open a candidate for reading")
    if not candidates:
        print("No candidate to open (see step 2). Stopping here.")
        return None, None
    for idx, d in candidates:
        path = d.get("path")
        product = (d.get("product_string") or "").strip()
        print(f"Trying [{idx}] {product!r} ...")
        try:
            dev = hid.device()
            dev.open_path(path)
            dev.set_nonblocking(True)
            print("  OPENED OK. Using this one for the live read.")
            return dev, d
        except Exception as exc:
            print(f"  could NOT open: {exc!r}")
    print("\nEvery candidate failed to open. On Windows this usually means the\n"
          "device is held exclusively by another process. Close MSFS and any\n"
          "Turtle Beach / VelocityOne app, then re-run this script.")
    return None, None


def step4_live(dev, d):
    hr("STEP 4 — live read (press each pedal, then Ctrl+C)")
    product = (d.get("product_string") or "").strip()
    print(f"Reading from {product!r}.")
    print("Now, slowly: press the LEFT toe brake, the RIGHT toe brake, then\n"
          "slide the rudder fully left and right. Watch the byte values move.\n"
          "Press Ctrl+C when done for a summary.\n")

    mins: dict[int, int] = {}
    maxs: dict[int, int] = {}
    last: list[int] = []
    try:
        while True:
            data = dev.read(64)
            if not data:
                continue
            data = list(data)
            for i, b in enumerate(data):
                mins[i] = b if i not in mins else min(mins[i], b)
                maxs[i] = b if i not in maxs else max(maxs[i], b)
            if data != last:
                changed = [i for i in range(len(data))
                           if i >= len(last) or data[i] != last[i]]
                hexs = " ".join(f"{b:02x}" for b in data)
                print(f"len={len(data):2}  changed@{changed}  {hexs}")
                last = data
    except KeyboardInterrupt:
        pass
    finally:
        try:
            dev.close()
        except Exception:
            pass

    hr("SUMMARY — per-byte range (biggest movers = the axes)")
    if not mins:
        print("No reports were read. The device opened but sent no input\n"
              "reports while you pressed the pedals. Tell me — that points at\n"
              "a device that needs a feature report / different read call.")
        return
    ranges = sorted(((maxs[i] - mins[i], i) for i in mins), reverse=True)
    print("byte  min  max  range")
    for rng, i in ranges:
        bar = "#" * min(rng // 4, 40)
        print(f"{i:4}  {mins[i]:3}  {maxs[i]:3}  {rng:5}  {bar}")
    print("\nBytes with a large range are the moving axes. Adjacent byte pairs\n"
          "that BOTH move together are one 16-bit axis. Paste this whole\n"
          "summary back to me and I'll fix the axis parsing to match exactly.")


def main() -> int:
    print("MSFS Companion — HID rudder diagnostic")
    print(f"python: {sys.version.split()[0]}  exe: {sys.executable}")
    hid = step1_import()
    if hid is None:
        return 1
    candidates = step2_enumerate(hid)
    dev, d = step3_open(hid, candidates)
    if dev is not None:
        step4_live(dev, d)
    print("\nDone. Copy everything above (especially steps 2 and the summary).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
