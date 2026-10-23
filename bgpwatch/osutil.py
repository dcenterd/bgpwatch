"""The few places where Windows and Linux differ, in one module."""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
APP = "bgpwatch"


def _local_appdata(env=os.environ) -> Path:
    return Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def state_dir(win: bool = IS_WINDOWS, env=os.environ) -> Path:
    """Logs, history database and settings.
    Windows: %LOCALAPPDATA%\\bgpwatch   Linux: $XDG_STATE_HOME or ~/.local/state/bgpwatch"""
    if win:
        return _local_appdata(env) / APP
    return Path(env.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP


def cache_dir(win: bool = IS_WINDOWS, env=os.environ) -> Path:
    """AS-name cache. Windows: %LOCALAPPDATA%\\bgpwatch\\cache   Linux: $XDG_CACHE_HOME or ~/.cache/bgpwatch"""
    if win:
        return _local_appdata(env) / APP / "cache"
    return Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP


def venv_python(root: Path, win: bool = IS_WINDOWS) -> Path:
    """The project's virtualenv interpreter (.venv/bin/python or .venv\\Scripts\\python.exe)."""
    return root / ".venv" / ("Scripts" if win else "bin") / ("python.exe" if win else "python")


def mono_font(win: bool = IS_WINDOWS) -> str:
    """A fixed-width font family that exists on the platform."""
    return "Consolas" if win else "monospace"


def prepare_console() -> None:
    """Make printing safe everywhere: UTF-8 with replacement on Windows consoles (cp1252 cannot
    show ✔ ✖ →), and a null stream when there is no console at all (a windowed .exe)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
