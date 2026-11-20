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
        self.assertIn("http", messenger.send({"kind": "webhook", "url": ""}, "t", "b"))

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


class ProxyTests(unittest.TestCase):
    """Real sockets on localhost: a fake HTTP proxy and a fake SOCKS5 proxy."""

    def serve(self, handler):
        import socketserver
        import threading

        class S(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        srv = S(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_http_proxy_with_and_without_auth(self):
        import base64
        import http.server
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path, self.headers.get("Proxy-Authorization")))
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        port = self.serve(H)
        cfg = {"kind": "webhook", "url": "http://hook.example/x", "proxy": f"127.0.0.1:{port}"}
        self.assertIsNone(messenger.send(cfg, "t", "b"))
        self.assertEqual(seen[-1], ("http://hook.example/x", None))
        cfg.update(proxy_user="bob", proxy_pass="p@ss")
        self.assertIsNone(messenger.send(cfg, "t", "b"))
        token = base64.b64encode(b"bob:p@ss").decode()
        self.assertEqual(seen[-1][1], "Basic " + token)

    def test_socks5_with_and_without_auth(self):
        import socketserver
        seen = []

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                r = self.request
                r.recv(1)
                n = r.recv(1)[0]
                methods = r.recv(n)
                user = None
                if 2 in methods:
                    r.sendall(b"\x05\x02")
                    r.recv(1)
                    u = r.recv(r.recv(1)[0]).decode()
                    p = r.recv(r.recv(1)[0]).decode()
                    r.sendall(b"\x01\x00")
                    user = (u, p)
                else:
                    r.sendall(b"\x05\x00")
                r.recv(4)
                host = r.recv(r.recv(1)[0]).decode()
                r.recv(2)
                seen.append((user, host))
                r.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                r.recv(65536)
                r.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        port = self.serve(H)
        cfg = {"kind": "webhook", "url": "http://hook.example/x", "proxy": f"socks5://127.0.0.1:{port}"}
        self.assertIsNone(messenger.send(cfg, "t", "b"))
        self.assertEqual(seen[-1], (None, "hook.example"))
        cfg.update(proxy_user="bob", proxy_pass="pw")
        self.assertIsNone(messenger.send(cfg, "t", "b"))
        self.assertEqual(seen[-1], (("bob", "pw"), "hook.example"))

    def test_bad_proxy_and_dead_proxy(self):
        self.assertIn("proxy must", messenger.send(
            {"kind": "webhook", "url": "http://h/x", "proxy": "ftp://x:1"}, "t", "b"))
        self.assertIsNotNone(messenger.send(
            {"kind": "webhook", "url": "http://h/x", "proxy": "127.0.0.1:9"}, "t", "b", timeout=2))


