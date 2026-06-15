"""Cross-cutting persistent settings shared by every tool.

A tiny JSON-backed store in the user's config directory. Tools read and write
small keys (last-used folders, window geometry, per-tool options, saved presets)
without caring where it lives on disk. Reads and writes never raise — settings
are a convenience, never load-bearing, so a corrupt or unwritable file degrades
to "no remembered state" rather than breaking a tool.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile

logger = logging.getLogger(__name__)
APP_NAME = "ChasersShenanigans"


def _config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


_PATH = os.path.join(_config_dir(), "settings.json")
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(_PATH, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
            if not isinstance(_cache, dict):
                _cache = {}
        except Exception:  # noqa: BLE001 — missing/corrupt file -> empty settings
            _cache = {}
    return _cache


def _save(data: dict) -> None:
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_PATH), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, _PATH)            # atomic on the same filesystem
    except Exception as exc:  # noqa: BLE001 — settings are never load-bearing
        logger.info("Could not save settings: %r", exc)


def get(key: str, default=None):
    return _load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 — intentional simple API
    data = _load()
    data[key] = value
    _save(data)


# ---- convenience helpers used across tools ----
def last_dir(tool: str, default: str = "") -> str:
    return get(f"{tool}.last_dir", default) or default


def remember_dir(tool: str, path: str) -> None:
    if not path:
        return
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if folder:
        set(f"{tool}.last_dir", folder)


def window_geometry(tool: str):
    return get(f"{tool}.geometry")


def remember_window(tool: str, geometry_hex: str) -> None:
    set(f"{tool}.geometry", geometry_hex)


def presets(tool: str) -> dict:
    return get(f"{tool}.presets", {}) or {}


def save_preset(tool: str, name: str, params: dict) -> None:
    table = presets(tool)
    table[name] = params
    set(f"{tool}.presets", table)


def delete_preset(tool: str, name: str) -> None:
    table = presets(tool)
    if name in table:
        del table[name]
        set(f"{tool}.presets", table)
