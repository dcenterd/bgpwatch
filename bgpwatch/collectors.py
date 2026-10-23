"""Route sources. Each collector returns a list of Route objects for a target."""
from __future__ import annotations

import ipaddress
import json
import random
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from .models import Route, parse_as_path

USER_AGENT = "bgpwatch/1.0 (+https://github.com/)"


class CollectorError(Exception):
    pass


def http_get_json(url: str, params: dict, timeout: float = 25) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT,
                                                "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # network, HTTP, JSON
        raise CollectorError(f"{type(exc).__name__}: {exc}") from exc


class Collector(ABC):
    name = "base"

    @abstractmethod
    def fetch(self, target: str) -> list:
        """Return a list of Route for the target IP or prefix."""


class RipeStatCollector(Collector):
    """RIPEstat looking-glass data call (RIPE RIS route collectors).

    Every RIS peer gives us the route *it* selected, so one target yields
    hundreds of routes from all over the world.
    """
    name = "ripestat"
    URL = "https://stat.ripe.net/data/looking-glass/data.json"

    def __init__(self, timeout: float = 25, collectors: list | None = None):
        self.timeout = timeout
        self.collectors = [c.upper() for c in collectors] if collectors else None

    def fetch(self, target: str) -> list:
        data = http_get_json(self.URL, {"resource": target, "sourceapp": "bgpwatch"},
                             self.timeout)
        if data.get("status") not in (None, "ok"):
            raise CollectorError(f"RIPEstat status {data.get('status')}: {data.get('messages')}")
        routes = []
        for rrc in (data.get("data") or {}).get("rrcs", []) or []:
            name = str(rrc.get("rrc", "?")).upper()
            if self.collectors and name not in self.collectors:
                continue
            for p in rrc.get("peers", []) or []:
                path = parse_as_path(p.get("as_path", ""))
                if not path:
                    continue
                routes.append(Route(
                    target=target,
                    prefix=str(p.get("prefix", "")),
                    collector=name,
                    peer_ip=str(p.get("peer", "")),
                    as_path=path,
                    next_hop=str(p.get("next_hop", "")),
                    peer_location=str(p.get("peer_location", "")),
                ))
        return routes


class DemoCollector(Collector):
    """Offline simulator: realistic-looking paths that change every few polls.

    Useful to see the map, the red change highlight and the console logging
    without waiting for a real BGP event.
    """
    name = "demo"
    ORIGINS = {"8.8.8.8": 15169, "8.8.4.4": 15169, "1.1.1.1": 13335,
               "1.0.0.1": 13335, "9.9.9.9": 19281}
    TRANSITS = [1299, 174, 3356, 2914, 6939, 6453, 3257, 6762, 3491]
    PEERS = [3333, 20514, 34927, 49544, 8218, 24482, 6461, 58057, 202365, 13030,
             25091, 47147, 3214, 50304]

    def __init__(self, change_every: int = 3):
        self.change_every = max(1, change_every)
        self.polls: dict = {}

    def fetch(self, target: str) -> list:
        n = self.polls.get(target, 0)
        self.polls[target] = n + 1
        try:
            ip = ipaddress.ip_network(target, strict=False)
            plen = 24 if ip.version == 4 else 48
            if ip.prefixlen <= plen:
                prefix = str(ip)
            else:
                prefix = str(ipaddress.ip_network(f"{ip.network_address}/{plen}", strict=False))
        except ValueError:
            prefix = target
        origin = self.ORIGINS.get(target.split("/")[0], 64500 + (sum(map(ord, target)) % 400))
        base = random.Random(target)
        epoch = n // self.change_every
        routes = []
        for i, peer in enumerate(self.PEERS):
            rng = random.Random(f"{target}-{peer}-{epoch if i < 4 else 0}")
            hops = [peer]
            if base.random() < 0.75 or i < 4:
                t = rng.choice(self.TRANSITS)
                if t != peer:
                    hops.append(t)
                if rng.random() < 0.3:
                    t2 = rng.choice(self.TRANSITS)
                    if t2 not in hops:
                        hops.append(t2)
            hops.append(origin)
            routes.append(Route(target, prefix, f"RRC{i % 4:02d}",
                                f"192.0.2.{10 + i}", tuple(hops)))
        # the first peers share one path so a clear "consensus" best exists
        lead_rng = random.Random(f"{target}-lead-{epoch}")
        lead_t = lead_rng.choice(self.TRANSITS)
        lead = (3333, lead_t, origin)
        for k in range(5):
            routes.append(Route(target, prefix, "RRC00", f"193.0.0.{56 + k}", lead))
        return routes
