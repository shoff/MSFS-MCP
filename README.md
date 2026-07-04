# msfs2024-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for **Microsoft Flight Simulator 2024**. It lets an MCP client (Claude Desktop, Claude Code, etc.) read live sim state and drive the aircraft across three capability layers:

| Layer | Source | Covers | Setup |
| ----- | ------ | ------ | ----- |
| **1. SimConnect** | Official Microsoft API (`python-SimConnect`) | Thousands of SimVars, Events (controls), bundled aircraft state | MSFS running |
| **2. FSUIPC7** | Offset table (`fsuipc` module) | Values SimConnect doesn't cleanly expose; stable offsets | FSUIPC7 installed + running |
| **3. Raw memory** | `pymem` / ReadProcessMemory | Escape hatch for anything else | Opt-in, admin rights |

> **Reality check:** SimConnect, FSUIPC, and raw memory are **Windows-only** and require a *running* MSFS on the same machine (or LAN via `SimConnect.cfg`). Run this server on that Windows host. Every layer **degrades gracefully** — if a layer isn't available, its tools return a structured `{ "ok": false, "error": ... }` explaining why, instead of crashing the server. So the server boots and the catalog/discovery tools work even before MSFS is up.

## Install (on the Windows host with MSFS)

```powershell
git clone <your-repo-url> msfs2024-mcp
cd msfs2024-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env   # then edit if you like
```

Layer prerequisites:
- **SimConnect** — installed automatically with the `SimConnect` pip package, which ships its own `SimConnect.dll`. Just have MSFS running and loaded into a flight.
- **FSUIPC7** — download and run [FSUIPC7](http://www.fsuipc.com/) (free for basic offset access). Leave it running alongside MSFS.
- **Raw memory** — set `MSFS_ENABLE_MEMORY=true` in `.env` and run the server **as Administrator**. Off by default.

## Verify it works

```powershell
python scripts\smoke_test.py
```

With MSFS loaded into a flight you'll see a live aircraft-state snapshot and an event round-trip (nav lights toggle). Off-Windows or with the sim closed, it prints layer health and exits cleanly — which is how you know the graceful-degradation path is intact.

Platform-independent tests (catalog integrity + degradation) run anywhere:

```bash
pip install -e ".[dev]"
pytest -q
```

## Wire into an MCP client

**Claude Desktop / Claude Code** — add to your MCP config (`claude_desktop_config.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "msfs2024": {
      "command": "python",
      "args": ["-m", "msfs_mcp.server"],
      "cwd": "C:\\path\\to\\msfs2024-mcp",
      "env": { "MSFS_ENABLE_FSUIPC": "true", "MSFS_ENABLE_MEMORY": "false" }
    }
  }
}
```

(If you `pip install -e .`, you can use the `msfs-mcp` console script instead of `python -m msfs_mcp.server`.)

## Tool surface (23 tools)

**Connection** — `connection_status`, `connect_sim`

**SimConnect / SimVars** — `get_simvar`, `get_simvars`, `set_simvar`, `get_aircraft_state`

**SimConnect / Events & autopilot** — `trigger_event`, `autopilot_set_heading`, `autopilot_set_altitude`, `autopilot_set_vertical_speed`, `autopilot_toggle_master`

**Discovery** — `list_simvars`, `list_events` (searchable by keyword/category)

**FSUIPC** — `fsuipc_status`, `fsuipc_read_offset`, `fsuipc_read_known`, `fsuipc_write_offset`

**Raw memory** — `memory_status`, `memory_attach`, `memory_module_base`, `memory_read`, `memory_read_pointer_chain`, `memory_write`

**Resources** — `msfs://telemetry/state`, `msfs://catalog/simvars`, `msfs://catalog/events`

**Prompts** — `preflight_briefing`, `fly_to_heading_altitude`

### Examples (natural language to the MCP client)

- "What's my current altitude and heading?" → `get_aircraft_state`
- "Find me every autopilot-related variable." → `list_simvars(category="autopilot")`
- "Raise the landing gear and set flaps to the first notch." → `trigger_event('GEAR_UP')`, `trigger_event('FLAPS_INCR')`
- "Engage the autopilot for heading 270 at 8000 feet." → `autopilot_toggle_master`, `autopilot_set_heading(270)`, `autopilot_set_altitude(8000)`
- "Read FSUIPC offset 0x0560 as a long." → `fsuipc_read_offset('0x0560', 'l')`

## Safety notes

- **Writes are real.** `set_simvar`, `trigger_event`, and `fsuipc_write_offset` change the running sim. Fine for your own local flight; think before scripting them.
- **Raw memory is double-gated.** It requires both `MSFS_ENABLE_MEMORY=true` *and* `allow_write=true` per write call, because bad writes can crash MSFS. Pointer chains break on most sim updates — keep them version-pinned.
- **Reads are harmless.** All read paths are observation-only.

## Extending the catalog

`src/msfs_mcp/catalog.py` is a curated subset, not the full SDK. The generic `get_simvar` / `set_simvar` / `trigger_event` tools reach **any** SimVar or Event by exact SDK name — add entries to the catalog only to make them discoverable. Full reference: the [MSFS SDK SimVars](https://docs.flightsimulator.com/html/Programming_Tools/SimVars/Simulation_Variables.htm) and [Event IDs](https://docs.flightsimulator.com/html/Programming_Tools/Event_IDs/Event_IDs.htm) docs.

## Architecture

```
MCP client  ──stdio──▶  msfs_mcp.server (FastMCP, 23 tools)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                 ▼
     SimConnectClient   FsuipcClient      MemoryClient
     (SimConnect.dll)   (FSUIPC7)         (pymem)
              │               │                 │
              └──────── Microsoft Flight Simulator 2024 ────────┘
```

Each client is a singleton with lazy connect, a thread lock around the native handle, and a uniform `LayerUnavailable` error contract that the server renders as structured JSON.

## License

MIT
