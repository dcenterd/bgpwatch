"""Push alerts to a chat messenger: Telegram bot, or a webhook (Discord / Slack / ntfy / generic)."""
from __future__ import annotations

import functools
import http.client
import json
import socket
import ssl
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request

KINDS = ("telegram", "webhook")


def default_config() -> dict:
    return {"enabled": False, "kind": "telegram", "token": "", "chat_id": "", "url": "",
            "proxy": "", "proxy_user": "", "proxy_pass": ""}


def build_request(cfg: dict, title: str, body: str) -> urllib.request.Request:
    """Build the HTTP request for one message. Raises ValueError when the config is incomplete."""
    text = f"{title}\n{body}".strip()
    if cfg.get("kind") == "webhook":
        url = (cfg.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("webhook URL must start with http:// or https://")
        if "discord.com/api/webhooks" in url:
            data, ctype = json.dumps({"content": text[:2000]}).encode(), "application/json"
        elif "hooks.slack.com" in url:
            data, ctype = json.dumps({"text": text}).encode(), "application/json"
        else:                                    # ntfy.sh and anything else: plain-text body
            req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
            req.add_header("Title", title.encode("ascii", "replace").decode())
            req.add_header("Priority", "high")
            return req
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", ctype)
        return req
    token, chat = (cfg.get("token") or "").strip(), str(cfg.get("chat_id") or "").strip()
    if not token or not chat:
        raise ValueError("Telegram needs a bot token and a chat ID")
    data = json.dumps({"chat_id": chat, "text": text[:4000],
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    return req


def _socks5_connect(proxy, host, port, timeout):
    """Open a TCP connection to host:port through a SOCKS5 proxy (RFC 1928/1929); the proxy resolves the name."""
    sock = socket.create_connection((proxy["host"], proxy["port"]), timeout)
    try:
        user, pw = proxy["user"].encode(), proxy["pass"].encode()
        sock.sendall(b"\x05\x02\x00\x02" if user else b"\x05\x01\x00")
        ver, method = sock.recv(2)
        if ver != 5 or method == 0xFF:
            raise OSError("SOCKS5 proxy refused our authentication methods")
        if method == 2:
            sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pw)]) + pw)
            if sock.recv(2)[1] != 0:
                raise OSError("SOCKS5 proxy: wrong username or password")
        name = host.encode("idna")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", port))
        head = sock.recv(4)
        if len(head) < 4 or head[1] != 0:
            raise OSError(f"SOCKS5 proxy could not connect (code {head[1] if len(head) > 1 else '?'})")
        rest = {1: 4, 4: 16}.get(head[3])
        sock.recv((sock.recv(1)[0] if rest is None else rest) + 2)      # bound address + port
        return sock
    except Exception:
        sock.close()
        raise


class _SocksHTTP(http.client.HTTPConnection):
    def __init__(self, *a, proxy=None, **kw):
        super().__init__(*a, **kw)
        self._proxy = proxy

    def connect(self):
        self.sock = _socks5_connect(self._proxy, self.host, self.port, self.timeout)


class _SocksHTTPS(http.client.HTTPSConnection):
    def __init__(self, *a, proxy=None, **kw):
        super().__init__(*a, **kw)
        self._proxy = proxy

    def connect(self):
        raw = _socks5_connect(self._proxy, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _SocksHandler(urllib.request.HTTPSHandler, urllib.request.HTTPHandler):
    def __init__(self, proxy):
        urllib.request.HTTPSHandler.__init__(self)
        self.proxy = proxy

    def http_open(self, req):
        return self.do_open(functools.partial(_SocksHTTP, proxy=self.proxy), req)

    def https_open(self, req):
        return self.do_open(functools.partial(_SocksHTTPS, proxy=self.proxy), req)


def build_opener(cfg: dict) -> urllib.request.OpenerDirector:
    """An opener that goes through cfg['proxy'] (http://, https:// or socks5://host:port), with optional login.
    No proxy configured: connect directly (the system proxy variables are ignored on purpose)."""
    raw = (cfg.get("proxy") or "").strip()
    if not raw:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if "://" not in raw:
        raw = "http://" + raw
    u = urllib.parse.urlsplit(raw)
    if u.scheme not in ("http", "https", "socks5", "socks5h") or not u.hostname:
        raise ValueError("proxy must look like http://host:port or socks5://host:port")
    user = cfg.get("proxy_user") or urllib.parse.unquote(u.username or "")
    pw = cfg.get("proxy_pass") or urllib.parse.unquote(u.password or "")
    if u.scheme.startswith("socks5"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _SocksHandler(
            {"host": u.hostname, "port": u.port or 1080, "user": user, "pass": pw}))
    netloc = f"{u.hostname}:{u.port or (443 if u.scheme == 'https' else 8080)}"
    if user:
        netloc = f"{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(pw, safe='')}@{netloc}"
    url = f"{u.scheme}://{netloc}"
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": url, "https": url}))


def send(cfg: dict, title: str, body: str, timeout: float = 10) -> str | None:
    """Send synchronously. Returns None on success, else a short error message."""
    try:
        req = build_request(cfg, title, body)
        with build_opener(cfg).open(req, timeout=timeout):
            pass
        return None
    except ValueError as e:
        return str(e)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        return str(getattr(e, "reason", e))


class Messenger:
    """Holds the config and sends in a background thread so a slow network never stalls the monitor."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = {**default_config(), **(cfg or {})}
        self.last_error: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.cfg.get("enabled"))

    def notify(self, title: str, body: str):
        if not self.active:
            return
        threading.Thread(target=self._run, args=(dict(self.cfg), title, body), daemon=True).start()

    def _run(self, cfg, title, body):
        self.last_error = send(cfg, title, body)
