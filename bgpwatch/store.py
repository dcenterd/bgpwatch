"""Persistence: change history (SQLite) and user settings (JSON)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import PathEvent

SKIP_KINDS = {"ALT_CHANGED", "FETCH_ERROR"}      # too noisy for the timeline


class History:
    """Every path change, with a snapshot of the paths seen at that moment so the
    map can be redrawn later."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, target TEXT,
            prefix TEXT, vantage TEXT, old_path TEXT, new_path TEXT, detail TEXT,
            snapshot TEXT)""")
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_target_ts ON events(target, ts)")
        self._db.commit()

    def add(self, ev: PathEvent):
        if ev.kind in SKIP_KINDS:
            return
        row = (ev.timestamp.isoformat(timespec="seconds"), ev.kind, ev.target, ev.prefix,
               ev.vantage, json.dumps(list(ev.old_path) if ev.old_path else None),
               json.dumps(list(ev.new_path) if ev.new_path else None), ev.detail,
               json.dumps([[list(p), n] for p, n in ev.snapshot]))
        try:
            with self._lock:
                self._db.execute("INSERT INTO events (ts, kind, target, prefix, vantage, old_path,"
                                 " new_path, detail, snapshot) VALUES (?,?,?,?,?,?,?,?,?)", row)
                self._db.commit()
        except sqlite3.Error:
            pass

    def query(self, target: Optional[str] = None, limit: int = 1000) -> list:
        """Newest first. Each row is a dict with a PathEvent under 'event'."""
        sql, args = "SELECT id, ts, kind, target, prefix, vantage, old_path, new_path, detail, " \
                    "snapshot FROM events", []
        if target:
            sql += " WHERE target = ?"
            args.append(target)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        try:
            with self._lock:
                rows = self._db.execute(sql, args).fetchall()
        except sqlite3.Error:
            return []
        out = []
        for id_, ts, kind, tgt, prefix, vantage, old, new, detail, snap in rows:
            old, new = json.loads(old), json.loads(new)
            out.append(PathEvent(kind, tgt, prefix, vantage,
                                 tuple(old) if old else None, tuple(new) if new else None,
                                 datetime.fromisoformat(ts), detail,
                                 [(tuple(p), n) for p, n in json.loads(snap or "[]")]))
        return out

    def clear(self, target: Optional[str] = None):
        with self._lock:
            if target:
                self._db.execute("DELETE FROM events WHERE target = ?", (target,))
            else:
                self._db.execute("DELETE FROM events")
            self._db.commit()


class Settings:
    """targets, per-target rules / mute, theme - saved as JSON next to the logs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"targets": [], "rules": {}, "muted": [], "mute_all": False, "dark": False}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except OSError:
            pass
