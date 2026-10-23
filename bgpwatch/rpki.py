"""RPKI origin validation: is the origin AS allowed to announce this prefix?

A ROA (Route Origin Authorization) is a signed record "prefix P may be originated by AS X, up to
length L". RIPEstat's rpki-validation call checks (origin AS, prefix) against all published ROAs:

    valid           a ROA matches origin and length
    invalid_asn     ROAs cover the prefix but authorise another AS      -> likely hijack / mistake
    invalid_length  the origin is right but the prefix is more specific  -> likely hijack / leak
    unknown         no ROA covers the prefix (nothing can be said)
    error           the check itself failed (network, API)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .collectors import CollectorError, http_get_json

LABELS = {
    "valid": "✔ valid",
    "invalid_asn": "✖ INVALID (origin AS not authorised)",
    "invalid_length": "✖ INVALID (prefix too specific)",
    "unknown": "• not found (no ROA)",
    "error": "? check failed",
}


SHORT = {"valid": "✔ valid", "invalid_asn": "✖ INVALID", "invalid_length": "✖ INVALID",
         "unknown": "• no ROA", "error": "? failed"}        # compact form for the header line


@dataclass(frozen=True)
class RpkiResult:
    status: str            # valid | invalid_asn | invalid_length | unknown | error
    detail: str = ""

    @property
    def invalid(self) -> bool:
        return self.status.startswith("invalid")

    @property
    def label(self) -> str:
        return LABELS.get(self.status, self.status)


def describe(status: str, origin: int, prefix: str, roas: list) -> str:
    """One sentence explaining the verdict, built from the ROAs that cover the prefix."""
    auth = sorted({f"AS{r.get('origin')}" for r in roas if r.get("origin")})
    who = ", ".join(auth) or "-"
    if status == "valid":
        r = next((r for r in roas if r.get("validity") == "valid"), roas[0] if roas else {})
        return f"ROA authorises AS{origin} for {r.get('prefix', prefix)} up to /{r.get('max_length', '?')}"
    if status == "invalid_asn":
        return f"AS{origin} is not authorised for {prefix}; the ROA(s) authorise {who}"
    if status == "invalid_length":
        longest = max((int(r.get("max_length") or 0) for r in roas), default=0)
        plen = prefix.split("/")[-1]
        return f"{prefix} is longer than the ROA maximum /{longest} (authorised: {who}); announced /{plen}"
    if status == "unknown":
        return "no ROA covers this prefix, so its origin cannot be verified"
    return ""


class RpkiChecker:
    """Cached RPKI lookups through RIPEstat. Blocking: call it from the worker thread."""
    URL = "https://stat.ripe.net/data/rpki-validation/data.json"

    def __init__(self, ttl: int = 900, timeout: int = 10):
        self.ttl, self.timeout = ttl, timeout
        self._lock = threading.Lock()
        self._cache: dict = {}            # (asn, prefix) -> (monotonic time, RpkiResult)

    # -- overridable -------------------------------------------------------
    def _lookup(self, asn: int, prefix: str) -> RpkiResult:
        try:
            data = http_get_json(self.URL, {"resource": f"AS{asn}", "prefix": prefix,
                                            "sourceapp": "bgpwatch"}, self.timeout)
        except CollectorError as exc:
            return RpkiResult("error", str(exc))
        d = data.get("data") or {}
        status = d.get("status") or "error"
        if status not in LABELS:
            return RpkiResult("error", f"unexpected RPKI status '{status}'")
        return RpkiResult(status, describe(status, asn, prefix, d.get("validating_roas") or []))

    # -- public ------------------------------------------------------------
    def check(self, asn: int, prefix: str) -> RpkiResult:
        key = (int(asn), prefix)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < (self.ttl if hit[1].status != "error" else 60):
            return hit[1]
        res = self._lookup(*key)
        with self._lock:
            self._cache[key] = (now, res)
        return res

    def cached(self, asn: int, prefix: str) -> RpkiResult | None:
        """Last result for this pair without any network access (None if never checked)."""
        with self._lock:
            hit = self._cache.get((int(asn), prefix))
        return hit[1] if hit else None


class DemoRpki(RpkiChecker):
    """Offline stand-in for --demo. The well-known demo origins are valid, 8.8.4.4 is shown as a
    hijack (wrong origin) so the alert can be seen, anything else has no ROA."""
    KNOWN = {15169, 13335, 19281}

    def _lookup(self, asn: int, prefix: str) -> RpkiResult:
        if prefix.startswith("8.8.4."):
            return RpkiResult("invalid_asn", describe("invalid_asn", asn, prefix, [{"origin": 64496}])
                              + "  [simulated]")
        if asn in self.KNOWN:
            return RpkiResult("valid", f"ROA authorises AS{asn} for {prefix} up to /24  [simulated]")
        return RpkiResult("unknown", describe("unknown", asn, prefix, []))
