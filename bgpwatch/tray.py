"""System-tray icon: a router that changes colour with the alert state.

Needs the optional `pystray` + Pillow packages (and, on GNOME, the AppIndicator extension that
Ubuntu ships). Without them `Tray.start()` returns False and the app simply has no tray icon.

The tray runs in its own thread, so its menu never touches Tk directly: it puts ("tray", action)
on the application's queue and the Tk thread picks it up.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable

# status colour of the little lamp on the router
COLORS = {"ok": "#2e9e44", "changed": "#1e88ff", "error": "#e0a000", "alert": "#d93636",
          "idle": "#8a8a8a"}


def overall_status(views) -> str:
    """Worst state over all targets: alert (RPKI invalid / rule violation) > changed > error > ok."""
    states = {v.status for v in views}
    if not states:
        return "idle"
    if states & {"rpki", "violation"}:
        return "alert"
    for s in ("changed", "error"):
        if s in states:
            return s
    return "ok" if "ok" in states else "idle"


def router_icon(status: str = "ok", size: int = 64):
    """A drawn router (body, two antennas, LEDs) with a status lamp. Returns a PIL image."""
    from PIL import Image, ImageDraw
    k = 4                                        # draw big, shrink for smooth edges
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 64
    body, edge, light = "#2f3b4c", "#141a22", "#e8eef5"
    for x in (16, 48):                           # antennas
        d.line([(x * u, 38 * u), (x * u, 10 * u)], fill=edge, width=int(4 * u))
        d.ellipse([(x - 4) * u, 6 * u, (x + 4) * u, 14 * u], fill=light, outline=edge, width=int(1.5 * u))
    d.rounded_rectangle([4 * u, 34 * u, 60 * u, 56 * u], radius=int(5 * u), fill=body, outline=edge,
                        width=int(2 * u))        # body
    for i, x in enumerate((12, 20, 28)):         # port LEDs
        d.rectangle([x * u, 42 * u, (x + 5) * u, 48 * u], fill=("#7fd1ff" if i < 2 else "#5b6b80"))
    d.ellipse([44 * u, 40 * u, 56 * u, 52 * u], fill=COLORS.get(status, COLORS["idle"]),
              outline=light, width=int(1.5 * u))  # status lamp
    return img.resize((size, size), Image.LANCZOS)


class Tray:
    def __init__(self, q: queue.Queue, title: str = "BGP LookingGlass"):
        self.q, self.title = q, title
        self.icon = None
        self.status = "idle"

    def start(self) -> bool:
        try:
            import pystray
            from pystray import Menu, MenuItem as Item
            self._pystray = pystray
            send: Callable = lambda action: (lambda *_: self.q.put(("tray", action)))
            menu = Menu(
                Item("Show / hide window", send("toggle"), default=True),
                Item("Check now", send("check")),
                Menu.SEPARATOR,
                Item("Quit", send("quit")))
            self.icon = pystray.Icon("bgpwatch", router_icon("idle"), self.title, menu)
            # Tk owns the main thread, so the tray runs its own loop in a daemon thread
            # (run_detached() would wait for a GTK main loop that does not exist here)
            threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
            return True
        except Exception:                        # no pystray / Pillow / tray host: run without
            self.icon = None
            return False

    def update(self, status: str, text: str = ""):
        """Change the lamp colour and tooltip; cheap to call on every refresh."""
        if not self.icon:
            return
        title = f"{self.title} - {text}" if text else self.title
        if status != self.status:
            self.status = status
            self.icon.icon = router_icon(status)
        if self.icon.title != title:
            self.icon.title = title

    def notify(self, title: str, body: str):
        """A balloon / toast from the tray icon (used on Windows, where there is no notify-send)."""
        if self.icon:
            self.icon.notify(body, title)

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
