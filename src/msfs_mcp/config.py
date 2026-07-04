"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    simconnect_cache_ms: int = _int("MSFS_SIMCONNECT_CACHE_MS", 200)
    enable_simconnect: bool = _bool("MSFS_ENABLE_SIMCONNECT", True)
    enable_fsuipc: bool = _bool("MSFS_ENABLE_FSUIPC", True)
    enable_memory: bool = _bool("MSFS_ENABLE_MEMORY", False)
    process_name: str = os.getenv("MSFS_PROCESS_NAME", "FlightSimulator2024.exe")
    log_level: str = os.getenv("MSFS_LOG_LEVEL", "INFO").upper()


CONFIG = Config()
