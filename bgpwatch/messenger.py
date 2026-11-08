"""Push alerts to a chat messenger: Telegram bot, or a webhook (Discord / Slack / ntfy / generic)."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

KINDS = ("telegram", "webhook")


def default_config() -> dict:
    return {"enabled": False, "kind": "telegram", "token": "", "chat_id": "", "url": ""}


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


def send(cfg: dict, title: str, body: str, timeout: float = 10) -> str | None:
    """Send synchronously. Returns None on success, else a short error message."""
    try:
        req = build_request(cfg, title, body)
        with urllib.request.urlopen(req, timeout=timeout):
            pass
        return None
    except ValueError as e:
        return str(e)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, OSError) as e:
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
