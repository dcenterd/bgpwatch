import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch import messenger  # noqa: E402
from bgpwatch.alerts import Alerter  # noqa: E402
from bgpwatch.models import PathEvent  # noqa: E402


class MessengerTests(unittest.TestCase):
    def test_telegram_request(self):
        req = messenger.build_request({"kind": "telegram", "token": "T", "chat_id": "42"}, "t", "b")
        self.assertEqual(req.full_url, "https://api.telegram.org/botT/sendMessage")
        self.assertEqual(json.loads(req.data)["chat_id"], "42")

    def test_incomplete_config(self):
        self.assertIn("token", messenger.send({"kind": "telegram"}, "t", "b"))
        self.assertIn("http", messenger.send({"kind": "webhook", "url": "x"}, "t", "b"))

    def test_webhook_flavours(self):
        d = messenger.build_request({"kind": "webhook", "url": "https://discord.com/api/webhooks/1/x"}, "t", "b")
        self.assertIn("content", json.loads(d.data))
        n = messenger.build_request({"kind": "webhook", "url": "https://ntfy.sh/topic"}, "t", "b")
        self.assertEqual(n.data, b"b")

    def test_alert_pushes_only_when_enabled(self):
        a = Alerter(Path(tempfile.mkdtemp()), notify=False, color=False)
        ev = PathEvent("BEST_CHANGED", "8.8.8.8", "8.8.8.0/24", "consensus", (1, 2), (1, 3))
        with mock.patch.object(messenger.Messenger, "_run") as run:
            a.handle(ev)
            self.assertFalse(run.called)
            a.messenger = messenger.Messenger({"enabled": True, "token": "T", "chat_id": "1"})
            with mock.patch("bgpwatch.messenger.threading.Thread") as th:
                a.handle(ev)
                self.assertTrue(th.return_value.start.called)


if __name__ == "__main__":
    unittest.main()
