"""Run with:  python3 -m unittest discover -s tests   (no network needed)"""
import queue
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bgpwatch import collectors  # noqa: E402
from bgpwatch.collectors import Collector, RipeStatCollector  # noqa: E402
from bgpwatch.engine import Monitor, select_best  # noqa: E402
from bgpwatch.layout import build_graph, to_svg  # noqa: E402
from bgpwatch.models import Route, collapse_prepends, parse_as_path  # noqa: E402
from bgpwatch.targets import parse_targets  # noqa: E402

SAMPLE = {"status": "ok", "data": {"rrcs": [
    {"rrc": "RRC00", "peers": [
        {"as_path": "3333 1257 15169", "prefix": "8.8.8.0/24", "peer": "193.0.0.56",
         "next_hop": "193.0.0.56", "peer_location": "Amsterdam, NL"},
        {"as_path": "20514 1299 15169", "prefix": "8.8.8.0/24", "peer": "217.151.205.147"},
        {"as_path": "20514 1299 15169", "prefix": "8.8.0.0/16", "peer": "217.151.205.147"},
    ]},
    {"rrc": "RRC01", "peers": [
        {"as_path": "6424 6424 1299 15169", "prefix": "8.8.8.0/24", "peer": "195.66.225.212"},
        {"as_path": "1299 15169", "prefix": "8.8.8.0/24", "peer": "195.66.227.163"},
    ]}]}}


class Scripted(Collector):
    """Returns a scripted list of {vantage: path} per poll."""
    name = "scripted"

    def __init__(self, script):
        self.script, self.i = script, 0

    def fetch(self, target):
        step = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return [Route(target, "8.8.8.0/24", v.split("/")[0], v.split("/")[1], tuple(p))
                for v, p in step.items()]


def run(script, polls, **kw):
    q = queue.Queue()
    m = Monitor(Scripted(script), q, None, **kw)
    m.add_target("8.8.8.8")
    for _ in range(polls):
        m.poll_target("8.8.8.8")
    events, view = [], None
    while not q.empty():
        k, p = q.get()
        if k == "event":
            events.append(p)
        if k == "view":
            view = p
    return events, view


class Tests(unittest.TestCase):
    def test_parse_path(self):
        self.assertEqual(parse_as_path("3333 {64512,64513} 15169"), (3333, 64512, 15169))
        self.assertEqual(collapse_prepends((6424, 6424, 1299, 15169)), (6424, 1299, 15169))

    def test_targets(self):
        good, bad = parse_targets("8.8.8.8, 1.1.1.0/24 2001:4860:4860::8888 nope")
        self.assertEqual(good, ["8.8.8.8", "1.1.1.0/24", "2001:4860:4860::8888"])
        self.assertEqual(bad, ["nope"])

    def test_ripestat_parse_and_most_specific(self):
        with mock.patch.object(collectors, "http_get_json", return_value=SAMPLE):
            routes = RipeStatCollector().fetch("8.8.8.8")
        self.assertEqual(len(routes), 5)
        q = queue.Queue()
        with mock.patch.object(collectors, "http_get_json", return_value=SAMPLE):
            m = Monitor(RipeStatCollector(), q, None)
            m.add_target("8.8.8.8")
            m.poll_target("8.8.8.8")
        views = [p for k, p in list(q.queue) if k == "view"]
        v = views[-1]
        self.assertEqual(len(v.routes), 4)                     # /16 dropped for that peer
        self.assertEqual(v.prefix, "8.8.8.0/24")
        self.assertEqual(v.routes[0].peer_location, "Amsterdam, NL")

    def test_consensus_and_peer_mode(self):
        rs = [Route("t", "p/24", "RRC00", "a", (1, 2, 9)), Route("t", "p/24", "RRC00", "b", (3, 2, 9)),
              Route("t", "p/24", "RRC01", "c", (3, 2, 9))]
        best, label = select_best(rs, "consensus")
        self.assertEqual(best.as_path, (3, 2, 9))
        self.assertIn("2/3", label)
        best, _ = select_best(rs, "peer", "RRC00/a")
        self.assertEqual(best.as_path, (1, 2, 9))

    def test_change_detected_with_previous(self):
        a = {"RRC00/x": [3333, 1299, 15169], "RRC00/y": [3333, 1299, 15169]}
        b = {"RRC00/x": [3333, 174, 15169], "RRC00/y": [3333, 174, 15169]}
        ev, v = run([a, a, b], 3)
        kinds = [e.kind for e in ev]
        self.assertEqual(kinds[0], "FIRST_SEEN")
        ch = [e for e in ev if e.kind == "BEST_CHANGED"][0]
        self.assertEqual(ch.old_path, (3333, 1299, 15169))
        self.assertEqual(ch.new_path, (3333, 174, 15169))
        self.assertIn("AS1299 -> AS174", ch.console_block())
        self.assertTrue(v.changed)
        self.assertEqual(v.status, "changed")
        self.assertEqual(v.previous_path, (3333, 1299, 15169))

    def test_flap_guard(self):
        a = {"R/x": [1, 2, 9]}
        b = {"R/x": [1, 3, 9]}
        ev, _ = run([a, b, a], 3, confirm=2)                 # one-poll blip -> no alert
        self.assertFalse([e for e in ev if e.kind == "BEST_CHANGED"])
        ev, _ = run([a, b, b], 3, confirm=2)
        self.assertEqual(len([e for e in ev if e.kind == "BEST_CHANGED"]), 1)

    def test_origin_change(self):
        ev, _ = run([{"R/x": [1, 2, 15169]}, {"R/x": [1, 2, 64666]}], 2)
        oc = [e for e in ev if e.kind == "ORIGIN_CHANGED"]
        self.assertEqual(len(oc), 1)
        self.assertIn("hijack", oc[0].detail)

    def test_lost_and_restored_in_peer_mode(self):
        a = {"R/x": [1, 2, 9], "R/y": [5, 2, 9]}
        gone = {"R/y": [5, 2, 9]}
        ev, v = run([a, gone, a], 3, mode="peer", vantage="R/x")
        kinds = [e.kind for e in ev if e.kind != "ALT_CHANGED"]
        self.assertEqual(kinds, ["FIRST_SEEN", "BEST_LOST", "BEST_RESTORED"])

    def test_layout_and_svg(self):
        a = {"R/x": [3333, 1299, 15169], "R/y": [20514, 1299, 15169], "R/z": [6424, 6424, 174, 15169]}
        b = dict(a, **{"R/x": [3333, 174, 15169]})
        _, v = run([a, b], 2, mode="peer", vantage="R/x")
        g = build_graph(v, lambda a: "", 10)
        self.assertEqual(g.nodes["TGT"].col, 0)
        self.assertEqual(g.nodes["AS15169"].kind, "origin")
        self.assertEqual(g.edges[("AS3333", "AS174")].status, "changed")
        self.assertEqual(g.edges[("AS3333", "AS1299")].status, "previous")
        # every edge points left -> right
        for (x, y) in g.edges:
            self.assertGreater(g.nodes[x].col, g.nodes[y].col)
        self.assertIn("<svg", to_svg(g, "t"))


if __name__ == "__main__":
    unittest.main()
