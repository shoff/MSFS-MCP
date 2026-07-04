"""Layer 1 — SimConnect.

Wraps python-SimConnect (``SimConnect`` on PyPI). Connects to a running MSFS
on the same machine (or LAN via a SimConnect.cfg). Everything here degrades
gracefully: if the dependency is missing, we're not on Windows, or the sim
isn't running, methods raise ``LayerUnavailable`` with an actionable message
rather than crashing the server.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .config import CONFIG

log = logging.getLogger("msfs_mcp.simconnect")


class LayerUnavailable(RuntimeError):
    """Raised when a capability layer can't service a request."""


class SimConnectClient:
    def __init__(self) -> None:
        self._sm: Any = None
        self._aq: Any = None        # AircraftRequests
        self._ae: Any = None        # AircraftEvents
        self._lock = threading.Lock()
        self._import_error: str | None = None
        try:
            # Imported lazily so the package installs/loads on non-Windows hosts.
            from SimConnect import AircraftEvents, AircraftRequests, SimConnect  # noqa: F401
            self._SimConnect = SimConnect
            self._AircraftRequests = AircraftRequests
            self._AircraftEvents = AircraftEvents
        except Exception as exc:  # ImportError on non-Windows, etc.
            self._import_error = f"{type(exc).__name__}: {exc}"
            log.warning("SimConnect import failed: %s", self._import_error)

    # -- connection management ------------------------------------------- #
    @property
    def connected(self) -> bool:
        return self._sm is not None and getattr(self._sm, "ok", False)

    def _ensure(self) -> None:
        if not CONFIG.enable_simconnect:
            raise LayerUnavailable("SimConnect layer disabled (MSFS_ENABLE_SIMCONNECT=false).")
        if self._import_error:
            raise LayerUnavailable(
                "python-SimConnect unavailable: "
                f"{self._import_error}. SimConnect is Windows-only and needs MSFS's "
                "SimConnect.dll. Run this server on the Windows host where MSFS runs."
            )
        if not self.connected:
            self.connect()

    def connect(self) -> dict[str, Any]:
        with self._lock:
            if self.connected:
                return self.status()
            if self._import_error:
                raise LayerUnavailable(self._import_error)
            try:
                self._sm = self._SimConnect()
                self._aq = self._AircraftRequests(self._sm, _time=CONFIG.simconnect_cache_ms)
                self._ae = self._AircraftEvents(self._sm)
                log.info("SimConnect connected.")
            except Exception as exc:
                self._sm = None
                raise LayerUnavailable(
                    f"Could not connect to MSFS via SimConnect ({exc}). "
                    "Is the sim running and fully loaded into a flight?"
                ) from exc
        return self.status()

    def disconnect(self) -> None:
        with self._lock:
            if self._sm is not None:
                try:
                    self._sm.exit()
                except Exception:
                    pass
            self._sm = self._aq = self._ae = None

    def status(self) -> dict[str, Any]:
        return {
            "layer": "simconnect",
            "enabled": CONFIG.enable_simconnect,
            "import_ok": self._import_error is None,
            "import_error": self._import_error,
            "connected": self.connected,
        }

    # -- SimVar read / write --------------------------------------------- #
    def get(self, name: str) -> Any:
        """Read a SimVar by SDK name. Supports indexed vars like 'TURB_ENG_N1:1'."""
        self._ensure()
        with self._lock:
            try:
                value = self._aq.get(name)
            except Exception as exc:
                raise LayerUnavailable(f"Failed reading SimVar '{name}': {exc}") from exc
        if value is None:
            raise LayerUnavailable(
                f"SimVar '{name}' returned no data — check the exact SDK spelling/index."
            )
        if isinstance(value, bytes):
            value = value.decode(errors="replace").rstrip("\x00")
        return value

    def get_many(self, names: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for n in names:
            try:
                out[n] = self.get(n)
            except LayerUnavailable as exc:
                out[n] = {"error": str(exc)}
        return out

    def set(self, name: str, value: float) -> None:
        self._ensure()
        with self._lock:
            try:
                self._aq.set(name, value)
            except Exception as exc:
                raise LayerUnavailable(f"Failed writing SimVar '{name}': {exc}") from exc

    # -- Events ----------------------------------------------------------- #
    def trigger(self, event_name: str, value: int | None = None) -> None:
        """Fire a SimConnect Event. Pass ``value`` for events that take a parameter."""
        self._ensure()
        with self._lock:
            try:
                event = self._ae.find(event_name)
                if event is None:
                    raise LayerUnavailable(f"Unknown event '{event_name}'.")
                event(value) if value is not None else event()
            except LayerUnavailable:
                raise
            except Exception as exc:
                raise LayerUnavailable(f"Failed triggering event '{event_name}': {exc}") from exc


SIMCONNECT = SimConnectClient()
