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
