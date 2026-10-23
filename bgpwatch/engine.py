"""Polling loop, best-path selection and change detection.

Runs in a background thread and talks to the GUI (or the console runner)
only through a queue.Queue of ("view", TargetView) / ("event", PathEvent) /
("status", str) messages, so Tkinter is never touched from the worker.
"""
from __future__ import annotations

import copy
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .collectors import Collector, CollectorError
from .models import PathEvent, Route, TargetView, fmt_path


@dataclass
class _State:
    view: TargetView
    confirmed: Optional[Route] = None      # current confirmed best route
    pending_path: Optional[tuple] = None
    pending_count: int = 0
    stable_polls: int = 0
    alt_paths: frozenset = field(default_factory=frozenset)
    polled: bool = False
    lost: bool = False
    violations: tuple = ()                 # path-rule violations already reported
    rpki_bad: bool = False                 # RPKI-invalid already reported


def most_specific_per_peer(routes: list) -> list:
    """If a peer has both 8.8.0.0/16 and 8.8.8.0/24, keep only the /24 -
    that is the route traffic actually follows."""
    best: dict = {}
    for r in routes:
        cur = best.get(r.vantage)
        if cur is None or r.prefix_len > cur.prefix_len:
            best[r.vantage] = r
    return sorted(best.values(), key=lambda r: (r.collector, r.peer_ip))


def select_best(routes: list, mode: str, vantage: str = "") -> tuple:
    """Return (best_route, label).

    mode 'peer'      -> the route seen by one chosen collector/peer
                        (what that router uses as its best path)
    mode 'consensus' -> the AS path used by the most peers; ties go to the
                        shorter path. A good "how the Internet reaches it" view.
    """
    if not routes:
        return None, "no routes"
    if mode == "peer" and vantage:
        for r in routes:
            if r.vantage.lower() == vantage.lower() or r.peer_ip == vantage:
                return r, f"peer {r.vantage} (AS{r.peer_asn})"
        return None, f"peer {vantage} not seen"
    counts: dict = {}
    first: dict = {}
    for r in routes:
        counts[r.as_path] = counts.get(r.as_path, 0) + 1
        first.setdefault(r.as_path, r)
    path = sorted(counts, key=lambda p: (-counts[p], len(p), p))[0]
    return first[path], f"consensus ({counts[path]}/{len(routes)} peers)"


