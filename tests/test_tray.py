import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch import tray  # noqa: E402


def views(*states):
    return [SimpleNamespace(status=s) for s in states]


class TrayTests(unittest.TestCase):
    def test_overall_status_is_the_worst_state(self):
        self.assertEqual(tray.overall_status([]), "idle")
        self.assertEqual(tray.overall_status(views("pending")), "idle")
        self.assertEqual(tray.overall_status(views("ok", "ok")), "ok")
        self.assertEqual(tray.overall_status(views("ok", "error")), "error")
        self.assertEqual(tray.overall_status(views("ok", "error", "changed")), "changed")
        self.assertEqual(tray.overall_status(views("changed", "rpki")), "alert")
        self.assertEqual(tray.overall_status(views("ok", "violation")), "alert")

    def test_router_icon_is_drawn_for_every_state(self):
        imgs = {s: tray.router_icon(s, 64) for s in tray.COLORS}
        for s, im in imgs.items():
            self.assertEqual(im.size, (64, 64), s)
            self.assertEqual(im.mode, "RGBA", s)
            self.assertGreater(im.getchannel("A").getbbox()[2], 40, s)     # something was drawn
        self.assertNotEqual(imgs["ok"].tobytes(), imgs["alert"].tobytes())  # lamp colour differs
        lamp = imgs["alert"].getpixel((50, 46))[:3]
        self.assertGreater(lamp[0], 180)                                    # red lamp

    def test_start_without_pystray_is_harmless(self):
        t = tray.Tray(queue.Queue())
        with mock.patch.dict(sys.modules, {"pystray": None}):
            self.assertFalse(t.start())
        t.update("alert", "x")                                              # no icon: must not raise
        t.stop()

    def test_menu_clicks_go_to_the_queue(self):
        q = queue.Queue()
        fake = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"pystray": fake}):
            self.assertTrue(tray.Tray(q).start())
        items = fake.Menu.call_args.args
        callbacks = [c.args[1] for c in fake.MenuItem.call_args_list]
        self.assertEqual(len(callbacks), 3)
        for cb in callbacks:
            cb(None, None)
        self.assertEqual([q.get_nowait() for _ in range(3)],
                         [("tray", "toggle"), ("tray", "check"), ("tray", "quit")])
        import time
        for _ in range(50):                               # the loop runs in a daemon thread
            if fake.Icon.return_value.run.called:
                break
            time.sleep(0.01)
        fake.Icon.return_value.run.assert_called_once()
        self.assertTrue(items)

    def test_update_only_redraws_on_change(self):
        t = tray.Tray(queue.Queue())
        t.icon = SimpleNamespace(icon=None, title="")
        t.update("ok", "1 target(s)")
        first = t.icon.icon
        t.update("ok", "1 target(s)")
        self.assertIs(t.icon.icon, first)                                   # same state: same image
        t.update("alert", "1 target(s)")
        self.assertIsNot(t.icon.icon, first)


if __name__ == "__main__":
    unittest.main()
