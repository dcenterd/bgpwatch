"""Expected-path rules: what the best path of a target is allowed to look like."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def parse_asns(text: str) -> tuple:
    """'AS3356, 1299 174' -> (3356, 1299, 174); anything that is not a number is ignored."""
    return tuple(int(m) for m in re.findall(r"\d+", str(text)))


@dataclass(frozen=True)
class Rules:
    origin: int | None = None         # the origin AS must be this one
    via: tuple = ()                   # the path must pass through ALL of these ASes
    avoid: tuple = ()                 # the path must not contain ANY of these ASes
    max_len: int = 0                  # 0 = no limit (prepending collapsed)

    def is_empty(self) -> bool:
        return self.origin is None and not self.via and not self.avoid and not self.max_len

    def check(self, path) -> list:
        """Human-readable violations of this rule set by an AS path (empty list = ok)."""
        if not path or self.is_empty():
            return []
        hops = [a for i, a in enumerate(path) if i == 0 or a != path[i - 1]]
        out = []
        if self.origin is not None and hops[-1] != self.origin:
            out.append(f"origin is AS{hops[-1]}, expected AS{self.origin}")
        missing = [a for a in self.via if a not in hops]
        if missing:
            out.append("path does not pass through " + ", ".join(f"AS{a}" for a in missing))
        bad = [a for a in self.avoid if a in hops]
        if bad:
            out.append("path contains forbidden " + ", ".join(f"AS{a}" for a in bad))
        if self.max_len and len(hops) > self.max_len:
            out.append(f"path has {len(hops)} ASes, limit is {self.max_len}")
        return out

    def describe(self) -> str:
        parts = []
        if self.origin is not None:
            parts.append(f"origin=AS{self.origin}")
        if self.via:
            parts.append("via=" + ",".join(f"AS{a}" for a in self.via))
        if self.avoid:
            parts.append("avoid=" + ",".join(f"AS{a}" for a in self.avoid))
        if self.max_len:
            parts.append(f"max_len={self.max_len}")
        return " ".join(parts) or "no rules"

    def to_dict(self) -> dict:
        return {"origin": self.origin, "via": list(self.via), "avoid": list(self.avoid),
                "max_len": self.max_len}

    @classmethod
    def from_dict(cls, d: dict) -> "Rules":
        try:
            origin = d.get("origin")
            return cls(int(origin) if origin else None,
                       tuple(int(a) for a in d.get("via", ())),
                       tuple(int(a) for a in d.get("avoid", ())),
                       int(d.get("max_len") or 0))
        except (TypeError, ValueError, AttributeError):
            return cls()
