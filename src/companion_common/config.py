"""Load LLM settings from a config file, so you don't need OS environment vars.

A plain ``key = value`` text file (``#`` or ``;`` starts a comment). The
recognized keys map to the environment variables the LLM layer reads; a value
is applied only if that environment variable isn't already set, so a real env
var always overrides the file (handy for a one-off session), and the file is
the default the rest of the time.

Recognized keys::

    provider          = anthropic | openai | local   (aliases ollama/llama -> local)
    model             = <model id>                    (optional; provider default otherwise)
    base_url          = <url>                          (optional; local/OpenAI-compatible endpoint)
    openai_api_key    = <key>                           (for the openai provider)
    anthropic_api_key = <key>                           (for the anthropic provider)

Search order (first existing file wins):

    1. $MSFS_COMPANION_CONFIG                 (explicit path)
    2. ./msfs-companion.conf                  (next to where the app was launched)
    3. ~/.msfs_companion/config.conf          (per-user, survives re-clones)

Call ``apply()`` once at startup (both apps do this in ``main()``).
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_ENV = "MSFS_COMPANION_CONFIG"
FILE_NAME = "msfs-companion.conf"
HOME_CONFIG = Path.home() / ".msfs_companion" / "config.conf"

# friendly key -> the environment variable the app actually reads
KEY_TO_ENV = {
    "provider": "MSFS_COMPANION_LLM",
    "model": "MSFS_COMPANION_MODEL",
    "base_url": "MSFS_COMPANION_LLM_BASE_URL",
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    # When true, the controls app builds an AI-tailored setup automatically on
    # launch / aircraft change (default on). Set to false to require the button.
    "auto_setup": "MSFS_COMPANION_AUTO_SETUP",
    # When true, the built setup is written into your matching MSFS input
    # profiles automatically (with backups). Default off — writing changes real
    # sim files, so it's opt-in.
    "auto_write": "MSFS_COMPANION_AUTO_WRITE",
}


def config_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get(CONFIG_ENV)
    if explicit:
        paths.append(Path(explicit))
    paths.append(Path.cwd() / FILE_NAME)
    paths.append(HOME_CONFIG)
    return paths


def find_config() -> Path | None:
    for path in config_paths():
        if path.is_file():
            return path
    return None


def parse(text: str) -> dict[str, str]:
    """Parse the file into {ENV_VAR: value}, ignoring unknown/blank keys."""
    settings: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        env_name = KEY_TO_ENV.get(key)
        if env_name and value:
            settings[env_name] = value
    return settings


def apply(path: Path | None = None) -> Path | None:
    """Fill os.environ from the config file for any keys not already set.

    A real environment variable always wins (values are applied with
    ``setdefault``). Returns the file that was applied, or ``None`` if none was
    found or it couldn't be read.
    """
    path = path or find_config()
    if path is None or not path.is_file():
        return None
    try:
        settings = parse(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    for env_name, value in settings.items():
        os.environ.setdefault(env_name, value)
    return path
