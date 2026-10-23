import json
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch.collectors import Collector  # noqa: E402
from bgpwatch.engine import Monitor  # noqa: E402
from bgpwatch.live import LiveCollector, _Table, collector_name, parse_path, subscription  # noqa: E402
from bgpwatch.models import Route  # noqa: E402


def upd(path, prefixes=(), withdrawals=(), peer="1.1.1.1", host="rrc01.ripe.net"):
    return {"type": "UPDATE", "host": host, "peer": peer, "path": path,
            "announcements": [{"next_hop": peer, "prefixes": list(prefixes)}] if prefixes else [],
            "withdrawals": list(withdrawals)}


class TableTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(parse_path([3320, 6453, [64512, 64513], 15169]), (3320, 6453, 64512, 15169))
        self.assertEqual(collector_name("rrc01.ripe.net"), "RRC01")
        self.assertEqual(subscription("8.8.8.8"), {"type": "UPDATE", "prefix": "8.8.8.8/32",
                         "lessSpecific": True, "socketOptions": {"includeRaw": False}})

    def test_apply_announce_and_withdraw(self):
        t = _Table("8.8.8.8")
        self.assertTrue(t.apply(upd([1, 2, 15169], ["8.8.8.0/24", "9.9.9.0/24"])))   # only /24 covers
        self.assertEqual([r.prefix for r in t.routes.values()], ["8.8.8.0/24"])
        self.assertFalse(t.apply(upd([1, 2, 15169], ["8.8.8.0/24"])))               # unchanged
        self.assertTrue(t.apply(upd([1, 3, 15169], ["8.8.8.0/24"])))                # path changed
        self.assertEqual(next(iter(t.routes.values())).as_path, (1, 3, 15169))
        self.assertTrue(t.apply(upd([], withdrawals=["8.8.8.0/24"])))
        self.assertEqual(t.routes, {})

    def test_prefix_target_and_unrelated(self):
        t = _Table("8.8.8.0/24")
        t.apply(upd([1, 15169], ["8.8.0.0/16", "8.8.8.0/24", "8.8.8.128/25"]))
        self.assertEqual(sorted(r.prefix for r in t.routes.values()), ["8.8.0.0/16", "8.8.8.0/24"])

    def test_seed_does_not_overwrite_live(self):
        t = _Table("8.8.8.8")
        t.apply(upd([1, 9, 15169], ["8.8.8.0/24"]))
        t.seed([Route("8.8.8.8", "8.8.8.0/24", "RRC01", "1.1.1.1", (1, 2, 15169)),
                Route("8.8.8.8", "8.8.8.0/24", "RRC01", "2.2.2.2", (2, 15169))])
        got = {k[1]: r.as_path for k, r in t.routes.items()}
        self.assertEqual(got, {"1.1.1.1": (1, 9, 15169), "2.2.2.2": (2, 15169)})

    def test_seed_does_not_resurrect_withdrawn(self):
        t = _Table("8.8.8.8")
        t.apply(upd([], withdrawals=["8.8.8.0/24"]))
        t.seed([Route("8.8.8.8", "8.8.8.0/24", "RRC01", "1.1.1.1", (1, 15169))])
        self.assertEqual(t.routes, {})


class Seed(Collector):
    name = "seed"

    def fetch(self, target):
        return [Route(target, "8.8.8.0/24", "RRC01", f"10.0.0.{i}", (3333, 3257, 15169))
                for i in range(5)]


class LiveEngineTests(unittest.TestCase):
    def test_stream_update_triggers_best_path_change(self):
        woke = []
        live = LiveCollector(Seed(), on_update=woke.append, min_wake=0.05)
        # no real network: replace the stream thread with direct message injection
        live._run = lambda tbl: None
        q = queue.Queue()
        m = Monitor(live, q, pause_between=0)
        m.add_target("8.8.8.8")
        m.poll_target("8.8.8.8")
        tbl = live._tables["8.8.8.8"]
        for i in range(5):                                   # all 5 peers move to the new path
            live._handle(tbl, json.dumps({"type": "ris_message", "data": upd(
                [3333, 6762, 15169], ["8.8.8.0/24"], peer=f"10.0.0.{i}", host="rrc01.ripe.net")}).encode())
        time.sleep(0.2)
        self.assertTrue(woke)                                # the monitor would be woken
        m.poll_target("8.8.8.8")
        kinds = []
        while not q.empty():
            k, p = q.get_nowait()
            if k == "event":
                kinds.append(p.kind)
        self.assertEqual(kinds, ["FIRST_SEEN", "BEST_CHANGED"])

    def test_wake_is_rate_limited_with_trailing_call(self):
        calls = []
        live = LiveCollector(Seed(), on_update=calls.append, min_wake=0.2)
        for _ in range(10):
            live._wake("t")
        time.sleep(0.5)
        self.assertEqual(len(calls), 2)                      # immediate + one trailing


if __name__ == "__main__":
    unittest.main()
