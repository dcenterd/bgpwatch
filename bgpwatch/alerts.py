"""Console + rotating log file + JSON-lines event log + desktop notifications."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .models import PathEvent, fmt_path
from . import osutil
from .store import History

RESET, RED, GREEN, YELLOW, DIM = "\033[0m", "\033[91m", "\033[92m", "\033[93m", "\033[2m"


def default_log_dir() -> Path:
    return osutil.state_dir()


class Alerter:
    def __init__(self, log_dir: Path | None = None, notify: bool = True, color: bool | None = None):
        self.log_dir = Path(log_dir or default_log_dir())
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if color is None:                       # ANSI colours: not in the old Windows console
            color = sys.stdout.isatty() and (not osutil.IS_WINDOWS or bool(
                os.environ.get("WT_SESSION") or os.environ.get("TERM")))
        self.color = color
        self.notify_cmd = shutil.which("notify-send")      # None: not installed
        self.notify_enabled = notify                       # --no-notify / the GUI switch
        self.notifier = None                               # callable(title, body), e.g. the tray's balloon

        self.log = logging.getLogger("bgpwatch")
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        if not self.log.handlers:
            fh = logging.handlers.RotatingFileHandler(self.log_dir / "bgpwatch.log",
                                                      maxBytes=5_000_000, backupCount=5,
                                                      encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(message)s"))
            self.log.addHandler(fh)
        self.events_file = self.log_dir / "events.jsonl"
        self.history = History(self.log_dir / "history.db")
        self.muted: set = set()          # targets whose alerts make no sound / notification

    def _console(self, text: str, color: str = ""):
        if self.color and color:
            print(f"{color}{text}{RESET}", flush=True)
        else:
            print(text, flush=True)

    def handle(self, ev: PathEvent):
        block = ev.console_block()
        color = {"alert": RED, "error": YELLOW}.get(ev.severity, GREEN if ev.kind == "FIRST_SEEN" else DIM)
        self._console(block, color)
        self.log.info(block)
        self.history.add(ev)
        try:
            with self.events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "time": ev.timestamp.isoformat(timespec="seconds"),
                    "kind": ev.kind, "target": ev.target, "prefix": ev.prefix,
                    "vantage": ev.vantage,
                    "old_path": list(ev.old_path) if ev.old_path else None,
                    "new_path": list(ev.new_path) if ev.new_path else None,
                    "detail": ev.detail,
                }) + "\n")
        except OSError:
            pass
        if ev.severity == "alert" and ev.target not in self.muted:
            if ev.kind == "RPKI_INVALID":
                self.desktop(f"RPKI INVALID: {ev.target}", f"{ev.detail}\n{fmt_path(ev.new_path)}")
            elif ev.kind == "RULE_VIOLATION":
                self.desktop(f"BGP rule violated: {ev.target}",
                             f"{ev.detail}\n{fmt_path(ev.new_path)}")
            else:
                self.desktop(f"BGP path change: {ev.target}",
                             f"{fmt_path(ev.old_path)}\n→ {fmt_path(ev.new_path)}")

    @property
    def can_notify(self) -> bool:
        """Is there any way to show a desktop notification (notify-send, or the tray on Windows)?"""
        return bool(self.notifier or self.notify_cmd)

    def desktop(self, title: str, body: str):
        if not self.notify_enabled:
            return
        if self.notifier:
            try:
                self.notifier(title, body)
            except Exception:
                pass
            return
        if not self.notify_cmd:
            return
        try:
            subprocess.Popen([self.notify_cmd, "-u", "critical", "-a", "BGP LookingGlass",
                              title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
