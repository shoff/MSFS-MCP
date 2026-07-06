"""Background link to a running MSFS via the repo's SimConnect layer.

Polls the watched SimVars on a worker thread and emits their values; the GUI
decides what to do with them. Degrades exactly like the MCP server does: no
SimConnect / not Windows / sim not running -> state 'offline', periodic
retries, zero crashes.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QThread, pyqtSignal

POLL_S = 0.5
RETRY_S = 5.0

STATE_OFFLINE = "offline"      # can't connect (or SimConnect not available here)
STATE_CONNECTING = "connecting"
STATE_LIVE = "live"


class McpAutostartWorker(QThread):
    """Fire-and-report: make sure the shared MCP server is up (see msfs_mcp.autostart)."""

    result = pyqtSignal(str)  # disabled | already-running | started | failed

    def run(self):
        try:
            from msfs_mcp.autostart import ensure_server_running

            self.result.emit(ensure_server_running())
        except Exception:
            self.result.emit("failed")


class SimLink(QThread):
    values_read = pyqtSignal(dict)   # {simvar: value}
    state_changed = pyqtSignal(str)  # offline | connecting | live

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watch: set[str] = set()
        self._watch_lock = threading.Lock()
        self._stop = threading.Event()
        self._kick = threading.Event()   # wake the retry sleep for manual reconnect
        self._client = None
        self._state = ""

    # ------------------------------------------------------------- control
    def set_watch(self, names: set[str]) -> None:
        with self._watch_lock:
            self._watch = set(names)

    def request_reconnect(self) -> None:
        self._kick.set()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()

    # -------------------------------------------------------------- worker
    def _emit_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _make_client(self):
        try:
            from msfs_mcp.simconnect_client import SimConnectClient

            return SimConnectClient()
        except Exception:
            return None

    def run(self):  # noqa: C901 - simple poll loop
        self._client = self._make_client()
        if self._client is None:
            self._emit_state(STATE_OFFLINE)

        while not self._stop.is_set():
            client = self._client
            if client is None:
                # SimConnect layer can't even import here; retry only on manual kick
                self._kick.wait(timeout=RETRY_S * 4)
                self._kick.clear()
                if not self._stop.is_set():
                    self._client = self._make_client()
                continue

            if not client.connected:
                self._emit_state(STATE_CONNECTING)
                try:
                    client.connect()
                except Exception:
                    self._emit_state(STATE_OFFLINE)
                    self._kick.wait(timeout=RETRY_S)
                    self._kick.clear()
                    continue

            self._emit_state(STATE_LIVE)
            with self._watch_lock:
                watch = list(self._watch)
            if watch:
                try:
                    values = client.get_many(watch)
                except Exception:
                    values = {}
                good = {
                    k: v for k, v in values.items()
                    if not isinstance(v, dict) and v is not None
                }
                if not good and watch:
                    # every read failed -> assume the sim went away
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    self._emit_state(STATE_OFFLINE)
                    self._kick.wait(timeout=RETRY_S)
                    self._kick.clear()
                    continue
                self.values_read.emit(good)
            self._kick.wait(timeout=POLL_S)
            self._kick.clear()
