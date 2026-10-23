"""Live feed: RIPE RIS Live (HTTP NDJSON stream) keeps an in-memory routing table per target.

Polling asks RIPEstat every N seconds. Here each target gets a long-lived stream of the BGP
UPDATE messages that touch it, so a path change is seen within seconds. The table is seeded
once from the polling collector (RIPEstat) and then kept current from the stream; the Monitor
reads it through LiveCollector.fetch() exactly like any other collector.
"""
from __future__ import annotations

import ipaddress
import json
import threading
import time
import urllib.request
from datetime import datetime
from typing import Callable, Optional

from .collectors import USER_AGENT, Collector, CollectorError
from .models import Route

STREAM_URL = "https://ris-live.ripe.net/v1/stream/?format=json&client=bgp-lookingglass"
READ_TIMEOUT = 120          # a quiet prefix sends nothing; reconnect after this long


def _network(target: str):
    return ipaddress.ip_network(target, strict=False)


def parse_path(raw) -> tuple:
    """RIS Live path: [3320, 6453, [64512, 64513], 15169] -> (3320, 6453, 64512, 15169)."""
    out = []
    for hop in raw or []:
        if isinstance(hop, list):
            hop = hop[0] if hop else None
        if isinstance(hop, int):
            out.append(hop)
    return tuple(out)


def collector_name(host: str) -> str:
    """'rrc01.ripe.net' -> 'RRC01' (same naming RIPEstat uses)."""
    return str(host).split(".")[0].upper()


def subscription(target: str) -> dict:
    """Filter that matches updates for the target and every prefix covering it."""
    net = _network(target)
    return {"type": "UPDATE", "prefix": str(net), "lessSpecific": True,
            "socketOptions": {"includeRaw": False}}


class _Table:
    """Routes for one target, keyed by (collector, peer, prefix)."""

    def __init__(self, target: str):
        self.target = target
        self.net = _network(target)
        self.routes: dict = {}
        self.touched: set = set()           # keys changed by the stream (a seed must not overwrite)
        self.seeded = False
        self.messages = 0
        self.last_update: Optional[datetime] = None
        self.state = "connecting"           # connecting | live | error: <why>
        self.stop = threading.Event()

    def covers(self, prefix: str) -> bool:
        try:
            return _network(prefix).supernet_of(self.net)
        except (ValueError, TypeError):
            return False

    def apply(self, data: dict) -> bool:
        """Apply one ris_message payload. True if the table changed."""
        if data.get("type") != "UPDATE":
            return False
        coll, peer = collector_name(data.get("host", "")), str(data.get("peer", ""))
        changed = False
        for pfx in data.get("withdrawals") or []:
            if self.covers(pfx):
                key = (coll, peer, pfx)
                self.touched.add(key)
                changed |= self.routes.pop(key, None) is not None
        path = parse_path(data.get("path"))
        if path:
            for ann in data.get("announcements") or []:
                for pfx in ann.get("prefixes") or []:
                    if not self.covers(pfx):
                        continue
                    key = (coll, peer, pfx)
                    self.touched.add(key)
                    new = Route(self.target, pfx, coll, peer, path, str(ann.get("next_hop", "")))
                    if self.routes.get(key) != new:
                        self.routes[key] = new
                        changed = True
        return changed

    def seed(self, routes: list):
        for r in routes:
            key = (r.collector, r.peer_ip, r.prefix)
            if key not in self.touched:
                self.routes.setdefault(key, r)
        self.seeded = True


class LiveCollector(Collector):
    name = "ris-live"

    def __init__(self, seed: Collector, on_update: Callable[[str], None] | None = None,
                 min_wake: float = 1.0):
        self.seed_source = seed
        self.on_update = on_update              # called (rate limited) with the target
        self.min_wake = min_wake
        self._tables: dict = {}
        self._lock = threading.Lock()
        self._last_wake: dict = {}
        self._pending: set = set()

    # ---------------- Collector API ----------------------------------------
    def fetch(self, target: str) -> list:
        tbl = self._start(target)
        if not tbl.seeded:
            try:
                routes = self.seed_source.fetch(target)
            except CollectorError:
                if not tbl.routes:
                    raise
                routes = []
            with self._lock:
                tbl.seed(routes)
        with self._lock:
            return list(tbl.routes.values())

    def status(self) -> str:
        """One line for the GUI."""
        with self._lock:
            tables = list(self._tables.values())
        if not tables:
            return "no targets"
        live = sum(1 for t in tables if t.state == "live")
        msgs = sum(t.messages for t in tables)
        last = max((t.last_update for t in tables if t.last_update), default=None)
        err = next((t.state for t in tables if t.state.startswith("error")), "")
        text = f"{live}/{len(tables)} streams live · {msgs} update(s)"
        if last:
            text += f" · last {last:%H:%M:%S}"
        return text + (f" · {err}" if err else "")

    def forget(self, target: str):
        with self._lock:
            tbl = self._tables.pop(target, None)
        if tbl:
            tbl.stop.set()

    def close(self):
        for t in list(self._tables):
            self.forget(t)

    # ---------------- stream thread ----------------------------------------
    def _start(self, target: str) -> _Table:
        with self._lock:
            tbl = self._tables.get(target)
            if tbl is None:
                tbl = self._tables[target] = _Table(target)
                threading.Thread(target=self._run, args=(tbl,), daemon=True,
                                 name=f"ris-live-{target}").start()
            return tbl

    def _run(self, tbl: _Table):
        backoff = 2
        while not tbl.stop.is_set():
            req = urllib.request.Request(STREAM_URL, headers={
                "User-Agent": USER_AGENT,
                "X-RIS-Subscribe": json.dumps(subscription(tbl.target))})
            try:
                with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as resp:
                    tbl.state, backoff = "live", 2
                    for line in resp:
                        if tbl.stop.is_set():
                            return
                        self._handle(tbl, line)
            except TimeoutError:
                continue                         # quiet prefix: just reconnect
            except Exception as exc:             # network, HTTP, ...
                tbl.state = f"error: {type(exc).__name__}"
                with self._lock:                 # we may have missed updates: re-seed
                    tbl.seeded = False
                    tbl.touched.clear()
                if tbl.stop.wait(backoff):
                    return
                backoff = min(backoff * 2, 60)
                continue
            tbl.state = "connecting"            # server closed the stream
            tbl.stop.wait(1)

    def _handle(self, tbl: _Table, line: bytes):
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if msg.get("type") == "ris_error":
            tbl.state = f"error: {msg.get('data', {}).get('message', 'ris_error')}"[:80]
            return
        if msg.get("type") != "ris_message":
            return
        with self._lock:
            changed = tbl.apply(msg.get("data") or {})
            if changed:
                tbl.messages += 1
                tbl.last_update = datetime.now()
        if changed and self.on_update:
            self._wake(tbl.target)

    def _wake(self, target: str):
        """Tell the monitor to re-check, at most once per min_wake seconds. A burst always ends
        with a trailing wake, so the last update of the burst is never left unprocessed."""
        with self._lock:
            now = time.monotonic()
            wait = self._last_wake.get(target, 0) + self.min_wake - now
            if wait <= 0:
                self._last_wake[target] = now
            elif target in self._pending:
                return
            else:
                self._pending.add(target)
                self._last_wake[target] = now + wait

        def fire():
            with self._lock:
                self._pending.discard(target)
            self.on_update(target)
        if wait <= 0:
            fire()
        else:
            threading.Timer(wait, fire).start()
