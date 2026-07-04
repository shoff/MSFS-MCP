"""Layer 2 — FSUIPC7 offsets.

Bridges to the FSUIPC7 offset table (Paul Henty's ``fsuipc`` module). Covers
values not cleanly exposed by SimConnect and gives a stable address space.
Requires FSUIPC7 installed and running alongside MSFS.

Offsets are specified as (offset, type) where type is one of FSUIPC's codes:
  'b'  signed byte      'B'  unsigned byte
  'h'  signed short     'H'  unsigned short
  'd'  signed int       'u'  unsigned int
  'l'  signed long long 'L'  unsigned long long
  'f'  double (float64) 's'  string (give length via ('s', N))
See the FSUIPC offset status PDF for the full table.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .config import CONFIG
from .simconnect_client import LayerUnavailable

log = logging.getLogger("msfs_mcp.fsuipc")

# A few well-known offsets so the layer is useful out of the box.
KNOWN_OFFSETS: dict[str, tuple[int, str]] = {
    "latitude_raw": (0x0560, "l"),       # *90/(10001750*65536*65536) -> degrees
    "longitude_raw": (0x0568, "l"),      # *360/(65536^4) -> degrees
    "altitude_m_frac": (0x0570, "L"),    # 32.32 fixed point metres
    "heading_true_raw": (0x0580, "u"),   # *360/(65536*65536) -> degrees
    "ias_knots_x128": (0x02BC, "d"),     # /128 -> knots IAS
    "gs_x65536": (0x02B4, "u"),          # /65536 -> m/s groundspeed
    "on_ground": (0x0366, "H"),          # 0 air, 1 ground
    "pause_flag": (0x0264, "H"),         # 0 running, !=0 paused
    "sim_rate_x256": (0x0C1A, "H"),      # /256 -> sim rate
    "parking_brake": (0x0BC8, "H"),      # 0 off, 32767 on
}


class FsuipcClient:
    def __init__(self) -> None:
        self._fs: Any = None
        self._lock = threading.Lock()
        self._import_error: str | None = None
        try:
            from fsuipc import FSUIPC  # noqa: F401
            self._FSUIPC = FSUIPC
        except Exception as exc:
            self._import_error = f"{type(exc).__name__}: {exc}"
            log.warning("fsuipc import failed: %s", self._import_error)

    @property
    def connected(self) -> bool:
        return self._fs is not None

    def _ensure(self) -> None:
        if not CONFIG.enable_fsuipc:
            raise LayerUnavailable("FSUIPC layer disabled (MSFS_ENABLE_FSUIPC=false).")
        if self._import_error:
            raise LayerUnavailable(
                f"fsuipc module unavailable: {self._import_error}. Install FSUIPC7 and the "
                "'fsuipc' Python module; both are Windows-only."
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
                self._fs = self._FSUIPC()
                log.info("FSUIPC connected.")
            except Exception as exc:
                self._fs = None
                raise LayerUnavailable(
                    f"Could not connect to FSUIPC7 ({exc}). Is FSUIPC7 running?"
                ) from exc
        return self.status()

    def disconnect(self) -> None:
        with self._lock:
            if self._fs is not None:
                try:
                    self._fs.close()
                except Exception:
                    pass
            self._fs = None

    def status(self) -> dict[str, Any]:
        return {
            "layer": "fsuipc",
            "enabled": CONFIG.enable_fsuipc,
            "import_ok": self._import_error is None,
            "import_error": self._import_error,
            "connected": self.connected,
            "known_offsets": sorted(KNOWN_OFFSETS),
        }

    def read(self, offset: int, type_code: str, length: int | None = None) -> Any:
        """Read one offset. For strings pass type_code='s' and a length."""
        self._ensure()
        spec = (offset, (type_code, length)) if length else (offset, type_code)
        with self._lock:
            try:
                prepared = self._fs.prepare_data([spec], True)
                return prepared.read()[0]
            except Exception as exc:
                raise LayerUnavailable(f"FSUIPC read 0x{offset:04X} failed: {exc}") from exc

    def read_known(self, key: str) -> Any:
        if key not in KNOWN_OFFSETS:
            raise LayerUnavailable(f"Unknown offset key '{key}'. See status().known_offsets.")
        offset, type_code = KNOWN_OFFSETS[key]
        return self.read(offset, type_code)

    def write(self, offset: int, type_code: str, value: Any) -> None:
        self._ensure()
        with self._lock:
            try:
                prepared = self._fs.prepare_data([(offset, type_code)], False)
                prepared.write([value])
            except Exception as exc:
                raise LayerUnavailable(f"FSUIPC write 0x{offset:04X} failed: {exc}") from exc


FSUIPC = FsuipcClient()
