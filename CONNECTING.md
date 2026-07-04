# Connecting Claude Code to the MSFS 2024 MCP Server

The connection is automatic once you register the server **one time**. You never
run the server manually — Claude Code launches it as a subprocess whenever a
session needs it, and my tools auto-connect to the sim on first use.

## One-time setup

From the extracted project folder (adjust `C:\Projects\msfs2024-mcp` to your path):

```powershell
cd C:\Projects\msfs2024-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

Then register the server with Claude Code:

```powershell
claude mcp add msfs2024 --scope user -e MSFS_ENABLE_FSUIPC=true -e MSFS_ENABLE_MEMORY=false -- "C:\Projects\msfs2024-mcp\.venv\Scripts\python.exe" -m msfs_mcp.server
```

- `--scope user` — works from any folder you launch Claude Code in.
- Point at the **venv's** `python.exe` (full path) — that's the one with the deps installed.
- Flip `MSFS_ENABLE_MEMORY=true` later if you want the raw-memory layer (then run the
  terminal as Administrator).

Verify: `claude mcp list` should show `msfs2024`.

## Every flight session

1. **Start MSFS 2024** and load into a flight (parked on a runway is fine —
   SimConnect has no data at the main menu).
2. **Start Claude Code**: `claude`
3. Type `/mcp` — you should see `msfs2024` listed with its tools.
4. Ask in plain English: *"What's my current altitude, heading, and airspeed?"*

Order doesn't strictly matter — the server boots fine with MSFS closed and just
reports "not connected" until a flight is loaded.

## First-run validation prompt

Paste this into Claude Code to test the whole chain:

> Call connection_status, then get_aircraft_state, and tell me what aircraft
> I'm in and whether I'm on the ground.

`simconnect.connected: true` + real numbers = fully operational.

## Troubleshooting

| Symptom | Likely cause / fix |
| ------- | ------------------ |
| `/mcp` shows the server failed to start | Registration points at the wrong python. Re-run `claude mcp add` with the full path to `.venv\Scripts\python.exe`. |
| Tools return "Could not connect to MSFS" | Sim not running, or still at the main menu — load into a flight. |
| FSUIPC tools return "unavailable" | FSUIPC7 isn't installed/running, or `MSFS_ENABLE_FSUIPC` is false. |
| Memory tools return "disabled" | By design — set `MSFS_ENABLE_MEMORY=true` and run as Administrator to opt in. |
| A SimVar returns "no data" | Check the exact SDK spelling/index (e.g. `TURB_ENG_N1:1`), or the loaded aircraft doesn't implement that var. |
