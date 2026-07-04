"""Layer 3 — raw process memory (escape hatch).

OFF by default. Direct reads of the MSFS process via pymem (ReadProcessMemory).
Use only for values the other two layers can't reach. Pointer chains break on
nearly every sim update, so treat anything here as volatile and version-pinned.

Safety posture:
  - Reads are unrestricted (observation only).
  - Writes are gated behind ``allow_write=True`` per call AND the layer being
    enabled, because poking arbitrary process memory can crash the sim.
"""

from __future__ import annotations

import logging
import struct
import threading
from typing import Any

from .config import CONFIG
from .simconnect_client import LayerUnavailable

log = logging.getLogger("msfs_mcp.memory")

_STRUCT = {
    "int32": ("<i", 4), "uint32": ("<I", 4),
    "int64": ("<q", 8), "uint64": ("<Q", 8),
    "float": ("<f", 4), "double": ("<d", 8),
    "byte": ("<b", 1), "ubyte": ("<B", 1),
}


class MemoryClient:
    def __init__(self) -> None:
        self._pm: Any = None
        self._lock = threading.Lock()
        self._import_error: str | None = None
        try:
            import pymem  # noqa: F401
            self._pymem = pymem
        except Exception as exc:
            self._import_error = f"{type(exc).__name__}: {exc}"
            log.warning("pymem import failed: %s", self._import_error)

    @property
    def attached(self) -> bool:
        return self._pm is not None

    def _ensure(self) -> None:
        if not CONFIG.enable_memory:
            raise LayerUnavailable(
                "Raw-memory layer disabled (set MSFS_ENABLE_MEMORY=true to opt in). "
                "Disabled by default because bad writes can crash the sim."
            )
        if self._import_error:
            raise LayerUnavailable(f"pymem unavailable: {self._import_error} (Windows-only).")
        if not self.attached:
            self.attach()

    def attach(self, process_name: str | None = None) -> dict[str, Any]:
        name = process_name or CONFIG.process_name
        with self._lock:
            if self.attached:
                return self.status()
            if self._import_error:
                raise LayerUnavailable(self._import_error)
            try:
                self._pm = self._pymem.Pymem(name)
                log.info("Attached to process %s (pid %s).", name, self._pm.process_id)
            except Exception as exc:
                self._pm = None
                raise LayerUnavailable(
                    f"Could not attach to '{name}' ({exc}). Check MSFS_PROCESS_NAME and "
                    "that the server runs with sufficient privileges."
                ) from exc
        return self.status()

    def detach(self) -> None:
        with self._lock:
            if self._pm is not None:
                try:
                    self._pm.close_process()
                except Exception:
                    pass
            self._pm = None

    def status(self) -> dict[str, Any]:
        return {
            "layer": "memory",
            "enabled": CONFIG.enable_memory,
            "import_ok": self._import_error is None,
            "import_error": self._import_error,
            "attached": self.attached,
            "process_name": CONFIG.process_name,
            "pid": getattr(self._pm, "process_id", None) if self.attached else None,
        }

    def module_base(self, module_name: str | None = None) -> int:
        self._ensure()
        mod = module_name or CONFIG.process_name
        try:
            m = self._pymem.process.module_from_name(self._pm.process_handle, mod)
            return int(m.lpBaseOfDll)
        except Exception as exc:
            raise LayerUnavailable(f"Module '{mod}' base lookup failed: {exc}") from exc

    def resolve_pointer_chain(self, base: int, offsets: list[int]) -> int:
        """Walk a multi-level pointer: addr = *(base); addr = *(addr+off) per offset."""
        self._ensure()
        addr = base
        try:
            for off in offsets[:-1]:
                addr = self._pm.read_ulonglong(addr + off)
            return addr + (offsets[-1] if offsets else 0)
        except Exception as exc:
            raise LayerUnavailable(f"Pointer-chain resolve failed at {hex(addr)}: {exc}") from exc

    def read(self, address: int, type_name: str) -> Any:
        self._ensure()
        if type_name not in _STRUCT:
            raise LayerUnavailable(f"Unsupported type '{type_name}'. Use one of {list(_STRUCT)}.")
        fmt, size = _STRUCT[type_name]
        with self._lock:
            try:
                raw = self._pm.read_bytes(address, size)
            except Exception as exc:
                raise LayerUnavailable(f"Read at {hex(address)} failed: {exc}") from exc
        return struct.unpack(fmt, raw)[0]

    def write(self, address: int, type_name: str, value: Any, allow_write: bool = False) -> None:
        if not allow_write:
            raise LayerUnavailable(
                "Memory write refused: pass allow_write=true to confirm. This can crash MSFS."
            )
        self._ensure()
        if type_name not in _STRUCT:
            raise LayerUnavailable(f"Unsupported type '{type_name}'.")
        fmt, _ = _STRUCT[type_name]
        with self._lock:
            try:
                self._pm.write_bytes(address, struct.pack(fmt, value), struct.calcsize(fmt))
            except Exception as exc:
                raise LayerUnavailable(f"Write at {hex(address)} failed: {exc}") from exc


MEMORY = MemoryClient()
