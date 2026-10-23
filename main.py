#!/usr/bin/env python3
"""BGP LookingGlass - live BGP AS-path map with path-change alerts.

Examples
  ./main.py                                   # GUI, add IPs in the window
  ./main.py --ips 8.8.8.8,1.1.1.1             # GUI, start monitoring at once
  ./main.py --file targets.txt --interval 120
  ./main.py --demo --ips 8.8.8.8,1.1.1.1 --interval 10   # simulated changes
  ./main.py --no-gui --ips 8.8.8.8            # console only (servers, tmux)
"""
from __future__ import annotations

import argparse
import os
import queue
import signal
import sys
import time
from pathlib import Path

# use the project's virtualenv (it holds ttkbootstrap) when there is one
_VENV_PY = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != _VENV_PY.parent.parent.resolve() \
        and not os.environ.get("BGPWATCH_NO_VENV"):
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

from bgpwatch import __version__
from bgpwatch.alerts import Alerter, default_log_dir
from bgpwatch.asnames import ASNames
from bgpwatch.collectors import DemoCollector, RipeStatCollector
from bgpwatch.engine import Monitor
from bgpwatch.rpki import DemoRpki, RpkiChecker
from bgpwatch.rules import Rules
from bgpwatch.store import Settings


def read_targets(args) -> list:
    from bgpwatch.targets import parse_targets
    raw = []
    if args.ips:
        raw.append(args.ips)
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            raw.append(line.split("#")[0])
    good, bad = parse_targets(" ".join(raw))
    for b in bad:
        print(f"warning: ignoring '{b}' (not an IP address or prefix)", file=sys.stderr)
    return list(dict.fromkeys(good))


def main(argv=None):
    p = argparse.ArgumentParser(description="Live BGP AS-path map with change alerts.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("Examples", 1)[1])
    p.add_argument("--ips", help="comma/space separated IPs or prefixes")
    p.add_argument("--file", help="file with one IP/prefix per line (# comments allowed)")
    p.add_argument("--interval", type=int, default=60, help="seconds between polls (default 60)")
    p.add_argument("--confirm", type=int, default=1,
                   help="polls a new best path must persist before alerting (flap guard, default 1)")
    p.add_argument("--mode", choices=["consensus", "peer"], default="consensus",
                   help="how the best path is chosen (default consensus)")
    p.add_argument("--vantage", default="",
                   help="with --mode peer: collector/peer, e.g. RRC00/193.0.0.56")
    p.add_argument("--collectors", default="",
                   help="only use these RIS collectors, e.g. RRC00,RRC03,RRC12")
    p.add_argument("--max-paths", type=int, default=10, help="distinct paths drawn on the map")
    p.add_argument("--auto-ack", type=int, default=0,
                   help="end the blue 'path changed' highlight after N stable polls (0 = keep until acknowledged)")
    p.add_argument("--log-dir", default=str(default_log_dir()), help="where logs are written")
    p.add_argument("--no-rpki", action="store_true",
                   help="do not validate the origin AS of the best path against RPKI ROAs")
    p.add_argument("--no-tray", action="store_true", help="no icon in the system tray")
    p.add_argument("--no-notify", action="store_true", help="no desktop notifications")
    p.add_argument("--demo", action="store_true", help="simulated data (no network needed)")
    p.add_argument("--no-gui", action="store_true", help="console only")
    p.add_argument("--minimized", action="store_true", help="start the window minimised")
    p.add_argument("--no-restore", action="store_true",
                   help="do not reload the targets/rules saved by the previous session")
    p.add_argument("--version", action="version", version=f"bgpwatch {__version__}")
    args = p.parse_args(argv)

    if args.mode == "peer" and not args.vantage:
        p.error("--mode peer needs --vantage COLLECTOR/PEER_IP")

    targets = read_targets(args)
    q: queue.Queue = queue.Queue()
    collector = (DemoCollector() if args.demo else
                 RipeStatCollector(collectors=[c for c in args.collectors.split(",") if c] or None))
    names = ASNames(online=not args.demo)
    log_dir = Path(args.log_dir) / ("demo" if args.demo else "")     # keep demo data apart
    alerter = Alerter(log_dir, notify=not args.no_notify)
    monitor = Monitor(collector, q, names, interval=args.interval, confirm=args.confirm,
                      mode=args.mode, vantage=args.vantage, auto_ack=args.auto_ack,
                      pause_between=0 if args.demo else 1.0,
                      rpki=None if args.no_rpki else (DemoRpki() if args.demo else RpkiChecker()))
    settings = Settings(alerter.log_dir / "settings.json")
    if not args.no_restore:
        targets = list(dict.fromkeys(targets + list(settings.data.get("targets", []))))
        for t, d in settings.data.get("rules", {}).items():
            monitor.rules[t] = Rules.from_dict(d)
    alerter.muted = set(settings.data.get("muted", []))
    for t in targets:
        monitor.add_target(t)

    print(f"BGP LookingGlass {__version__} · source: {collector.name} · "
          f"logs: {alerter.log_dir}", flush=True)

    if args.no_gui:
        return run_console(monitor, alerter, q)

    try:
        import tkinter as tk
    except ImportError:
        print("Tkinter is not installed. On Debian/Ubuntu: sudo apt install python3-tk\n"
              "Or run with --no-gui for console mode.", file=sys.stderr)
        return 1
    from bgpwatch.gui import BGPWatchApp
    root = make_root(tk, settings)
    BGPWatchApp(root, monitor, names, alerter, q, max_paths=args.max_paths, demo=args.demo,
                autostart=bool(targets), settings=settings, minimized=args.minimized,
                tray=not args.no_tray)
    root.mainloop()
    return 0


def make_root(tk, settings):
    """A themed ttkbootstrap window when the package is installed, a plain Tk window otherwise."""
    try:
        import ttkbootstrap as tb
    except ImportError:
        return tk.Tk()
    name = settings.data.get("theme") or ("bootstrap-dark" if settings.data.get("dark")
                                          else "bootstrap-light")
    try:
        return tb.Window(themename=name)
    except Exception:
        return tb.Window(themename="bootstrap-light")


def run_console(monitor, alerter, q) -> int:
    if not monitor.targets():
        print("No targets. Use --ips or --file.", file=sys.stderr)
        return 2
    signal.signal(signal.SIGINT, lambda *a: (monitor.shutdown(), sys.exit(0)))
    monitor.start()
    while True:
        try:
            kind, payload = q.get(timeout=1)
        except queue.Empty:
            continue
        if kind == "event" and payload.kind != "ALT_CHANGED":
            alerter.handle(payload)
        elif kind == "event":
            alerter.log.info(payload.console_block())


if __name__ == "__main__":
    sys.exit(main())
