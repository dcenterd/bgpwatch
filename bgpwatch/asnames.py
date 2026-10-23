"""AS number -> holder name, cached on disk (~/.cache/bgpwatch/asnames.json, %LOCALAPPDATA%\\bgpwatch\\cache on Windows)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import osutil
from .collectors import CollectorError, http_get_json

BUILTIN = {
    174: "COGENT - Cogent Communications", 701: "UUNET - Verizon Business",
    1299: "TWELVE99 - Arelion Sweden AB", 2914: "NTT-LTD-2914 - NTT America",
    3257: "GTT-BACKBONE - GTT Communications", 3333: "RIPE-NCC-AS - RIPE NCC",
    3356: "LEVEL3 - Lumen / Level 3", 3491: "BTN-ASN - PCCW Global",
    6453: "AS6453 - TATA Communications", 6461: "ZAYO-6461 - Zayo Bandwidth",
    6762: "SEABONE-NET - Telecom Italia Sparkle", 6939: "HURRICANE - Hurricane Electric",
    7018: "ATT-INTERNET4 - AT&T", 13335: "CLOUDFLARENET - Cloudflare",
    15169: "GOOGLE - Google LLC", 19281: "QUAD9-1 - Quad9",
}


def short_name(holder: str) -> str:
    """'GOOGLE - Google LLC' -> 'Google LLC' (fits under the node label)."""
    if not holder:
        return ""
    part = holder.split(" - ", 1)[-1].strip()
    return part if len(part) <= 22 else part[:21] + "…"


class ASNames:
    URL = "https://stat.ripe.net/data/as-overview/data.json"

    def __init__(self, cache_file: Path | None = None, online: bool = True):
        self.online = online
        self.cache_file = cache_file or osutil.cache_dir() / "asnames.json"
        self._lock = threading.Lock()
        self._names: dict = {str(k): v for k, v in BUILTIN.items()}
        self._failed: set = set()
        try:
            self._names.update(json.loads(self.cache_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def get(self, asn: int) -> str:
        with self._lock:
            return self._names.get(str(asn), "")

    def resolve(self, asns, limit: int = 25) -> bool:
        """Look up unknown ASNs (blocking; call from the worker thread)."""
        if not self.online:
            return False
        todo = [a for a in dict.fromkeys(asns)
                if str(a) not in self._names and a not in self._failed][:limit]
        changed = False
        for asn in todo:
            try:
                data = http_get_json(self.URL, {"resource": f"AS{asn}", "sourceapp": "bgpwatch"}, 10)
                holder = ((data.get("data") or {}).get("holder") or "").strip()
            except CollectorError:
                holder = ""
            with self._lock:
                if holder:
                    self._names[str(asn)] = holder
                    changed = True
                else:
                    self._failed.add(asn)
        if changed:
            self.save()
        return changed

    def save(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self.cache_file.write_text(json.dumps(self._names, indent=0, sort_keys=True),
                                           encoding="utf-8")
        except OSError:
            pass
