"""Data model shared by collectors, the engine and the GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

ASPath = tuple  # tuple[int, ...]


def parse_as_path(text: str) -> ASPath:
    """Parse '3333 1299 {64512,64513} 15169' into (3333, 1299, 64512, 15169).

    AS_SETs (in braces) are reduced to their first member so the path
    stays a simple chain that can be drawn.
    """
    out = []
    for tok in str(text).split():
        tok = tok.strip("{}()[]")
        if "," in tok:
            tok = tok.split(",")[0]
        if tok.isdigit():
            out.append(int(tok))
    return tuple(out)


def collapse_prepends(path: ASPath) -> ASPath:
    """Remove AS-path prepending: (6424, 6424, 1299, 15169) -> (6424, 1299, 15169)."""
    out = []
    for asn in path:
        if not out or out[-1] != asn:
            out.append(asn)
    return tuple(out)


def fmt_path(path: Optional[ASPath]) -> str:
    return " ".join(str(a) for a in path) if path else "(none)"


@dataclass(frozen=True)
class Route:
    """One route as seen by one vantage point (collector + peer)."""
    target: str
    prefix: str
    collector: str
    peer_ip: str
    as_path: ASPath
    next_hop: str = ""
    peer_location: str = ""

    @property
    def peer_asn(self) -> Optional[int]:
        return self.as_path[0] if self.as_path else None

    @property
    def origin_asn(self) -> Optional[int]:
        return self.as_path[-1] if self.as_path else None

    @property
    def vantage(self) -> str:
        return f"{self.collector}/{self.peer_ip}"

    @property
    def prefix_len(self) -> int:
        try:
            return int(self.prefix.split("/")[1])
        except (IndexError, ValueError):
            return 0


@dataclass
class PathEvent:
    """Something that changed for a target."""
    kind: str                 # BEST_CHANGED | ORIGIN_CHANGED | PREFIX_CHANGED | ALT_CHANGED
                              # | BEST_LOST | FIRST_SEEN | FETCH_ERROR
                              # | RULE_VIOLATION | RULE_RESTORED | RPKI_INVALID | RPKI_RESTORED
    target: str
    prefix: str
    vantage: str
    old_path: Optional[ASPath] = None
    new_path: Optional[ASPath] = None
    timestamp: datetime = field(default_factory=datetime.now)
    detail: str = ""
    snapshot: list = field(default_factory=list)   # [(as_path, peer_count)] when it happened

    @property
    def severity(self) -> str:
        if self.kind in ("BEST_CHANGED", "ORIGIN_CHANGED", "PREFIX_CHANGED", "BEST_LOST",
                         "BEST_RESTORED", "RULE_VIOLATION", "RPKI_INVALID"):
            return "alert"
        if self.kind == "FETCH_ERROR":
            return "error"
        return "info"

    def changed_hops(self) -> str:
        old = set(self.old_path or ())
        new = set(self.new_path or ())
        removed = [a for a in (self.old_path or ()) if a not in new]
        added = [a for a in (self.new_path or ()) if a not in old]
        if not removed and not added:
            return "same ASes, different order or prepending"
        left = ", ".join(f"AS{a}" for a in removed) or "-"
        right = ", ".join(f"AS{a}" for a in added) or "-"
        return f"{left} -> {right}"

    def summary(self) -> str:
        """One line for the GUI event list."""
        t = self.timestamp.strftime("%H:%M:%S")
        if self.kind in ("BEST_CHANGED", "ORIGIN_CHANGED", "BEST_RESTORED", "BEST_LOST"):
            return (f"{t}  {self.kind.replace('_', ' ')}  {self.target} ({self.prefix}): "
                    f"{fmt_path(self.old_path)}  ->  {fmt_path(self.new_path)}")
        if self.kind == "FIRST_SEEN":
            return f"{t}  {self.target} ({self.prefix}) best path {fmt_path(self.new_path)}"
        if self.kind in ("RULE_VIOLATION", "RULE_RESTORED", "RPKI_INVALID", "RPKI_RESTORED"):
            return (f"{t}  {self.kind.replace('_', ' ')}  {self.target}: {self.detail}"
                    f"  [{fmt_path(self.new_path)}]")
        return f"{t}  {self.kind.replace('_', ' ')}  {self.target}: {self.detail}"

    def console_block(self) -> str:
        """Multi-line block for the console / log file."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        head = f"{ts} [{self.kind.replace('_', '-')}] {self.target} ({self.prefix}) @ {self.vantage}"
        if self.kind in ("BEST_CHANGED", "ORIGIN_CHANGED", "PREFIX_CHANGED",
                         "BEST_RESTORED", "BEST_LOST"):
            o = self.old_path[-1] if self.old_path else None
            n = self.new_path[-1] if self.new_path else None
            lines = [
                head,
                f"    PREVIOUS : {fmt_path(self.old_path):<40} (origin AS{o})",
                f"    NEW      : {fmt_path(self.new_path):<40} (origin AS{n})",
                f"    Changed  : {self.changed_hops()}",
            ]
            if self.detail:
                lines.append(f"    Note     : {self.detail}")
            return "\n".join(lines)
        if self.kind == "FIRST_SEEN":
            return f"{head}\n    BEST     : {fmt_path(self.new_path)}"
        if self.kind in ("RULE_VIOLATION", "RULE_RESTORED"):
            return f"{head}\n    PATH     : {fmt_path(self.new_path)}\n    RULE     : {self.detail}"
        if self.kind in ("RPKI_INVALID", "RPKI_RESTORED"):
            return f"{head}\n    PATH     : {fmt_path(self.new_path)}\n    RPKI     : {self.detail}"
        return f"{head}\n    {self.detail}"


@dataclass
class TargetView:
    """Immutable-ish snapshot the engine hands to the GUI for drawing."""
    target: str
    status: str = "pending"          # pending | ok | changed | error
    prefix: str = ""
    routes: list = field(default_factory=list)
    best: Optional[Route] = None
    best_path: Optional[ASPath] = None
    previous_path: Optional[ASPath] = None
    changed: bool = False
    changed_at: Optional[datetime] = None
    last_poll: Optional[datetime] = None
    error: str = ""
    best_label: str = ""             # e.g. "consensus (41/398 peers)" or "rrc00/193.0.0.56"
    violations: list = field(default_factory=list)   # broken path rules (strings)
    rpki: str = ""                   # valid | invalid_asn | invalid_length | unknown | error | "" (off)
    rpki_detail: str = ""

    def unique_paths(self) -> list:
        """[(path, count)] most common first."""
        counts: dict = {}
        for r in self.routes:
            counts[r.as_path] = counts.get(r.as_path, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))
