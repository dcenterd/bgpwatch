import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch.alerts import Alerter  # noqa: E402
from bgpwatch.models import PathEvent  # noqa: E402


def alert(kind="BEST_CHANGED", target="8.8.8.8"):
    return PathEvent(kind, target, "8.8.8.0/24", "consensus", (1, 2), (1, 3))


class NotifyTests(unittest.TestCase):
    def make(self, notify=True):
        a = Alerter(Path(tempfile.mkdtemp()), notify=notify, color=False)
        a.notify_cmd = "/usr/bin/notify-send"             # pretend it is installed
        return a

    def sent(self, a, ev):
        with mock.patch("bgpwatch.alerts.subprocess.Popen") as popen:
            a.handle(ev)
        return popen.call_count

    def test_enabled_sends_for_every_alert_kind(self):
        a = self.make()
        for kind in ("BEST_CHANGED", "RULE_VIOLATION", "RPKI_INVALID"):
            self.assertEqual(self.sent(a, alert(kind)), 1, kind)

    def test_switch_off_sends_nothing_but_still_logs(self):
        a = self.make()
        a.notify_enabled = False                           # what the GUI switch does
        self.assertEqual(self.sent(a, alert()), 0)
        self.assertIn("BEST-CHANGED", (a.log_dir / "events.jsonl").read_text().upper().replace("_", "-"))
        a.notify_enabled = True                            # and back on
        self.assertEqual(self.sent(a, alert()), 1)

    def test_no_notify_flag_starts_off(self):
        a = self.make(notify=False)
        self.assertFalse(a.notify_enabled)
        self.assertEqual(self.sent(a, alert()), 0)

    def test_muted_target_and_info_events_never_notify(self):
        a = self.make()
        a.muted = {"8.8.8.8"}
        self.assertEqual(self.sent(a, alert()), 0)
        self.assertEqual(self.sent(self.make(), alert("FIRST_SEEN")), 0)

    def test_missing_notify_send_is_safe(self):
        a = self.make()
        a.notify_cmd = None
        self.assertEqual(self.sent(a, alert()), 0)


if __name__ == "__main__":
    unittest.main()
