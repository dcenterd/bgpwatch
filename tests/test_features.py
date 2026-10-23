import queue
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch.collectors import Collector  # noqa: E402
from bgpwatch.engine import Monitor  # noqa: E402
from bgpwatch.models import PathEvent, Route  # noqa: E402
from bgpwatch.rules import Rules, parse_asns  # noqa: E402
from bgpwatch.store import History, Settings  # noqa: E402


class Fake(Collector):
    name = "fake"

    def __init__(self):
        self.path = (3333, 3257, 15169)

    def fetch(self, target):
        return [Route(target, "8.8.8.0/24", "rrc00", f"1.1.1.{i}", self.path) for i in range(5)]


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return [p for k, p in out if k == "event"]


class RuleTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_asns("AS3356, 1299 x 174"), (3356, 1299, 174))

    def test_checks(self):
        r = Rules(origin=15169, via=(3257,), avoid=(174,), max_len=3)
        self.assertEqual(r.check((3333, 3257, 15169)), [])
        self.assertEqual(r.check((3333, 3333, 3257, 15169)), [])         # prepending ignored
        self.assertTrue(any("origin" in v for v in r.check((3333, 3257, 64500))))
        self.assertTrue(any("pass through AS3257" in v for v in r.check((3333, 1299, 15169))))
        self.assertTrue(any("forbidden AS174" in v for v in r.check((3333, 174, 3257, 15169))))
        self.assertTrue(any("limit" in v for v in r.check((1, 2, 3257, 15169))))
        self.assertEqual(Rules().check((1, 2)), [])

    def test_roundtrip(self):
        r = Rules(15169, (3257,), (174, 6939), 5)
        self.assertEqual(Rules.from_dict(r.to_dict()), r)


class EngineRuleTests(unittest.TestCase):
    def test_violation_then_restored(self):
        q, col = queue.Queue(), Fake()
        m = Monitor(col, q, pause_between=0)
        m.add_target("8.8.8.8")
        m.set_rules("8.8.8.8", Rules(avoid=(3257,)))
        m.poll_target("8.8.8.8")
        evs = drain(q)
        self.assertEqual([e.kind for e in evs], ["FIRST_SEEN", "RULE_VIOLATION"])
        self.assertEqual(evs[1].severity, "alert")
        self.assertTrue(evs[1].snapshot)
        m.poll_target("8.8.8.8")                       # still violated -> no repeat
        self.assertEqual([e.kind for e in drain(q)], [])
        col.path = (3333, 6939, 15169)
        m.poll_target("8.8.8.8")
        self.assertIn("RULE_RESTORED", [e.kind for e in drain(q)])

    def test_status_is_violation(self):
        q = queue.Queue()
        m = Monitor(Fake(), q, pause_between=0)
        m.add_target("8.8.8.8")
        m.set_rules("8.8.8.8", Rules(origin=64500))
        m.poll_target("8.8.8.8")
        views = []
        while not q.empty():
            k, p = q.get_nowait()
            if k == "view":
                views.append(p)
        self.assertEqual(views[-1].status, "violation")


class StoreTests(unittest.TestCase):
    def test_history_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(Path(d) / "h.db")
            h.add(PathEvent("BEST_CHANGED", "8.8.8.8", "8.8.8.0/24", "x", (1, 2), (1, 3),
                            datetime(2026, 1, 1, 10, 0, 0), "note",
                            [((1, 3), 4), ((1, 2), 1)]))
            h.add(PathEvent("ALT_CHANGED", "8.8.8.8", "8.8.8.0/24", "x"))   # not stored
            h.add(PathEvent("FIRST_SEEN", "1.1.1.1", "1.1.1.0/24", "x", None, (9,)))
            rows = h.query("8.8.8.8")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].old_path, (1, 2))
            self.assertEqual(rows[0].snapshot, [((1, 3), 4), ((1, 2), 1)])
            self.assertEqual(len(h.query()), 2)
            h.clear("8.8.8.8")
            self.assertEqual(len(h.query()), 1)
            h.close()                                  # Windows cannot delete an open database

    def test_settings(self):
        with tempfile.TemporaryDirectory() as d:
            s = Settings(Path(d) / "s.json")
            s.data["targets"] = ["8.8.8.8"]
            s.save()
            self.assertEqual(Settings(Path(d) / "s.json").data["targets"], ["8.8.8.8"])
            (Path(d) / "bad.json").write_text("{nope")
            self.assertEqual(Settings(Path(d) / "bad.json").data["targets"], [])


if __name__ == "__main__":
    unittest.main()
