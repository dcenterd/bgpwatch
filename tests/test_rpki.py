import queue
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch.collectors import Collector, CollectorError  # noqa: E402
from bgpwatch.engine import Monitor  # noqa: E402
from bgpwatch.models import Route  # noqa: E402
from bgpwatch.rpki import DemoRpki, RpkiChecker, RpkiResult  # noqa: E402


def api(status, roas):
    return {"data": {"status": status, "validating_roas": roas}}


ROA = {"origin": "15169", "prefix": "8.8.8.0/24", "validity": "valid", "max_length": 24}


class CheckerTests(unittest.TestCase):
    def check(self, response, asn=15169, prefix="8.8.8.0/24"):
        with mock.patch("bgpwatch.rpki.http_get_json", return_value=response):
            return RpkiChecker().check(asn, prefix)

    def test_valid(self):
        r = self.check(api("valid", [ROA]))
        self.assertEqual(r.status, "valid")
        self.assertFalse(r.invalid)
        self.assertIn("AS15169", r.detail)

    def test_invalid_origin(self):
        r = self.check(api("invalid_asn", [dict(ROA, validity="invalid_asn")]), asn=64500)
        self.assertEqual(r.status, "invalid_asn")
        self.assertTrue(r.invalid)
        self.assertIn("AS64500 is not authorised", r.detail)
        self.assertIn("AS15169", r.detail)

    def test_invalid_length(self):
        r = self.check(api("invalid_length", [dict(ROA, validity="invalid_length")]),
                       prefix="8.8.8.0/25")
        self.assertTrue(r.invalid)
        self.assertIn("/25", r.detail)
        self.assertIn("/24", r.detail)

    def test_unknown_is_not_invalid(self):
        r = self.check(api("unknown", []))
        self.assertEqual(r.status, "unknown")
        self.assertFalse(r.invalid)

    def test_network_error_and_odd_status(self):
        with mock.patch("bgpwatch.rpki.http_get_json", side_effect=CollectorError("boom")):
            self.assertEqual(RpkiChecker().check(1, "1.0.0.0/24").status, "error")
        self.assertEqual(self.check(api("weird", [])).status, "error")

    def test_results_are_cached(self):
        c = RpkiChecker()
        self.assertIsNone(c.cached(15169, "8.8.8.0/24"))
        with mock.patch("bgpwatch.rpki.http_get_json", return_value=api("valid", [ROA])) as get:
            c.check(15169, "8.8.8.0/24")
            c.check(15169, "8.8.8.0/24")
            self.assertEqual(get.call_count, 1)
        self.assertEqual(c.cached(15169, "8.8.8.0/24").status, "valid")

    def test_demo_checker_is_offline(self):
        d = DemoRpki()
        self.assertEqual(d.check(15169, "8.8.8.0/24").status, "valid")
        self.assertTrue(d.check(15169, "8.8.4.0/24").invalid)
        self.assertEqual(d.check(64999, "5.5.5.0/24").status, "unknown")


class Fixed(Collector):
    name = "fixed"

    def __init__(self):
        self.origin = 15169

    def fetch(self, target):
        return [Route(target, "8.8.8.0/24", "RRC00", "1.1.1.1", (3333, 1299, self.origin))]


class ScriptedRpki(RpkiChecker):
    def __init__(self):
        super().__init__()
        self.answer = RpkiResult("valid", "ok")

    def _lookup(self, asn, prefix):
        return self.answer


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.q, self.col, self.rpki = queue.Queue(), Fixed(), ScriptedRpki()
        self.m = Monitor(self.col, self.q, None, rpki=self.rpki)
        self.m.add_target("8.8.8.8")

    def poll(self):
        self.rpki._cache.clear()
        self.m.poll_target("8.8.8.8")
        events, view = [], None
        while not self.q.empty():
            k, p = self.q.get()
            if k == "event":
                events.append(p)
            elif k == "view":
                view = p
        return events, view

    def test_valid_raises_nothing(self):
        events, view = self.poll()
        self.assertEqual([e.kind for e in events], ["FIRST_SEEN"])
        self.assertEqual((view.rpki, view.status), ("valid", "ok"))

    def test_invalid_alerts_once_then_restores(self):
        self.poll()
        self.rpki.answer = RpkiResult("invalid_asn", "wrong origin")
        events, view = self.poll()
        self.assertEqual([e.kind for e in events], ["RPKI_INVALID"])
        self.assertEqual(events[0].severity, "alert")
        self.assertEqual((view.rpki, view.status), ("invalid_asn", "rpki"))
        events, view = self.poll()                       # still invalid: no second alert
        self.assertEqual(events, [])
        self.assertEqual(view.status, "rpki")
        self.rpki.answer = RpkiResult("valid", "ok again")
        events, view = self.poll()
        self.assertEqual([e.kind for e in events], ["RPKI_RESTORED"])
        self.assertEqual(view.status, "ok")

    def test_unknown_and_error_do_not_alert(self):
        self.poll()
        for status in ("unknown", "error"):
            self.rpki.answer = RpkiResult(status, "")
            events, view = self.poll()
            self.assertEqual(events, [], status)
            self.assertEqual(view.status, "ok")

    def test_switching_off_clears_the_invalid_state(self):
        self.rpki.answer = RpkiResult("invalid_asn", "wrong origin")
        self.assertEqual(self.poll()[1].status, "rpki")
        self.m.rpki = None                                # the GUI toggle sets this
        events, view = self.poll()
        self.assertEqual(events, [])
        self.assertEqual((view.rpki, view.status), ("", "ok"))
        self.m.rpki = self.rpki                           # and back on: alerts again
        self.assertEqual([e.kind for e in self.poll()[0]], ["RPKI_INVALID"])

    def test_off_when_no_checker(self):
        q = queue.Queue()
        m = Monitor(Fixed(), q, None)
        m.add_target("8.8.8.8")
        m.poll_target("8.8.8.8")
        views = [p for k, p in list(q.queue) if k == "view"]
        self.assertEqual(views[-1].rpki, "")


if __name__ == "__main__":
    unittest.main()