class BotWebhookTests(unittest.TestCase):
    """Bale as a service, Telegram / Bale bot URLs used as the webhook, URLs without a scheme."""

    def test_bale_request(self):
        req = messenger.build_request({"kind": "bale", "token": "T", "chat_id": "42"}, "t", "b")
        self.assertEqual(req.full_url, "https://tapi.bale.ai/botT/sendMessage")
        self.assertEqual(json.loads(req.data), {"chat_id": "42", "text": "t\nb",
                                                "disable_web_page_preview": True})
        self.assertIn("Bale needs", messenger.send({"kind": "bale", "token": "T"}, "t", "b"))

    def test_webhook_without_scheme_gets_https(self):
        self.assertEqual(messenger.normalize_url("  ntfy.sh/topic "), "https://ntfy.sh/topic")
        self.assertEqual(messenger.normalize_url("http://h/x"), "http://h/x")
        self.assertEqual(messenger.normalize_url(""), "")
        req = messenger.build_request({"kind": "webhook", "url": "ntfy.sh/topic"}, "t", "b")
        self.assertEqual(req.full_url, "https://ntfy.sh/topic")
        self.assertIn("webhook URL", messenger.send({"kind": "webhook", "url": ""}, "t", "b"))
        self.assertIn("webhook URL", messenger.send({"kind": "webhook", "url": "ftp://h/x"}, "t", "b"))

    def test_telegram_bot_url_as_webhook(self):
        for url in ("https://api.telegram.org/bot123:ABC/sendMessage?chat_id=-1001",
                    "api.telegram.org/bot123:ABC/sendMessage?chat_id=-1001",
                    "https://api.telegram.org/bot123:ABC"):
            cfg = {"kind": "webhook", "url": url, "chat_id": "-1001"}
            req = messenger.build_request(cfg, "Alert", "path changed")
            self.assertEqual(req.full_url, "https://api.telegram.org/bot123:ABC/sendMessage", url)
            self.assertEqual(req.get_header("Content-type"), "application/json")
            body = json.loads(req.data)
            self.assertEqual((body["chat_id"], body["text"]), ("-1001", "Alert\npath changed"))

    def test_bale_bot_url_as_webhook(self):
        req = messenger.build_request(
            {"kind": "webhook", "url": "https://tapi.bale.ai/botXYZ/sendMessage?chat_id=77"}, "t", "b")
        self.assertEqual(req.full_url, "https://tapi.bale.ai/botXYZ/sendMessage")
        self.assertEqual(json.loads(req.data)["chat_id"], "77")

    def test_url_chat_id_wins_over_field(self):
        req = messenger.build_request({"kind": "webhook", "chat_id": "1",
                                       "url": "https://tapi.bale.ai/botX/sendMessage?chat_id=2"}, "t", "b")
        self.assertEqual(json.loads(req.data)["chat_id"], "2")

    def test_bot_url_errors(self):
        self.assertIn("chat ID", messenger.send(
            {"kind": "webhook", "url": "https://api.telegram.org/botT/sendMessage"}, "t", "b"))
        self.assertIn("bot<token>", messenger.send(
            {"kind": "webhook", "url": "https://api.telegram.org/sendMessage?chat_id=1"}, "t", "b"))
        self.assertIn("unknown", messenger.send({"kind": "signal"}, "t", "b"))

    def test_other_hosts_untouched(self):
        req = messenger.build_request({"kind": "webhook", "url": "https://example.com/botX?chat_id=1"}, "t", "b")
        self.assertEqual(req.data, b"b")


class BotWebhookLiveTests(unittest.TestCase):
    """End to end: send a bot-URL webhook through a local fake proxy that plays the bot API."""
    serve = ProxyTests.serve

    def fake_api(self, status=200, reply=b'{"ok":true}'):
        import http.server
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                seen.append((self.path, self.headers.get("Content-Type"), json.loads(data)))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *a):
                pass
        return self.serve(H), seen

    def test_bot_webhook_delivered(self):
        port, seen = self.fake_api()
        for host in ("api.telegram.org", "tapi.bale.ai"):
            cfg = {"kind": "webhook", "proxy": f"127.0.0.1:{port}",
                   "url": f"http://{host}/botTOK/sendMessage?chat_id=55"}
            self.assertIsNone(messenger.send(cfg, "BGP LookingGlass", "Test message"))
            path, ctype, body = seen[-1]
            self.assertEqual(path, f"http://{host}/botTOK/sendMessage")
            self.assertEqual(ctype, "application/json")
            self.assertEqual(body["chat_id"], "55")
            self.assertEqual(body["text"], "BGP LookingGlass\nTest message")

    def test_api_error_description_reported(self):
        port, _ = self.fake_api(400, b'{"ok":false,"description":"Bad Request: chat not found"}')
        cfg = {"kind": "webhook", "proxy": f"127.0.0.1:{port}",
               "url": "http://api.telegram.org/botTOK/sendMessage?chat_id=55"}
        self.assertEqual(messenger.send(cfg, "t", "b"), "HTTP 400: Bad Request: chat not found")
