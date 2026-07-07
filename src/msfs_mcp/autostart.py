"""Auto-start helper: make sure the HTTP MCP server is running locally.

Called by the companion GUI apps at launch as a convenience: it brings up the
streamable-http MCP server on a fixed local port so an external MCP client
(e.g. Claude Code) can attach at http://127.0.0.1:8787/mcp without the user
starting it by hand. The server runs HTTP so that:
  - "is it running?" is a simple TCP port check (no process scanning),
  - one instance outlives the app that started it and any MCP client can attach.

Note: the GUI apps do NOT talk to the sim *through* this server — they read sim
state in-process via ``msfs_mcp.simconnect_client.SimConnectClient`` directly
(lower latency, no round trip). The server this starts is purely for external
MCP clients. No Qt imports here — GUI apps wrap this in their own worker thread.
Set MSFS_COMPANION_AUTOSTART=0 to disable.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
LOG_PATH = Path.home() / ".msfs_companion" / "mcp-server.log"

# ensure_server_running() outcomes
DISABLED = "disabled"
ALREADY_RUNNING = "already-running"
STARTED = "started"
FAILED = "failed"


def server_url(host: str = DEFAULT_HOST, port: int | None = None) -> str:
    port = port or int(os.environ.get("MSFS_MCP_PORT", DEFAULT_PORT))
    return f"http://{host}:{port}/mcp"


def is_server_running(host: str = DEFAULT_HOST, port: int | None = None, timeout: float = 0.3) -> bool:
    port = port or int(os.environ.get("MSFS_MCP_PORT", DEFAULT_PORT))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


MAX_LOG_BYTES = 5_000_000  # truncate the server log past this on each spawn


def _spawn_detached(host: str, port: int) -> None:
    """Launch the server as its own process that survives the GUI closing."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Don't let the log grow without bound across months of sessions.
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES:
            LOG_PATH.unlink()
    except OSError:
        pass
    log_file = open(LOG_PATH, "ab")
    cmd = [
        sys.executable, "-m", "msfs_mcp.server",
        "--transport", "http", "--host", host, "--port", str(port),
    ]
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": log_file,
        "close_fds": True,
    }
    if os.name == "nt":
        # CREATE_NO_WINDOW: don't pop a console window for the background server.
        # (DETACHED_PROCESS lets a console app allocate its own visible window —
        # that's the "extra command window" nobody wants.)
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    finally:
        log_file.close()  # child has its own dup'd fd; don't leak ours


def ensure_server_running(
    host: str = DEFAULT_HOST,
    port: int | None = None,
    spawn=_spawn_detached,
    wait_s: float = 4.0,
) -> str:
    """Start the shared MCP server if it isn't already up.

    Returns one of DISABLED / ALREADY_RUNNING / STARTED / FAILED.
    """
    if os.environ.get("MSFS_COMPANION_AUTOSTART", "1").lower() in ("0", "false", "no"):
        return DISABLED
    port = port or int(os.environ.get("MSFS_MCP_PORT", DEFAULT_PORT))
    if is_server_running(host, port):
        return ALREADY_RUNNING
    try:
        spawn(host, port)
    except Exception:
        return FAILED
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if is_server_running(host, port):
            return STARTED
        time.sleep(0.2)
    return FAILED