class Monitor:
    def __init__(self, collector: Collector, out: queue.Queue, names=None,
                 interval: int = 60, confirm: int = 1, mode: str = "consensus",
                 vantage: str = "", auto_ack: int = 0, pause_between: float = 1.0,
                 rpki=None):
        self.collector = collector
        self.out = out
        self.names = names
        self.interval = max(5, int(interval))
        self.confirm = max(1, int(confirm))
        self.mode = mode
        self.vantage = vantage
        self.rpki = rpki                      # RpkiChecker or None (RPKI validation off)
        self.auto_ack = auto_ack              # clear red after N stable polls (0 = never)
        self.pause_between = pause_between    # be polite to the public API
        self._targets: dict = {}
        self.rules: dict = {}                 # target -> Rules (expected-path rules)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False

    # ---------------- target management (safe to call from the GUI) -------
    def add_target(self, target: str) -> bool:
        with self._lock:
            if target in self._targets:
                return False
            self._targets[target] = _State(TargetView(target=target))
        self._emit_view(target)
        return True

    def remove_target(self, target: str):
        with self._lock:
            self._targets.pop(target, None)

    def set_rules(self, target: str, rules) -> None:
        """Set (or clear, with None/empty) the expected-path rules of a target."""
        with self._lock:
            if rules is None or rules.is_empty():
                self.rules.pop(target, None)
            else:
                self.rules[target] = rules
        self.check_now()

    def targets(self) -> list:
        with self._lock:
            return list(self._targets)

    def acknowledge(self, target: str):
        with self._lock:
            st = self._targets.get(target)
            if st:
                st.view.changed = False
                if st.view.status == "changed":
                    st.view.status = "ok"
        self._emit_view(target)

    def set_options(self, interval=None, mode=None, vantage=None, confirm=None):
        if interval is not None:
            self.interval = max(5, int(interval))
        if confirm is not None:
            self.confirm = max(1, int(confirm))
        reselect = False
        if mode is not None and mode != self.mode:
            self.mode, reselect = mode, True
        if vantage is not None and vantage != self.vantage:
            self.vantage, reselect = vantage, True
        if reselect:
            # new definition of "best": start fresh, do not report a fake change
            with self._lock:
                for st in self._targets.values():
                    st.confirmed = None
                    st.pending_path, st.pending_count = None, 0
                    st.view.previous_path, st.view.changed = None, False
            self.check_now()

    # ---------------- thread control ---------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            self.running = True
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, name="bgp-monitor", daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def shutdown(self):
        self.running = False
        self._stop.set()
        self._wake.set()

    def check_now(self):
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            self._wake.clear()          # before polling: a wake-up that arrives mid-poll is kept
            if self.running:
                self.poll_all()
            # sleep in small steps so Stop / Check now react quickly
            deadline = time.monotonic() + self.interval
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self._wake.wait(0.5):
                    break
                if self.running:
                    remaining = int(deadline - time.monotonic())
                    self.out.put(("countdown", remaining))

    def poll_all(self):
        tgts = self.targets()
        for i, t in enumerate(tgts):
            if self._stop.is_set():
                return
            self.out.put(("status", f"Polling {t} ({i + 1}/{len(tgts)})…"))
            self.poll_target(t)
            if i + 1 < len(tgts):
                time.sleep(self.pause_between)
        self.out.put(("status", f"Last poll {datetime.now():%H:%M:%S} · "
                                f"{len(tgts)} target(s) · every {self.interval}s"))

    # ---------------- the actual work --------------------------------------
    def poll_target(self, target: str):
        now = datetime.now()
        try:
            routes = most_specific_per_peer(self.collector.fetch(target))
        except CollectorError as exc:
            with self._lock:
                st = self._targets.get(target)
                if not st:
                    return
                st.view.status, st.view.error, st.view.last_poll = "error", str(exc), now
            self.out.put(("event", PathEvent("FETCH_ERROR", target, st.view.prefix, "-",
                                             timestamp=now, detail=str(exc))))
            self._emit_view(target)
            return

        best, label = select_best(routes, self.mode, self.vantage)
        if self.rpki and best:
            self.rpki.check(best.origin_asn, best.prefix)      # network call, outside the lock
        events = []
        with self._lock:
            st = self._targets.get(target)
            if not st:
                return
            v = st.view
            v.routes, v.last_poll, v.error, v.best_label = routes, now, "", label
            v.prefix = best.prefix if best else (routes[0].prefix if routes else "")
            new_path = best.as_path if best else None
            vantage_name = best.vantage if (best and self.mode == "peer") else label

            if st.confirmed is None:
                if best:
                    st.confirmed = best
                    v.best, v.best_path = best, best.as_path
                    if not st.polled:
                        events.append(PathEvent("FIRST_SEEN", target, v.prefix, vantage_name,
                                                None, new_path, now))
                    elif st.lost:
                        events.append(PathEvent("BEST_RESTORED", target, v.prefix, vantage_name,
                                                v.previous_path, new_path, now,
                                                detail="route is back"))
                        v.changed, v.changed_at = True, now
                        st.lost = False
            elif new_path != st.confirmed.as_path:
                if new_path is None:
                    events.append(PathEvent("BEST_LOST", target, st.confirmed.prefix,
                                            vantage_name, st.confirmed.as_path, None, now,
                                            detail="no route from the selected vantage point "
                                                   "(withdrawn or peer down)"))
                    v.previous_path = st.confirmed.as_path
                    v.best, v.best_path = None, None
                    v.changed, v.changed_at = True, now
                    st.confirmed = None
                    st.lost = True
                    st.pending_path, st.pending_count = None, 0
                else:
                    if st.pending_path == new_path:
                        st.pending_count += 1
                    else:
                        st.pending_path, st.pending_count = new_path, 1
                    if st.pending_count >= self.confirm:
                        old = st.confirmed
                        kind = "BEST_CHANGED"
                        notes = []
                        if old.origin_asn != best.origin_asn:
                            kind = "ORIGIN_CHANGED"
                            notes.append(f"origin AS changed AS{old.origin_asn} -> "
                                         f"AS{best.origin_asn} - check for a hijack or "
                                         f"misorigination")
                        if old.prefix != best.prefix:
                            notes.append(f"prefix changed {old.prefix} -> {best.prefix}")
                        events.append(PathEvent(kind, target, best.prefix, vantage_name,
                                                old.as_path, best.as_path, now,
                                                detail="; ".join(notes)))
                        v.previous_path = old.as_path
                        st.confirmed = best
                        v.best, v.best_path = best, best.as_path
                        v.changed, v.changed_at = True, now
                        st.stable_polls = 0
                        st.pending_path, st.pending_count = None, 0
            else:
                st.pending_path, st.pending_count = None, 0
                v.best, v.best_path = best, best.as_path
                st.confirmed = best
                if v.changed:
                    st.stable_polls += 1
                    if self.auto_ack and st.stable_polls >= self.auto_ack:
                        v.changed = False

            # expected-path rules, checked against the confirmed best path
            if v.best_path is not None:
                rules = self.rules.get(target)
                viol = tuple(rules.check(v.best_path)) if rules else ()
                if viol != st.violations:
                    if viol:
                        events.append(PathEvent("RULE_VIOLATION", target, v.prefix, vantage_name,
                                                None, v.best_path, now, detail="; ".join(viol)))
                    else:
                        events.append(PathEvent("RULE_RESTORED", target, v.prefix, vantage_name,
                                                None, v.best_path, now,
                                                detail="path complies with the rules again"))
                    st.violations = viol
                v.violations = list(viol)

            # RPKI origin validation of the confirmed best path
            res = None
            if self.rpki and v.best is not None:
                res = self.rpki.cached(v.best.origin_asn, v.best.prefix)
            v.rpki, v.rpki_detail = (res.status, res.detail) if res else ("", "")
            if not self.rpki:
                st.rpki_bad = False                  # switched off: drop the RPKI flag silently
            if res and res.status != "error":
                if res.invalid and not st.rpki_bad:
                    events.append(PathEvent("RPKI_INVALID", target, v.prefix, vantage_name,
                                            None, v.best_path, now,
                                            detail=f"{res.label}: {res.detail}"))
                elif not res.invalid and st.rpki_bad:
                    events.append(PathEvent("RPKI_RESTORED", target, v.prefix, vantage_name,
                                            None, v.best_path, now,
                                            detail=f"{res.label}: {res.detail}"))
                st.rpki_bad = res.invalid

            # alternate (non-best) path churn - informational
            alts = frozenset(p for p in (r.as_path for r in routes) if p != new_path)
            if st.polled:
                added, gone = alts - st.alt_paths, st.alt_paths - alts
                if added or gone:
                    detail = f"{len(added)} alternate path(s) added, {len(gone)} withdrawn"
                    sample = [f"+ {fmt_path(p)}" for p in list(added)[:3]] + \
                             [f"- {fmt_path(p)}" for p in list(gone)[:3]]
                    if sample:
                        detail += "\n    " + "\n    ".join(sample)
                    events.append(PathEvent("ALT_CHANGED", target, v.prefix, label,
                                            timestamp=now, detail=detail))
            st.alt_paths = alts
            st.polled = True
            if not routes:
                v.status, v.error = "error", "no routes returned (prefix not in the global table?)"
            elif st.rpki_bad:
                v.status = "rpki"
            elif v.violations:
                v.status = "violation"
            elif v.changed:
                v.status = "changed"
            elif st.pending_path is not None:
                v.status = "pending"
            else:
                v.status = "ok"

        snap = v.unique_paths()[:40]
        for ev in events:
            if ev.kind not in ("ALT_CHANGED", "FETCH_ERROR"):
                ev.snapshot = snap
            self.out.put(("event", ev))
        if self.names is not None:
            asns = []
            for path, _ in v.unique_paths()[:40]:
                asns.extend(path)
            self.names.resolve(asns)
        self._emit_view(target)

    def _emit_view(self, target: str):
        with self._lock:
            st = self._targets.get(target)
            if st:
                self.out.put(("view", copy.copy(st.view)))
