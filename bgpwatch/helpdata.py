"""Content of the in-app help: module descriptions, the component diagram, the explanation text,
and the module-dependency matrix (read from the real imports, so it is never out of date)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent

# ---------------------------------------------------------------- module descriptions
MODULE_INFO = {
    "main": ("main.py", "Command-line entry point. Parses the options, builds the collector, Monitor, "
             "Alerter, AS-name cache and settings, wires them together and starts the GUI (or the "
             "console runner with --no-gui)."),
    "models": ("models.py", "The shared data types: Route (one peer's AS path), PathEvent (something "
               "that changed), TargetView (what the GUI draws) and the AS-path helpers. Almost every "
               "other module imports it."),
    "collectors": ("collectors.py", "Where routes come from. RipeStatCollector asks the RIPEstat "
                   "Looking Glass for the routes of ~400 RIS peers; DemoCollector simulates changes "
                   "offline. Also holds the small HTTP/JSON helper."),
    "live": ("live.py", "The ⚡ Live feed. One RIPE RIS Live stream per target keeps an in-memory "
             "routing table current; it looks like a collector to the engine, and wakes the engine "
             "when an update arrives."),
    "engine": ("engine.py", "The brain. The Monitor thread fetches routes, picks the best path "
               "(consensus or one peer), detects changes with a flap guard, checks the path rules, "
               "and sends views/events to the GUI through a queue."),
    "rules": ("rules.py", "Expected-path rules per target: expected origin AS, ASes the path must "
              "pass through, ASes it must avoid, maximum length."),
    "store": ("store.py", "Persistence. History keeps every change (SQLite, with a snapshot of the "
              "paths so the map can be replayed); Settings saves targets, rules, mutes, theme."),
    "alerts": ("alerts.py", "What happens when an event occurs: console text, rotating log file, "
               "events.jsonl, desktop notification (notify-send) and a row in the history database."),
    "sound": ("sound.py", "Generates and plays the three-beep alert (pw-play / paplay / aplay, "
              "or the Tk bell as a fallback)."),
    "rpki": ("rpki.py", "RPKI origin validation: asks RIPEstat whether a signed ROA authorises the "
             "origin AS of the best path for its prefix (valid / invalid / not found), with a cache. "
             "DemoRpki simulates it offline."),
    "tray": ("tray.py", "The system-tray router icon (optional pystray): draws the icon, colours its "
             "lamp by alert state and sends menu clicks to the GUI through the queue."),
    "asnames": ("asnames.py", "Turns AS numbers into holder names (via RIPEstat), cached on disk."),
    "targets": ("targets.py", "Parses what you type: IP addresses and prefixes, IPv4 and IPv6."),
    "layout": ("layout.py", "Turns a TargetView into a layered graph (peers → transit → origin → "
               "prefix → target) and can export it as SVG."),
    "theme": ("theme.py", "Colours and line styles shared by the canvas and the SVG export."),
    "dialogs": ("dialogs.py", "Small pop-up windows (the expected-path rules editor)."),
    "gui": ("gui.py", "The Tkinter window: target list, path map, paths table, history timeline, "
            "event log, toolbar, themes. Runs on the main thread and drains the queue."),
    "helpdata": ("helpdata.py", "This help: texts, the diagram description and the import matrix."),
    "helpview": ("helpview.py", "The Help window that draws the diagram and the matrix."),
}
EXTERNAL_INFO = {
    "ttkbootstrap": "optional: themed widgets and the theme picker",
}

# order used for the matrix rows/columns (readers first, foundations last)
ORDER = ["main", "gui", "helpview", "helpdata", "dialogs", "alerts", "engine", "live", "collectors",
         "store", "rules", "layout", "theme", "sound", "tray", "rpki", "asnames", "targets", "models"]


def import_matrix() -> tuple:
    """(modules, edges, external): edges[(importer, imported)] = [names]; external[mod] = [pkgs]."""
    files = {p.stem: p for p in PKG.glob("*.py") if p.stem != "__init__"}
    if (ROOT / "main.py").exists():
        files["main"] = ROOT / "main.py"
    edges: dict = {}
    external: dict = {}
    stdlib = set(sys.stdlib_module_names)
    for mod, path in files.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level == 1 or base == "bgpwatch" or base.startswith("bgpwatch."):
                    target = base.split(".")[-1] if base and base != "bgpwatch" else ""
                    if target in files:
                        edges.setdefault((mod, target), []).extend(a.name for a in node.names)
                    elif not target:                       # from . import x  /  from bgpwatch import x
                        for a in node.names:
                            if a.name in files:
                                edges.setdefault((mod, a.name), []).append(a.name)
                elif base.split(".")[0] not in stdlib and base.split(".")[0] != "__future__":
                    external.setdefault(mod, set()).add(base.split(".")[0])
            elif isinstance(node, ast.Import):
                for a in node.names:
                    top = a.name.split(".")[0]
                    if top not in stdlib and top != "bgpwatch":
                        external.setdefault(mod, set()).add(top)
    mods = [m for m in ORDER if m in files] + sorted(m for m in files if m not in ORDER)
    for k, v in edges.items():
        edges[k] = sorted(set(v))
    return mods, edges, {k: sorted(v) for k, v in external.items()}


# ---------------------------------------------------------------- component diagram
# kind: ext (outside world) | thread | core | ui | out | data
BOXES = {
    "ext_live":     (30, 14, 210, 58, "RIPE RIS Live", "HTTP stream of BGP updates", "ext"),
    "ext_ripestat": (290, 14, 210, 58, "RIPEstat", "HTTPS JSON · routes of ~400 RIS peers", "ext"),
    "main":         (760, 14, 310, 58, "main.py", "builds and connects everything below", "core"),
    "live":         (30, 120, 210, 62, "live.py", "stream → in-memory table", "core"),
    "collectors":   (290, 120, 210, 62, "collectors.py", "RipeStatCollector · DemoCollector", "core"),
    "asnames":      (550, 120, 150, 62, "asnames.py", "AS number → name", "core"),
    "rpki":         (740, 120, 150, 62, "rpki.py", "ROA origin validation", "core"),
    "engine":       (150, 236, 290, 74, "engine.py  (Monitor thread)", "poll · best path · change · rules", "thread"),
    "rules":        (530, 242, 150, 62, "rules.py", "expected-path rules", "core"),
    "queue":        (150, 340, 130, 46, "queue.Queue", "view · event · status", "data"),
    "gui":          (150, 420, 290, 78, "gui.py  (Tk main thread)", "map · tables · history · log · themes", "ui"),
    "layout":       (600, 384, 130, 50, "layout.py", "graph + SVG", "ui"),
    "targets":      (600, 444, 130, 50, "targets.py", "parse IP / prefix", "core"),
    "dialogs":      (600, 504, 130, 50, "dialogs.py", "rules editor", "ui"),
    "helpview":     (600, 564, 130, 50, "helpview.py", "this Help window", "ui"),
    "theme":        (790, 384, 120, 50, "theme.py", "colours", "ui"),
    "helpdata":     (790, 564, 145, 50, "helpdata.py", "texts · diagram · matrix", "ui"),
    "alerts":       (30, 590, 170, 56, "alerts.py", "console · logs · notify", "out"),
    "store":        (230, 590, 170, 56, "store.py", "history · settings", "out"),
    "sound":        (430, 590, 140, 56, "sound.py", "3-beep alert", "out"),
    "tray":         (600, 624, 130, 50, "tray.py", "router tray icon", "ui"),
    "ext_disk":     (80, 690, 200, 50, "Disk", "logs · history.db · settings", "ext"),
    "ext_desktop":  (330, 690, 200, 50, "Desktop", "notifications · speakers", "ext"),
    "models":       (640, 690, 430, 56, "models.py", "Route · PathEvent · TargetView — shared by every module", "data"),
}
# (from, to, label, dashed)
EDGES = [
    ("collectors", "ext_ripestat", "HTTPS GET", False),
    ("live", "ext_live", "stream", False),
    ("live", "collectors", "seed once", True),
    ("asnames", "ext_ripestat", "AS names", False),
    ("engine", "live", "fetch() if ⚡", False),
    ("live", "engine", "wake", True),
    ("engine", "collectors", "fetch()", False),
    ("engine", "rules", "check", False),
    ("engine", "asnames", "names", False),
    ("engine", "rpki", "validate origin", False),
    ("rpki", "ext_ripestat", "rpki-validation", False),
    ("engine", "queue", "put", False),
    ("queue", "gui", "every 150 ms", False),
    ("gui", "engine", "start · stop · rules", True),
    ("gui", "layout", "build map", False),
    ("layout", "theme", "colours", False),
    ("gui", "targets", "parse input", False),
    ("gui", "dialogs", "rules editor", False),
    ("gui", "helpview", "F1", False),
    ("helpview", "helpdata", "content", False),
    ("gui", "alerts", "handle(event)", False),
    ("gui", "sound", "beep ×3", False),
    ("gui", "tray", "status · menu", False),
    ("tray", "ext_desktop", "tray icon", False),
    ("gui", "store", "settings", False),
    ("alerts", "store", "history", False),
    ("alerts", "ext_disk", "log files", False),
    ("store", "ext_disk", "SQLite · JSON", False),
    ("alerts", "ext_desktop", "notify-send", False),
    ("sound", "ext_desktop", "audio", False),
]
KIND_NAMES = {"ext": "outside world", "thread": "worker thread", "core": "logic",
              "ui": "user interface", "out": "output / storage", "data": "shared / hand-over"}
KIND_COLORS = {  # light fill, border
    "ext": ("#eceff1", "#607d8b"), "thread": ("#e3f2fd", "#1565c0"), "core": ("#e8f5e9", "#2e7d32"),
    "ui": ("#fff3e0", "#ef6c00"), "out": ("#f3e5f5", "#7b1fa2"), "data": ("#fffde7", "#f9a825"),
}
DIAGRAM_SIZE = (1100, 760)


def box_info(key: str) -> str:
    """Text shown when a diagram box is clicked."""
    if key in MODULE_INFO:
        title, text = MODULE_INFO[key]
    else:
        title, text = BOXES[key][4], BOXES[key][5]
    out = [t for f, t, *_ in EDGES if f == key]
    inn = [f for f, t, *_ in EDGES if t == key]

    def name(k):
        return BOXES[k][4]
    lines = [f"{title} — {text}"]
    if out:
        lines.append("Talks to: " + ", ".join(dict.fromkeys(name(k) for k in out)))
    if inn:
        lines.append("Used by: " + ", ".join(dict.fromkeys(name(k) for k in inn)))
    return "\n".join(lines)


# ---------------------------------------------------------------- every parameter
# (group, name, default, values, description)
PARAMS = [
    ("Command line", "--ips LIST", "-", "comma/space separated IPs or prefixes",
     "Targets to watch. Several can be given, e.g. --ips 8.8.8.8,1.1.1.1."),
    ("Command line", "--file FILE", "-", "path",
     "Text file with one IP/prefix per line; # starts a comment."),
    ("Command line", "--interval N", "60", "seconds (engine minimum 5, window box 10-3600)",
     "Seconds between polls of each target."),
    ("Command line", "--confirm N", "1", "number of polls",
     "Flap guard: a new best path must hold for N polls before an alert is raised."),
    ("Command line", "--mode", "consensus", "consensus | peer",
     "How the best path is chosen: the path most peers use, or the route of one vantage peer."),
    ("Command line", "--vantage COLLECTOR/PEER_IP", "-", "e.g. RRC00/193.0.0.56",
     "The peer whose route is the best path. Required with --mode peer."),
    ("Command line", "--collectors LIST", "all", "e.g. RRC00,RRC03,RRC12",
     "Only use these RIPE RIS collectors (smaller, regional map)."),
    ("Command line", "--max-paths N", "10", "number of paths",
     "Distinct paths drawn on the map (also the 'Paths shown' box)."),
    ("Command line", "--auto-ack N", "0", "number of stable polls; 0 = off",
     "End the changed (blue) state after N stable polls. The GUI timer 'New path blue' does the same by time."),
    ("Command line", "--log-dir DIR", "~/.local/state/bgpwatch", "path",
     "Where logs, history and settings.json are written (demo mode uses a 'demo' sub-folder)."),
    ("Command line", "--no-rpki", "off (RPKI check on)", "flag",
     "Do not validate the origin AS of the best path against RPKI ROAs."),
    ("Command line", "--no-tray", "off (tray icon on)", "flag",
     "Do not show the router icon in the system tray."),
    ("Command line", "--no-notify", "off", "flag",
     "Start with desktop notifications off (can be switched on in the window)."),
    ("Command line", "--demo", "off", "flag", "Use simulated data (no network); a change every 3 polls."),
    ("Command line", "--no-gui", "off", "flag", "Console only (servers, tmux, systemd)."),
    ("Command line", "--minimized", "off", "flag", "Start the window minimised."),
    ("Command line", "--no-restore", "off", "flag", "Ignore the targets and rules saved by the last session."),
    ("Command line", "--version", "-", "flag", "Print the version and exit."),

    ("Window: top rows", "IP / prefix + Add", "-", "IP or prefix, comma separated",
     "Add targets to the list."),
    ("Window: top rows", "Load file… / Save list…", "-", "file",
     "Load targets from a text file / save the current list."),
    ("Window: top rows", "Start / Stop", "Start (Stop when targets are given)", "button",
     "Start or stop polling."),
    ("Window: top rows", "Check now", "-", "button", "Poll every target immediately."),
    ("Window: top rows", "Acknowledge", "-", "button",
     "End the blue blinking of the selected target now."),
    ("Window: top rows", "RPKI", "on (off with --no-rpki)", "on | off",
     "Switch the RPKI origin validation of the best path on or off; targets are re-checked at once. "
     "Saved between sessions."),
    ("Window: top rows", "New path blue", "60 sec", "number + sec | min; 0 = until acknowledged",
     "How long a new best path blinks blue before turning green. Saved between sessions."),
    ("Window: top rows", "Interval (s)", "60", "10 - 3600",
     "Same as --interval; applies immediately."),
    ("Window: top rows", "Best path =", "consensus", "consensus | peer", "Same as --mode."),
    ("Window: top rows", "Vantage peer", "-", "list of collector/peer",
     "Same as --vantage; used when Best path = peer."),
    ("Window: top rows", "Paths shown", "10", "1 - 60", "Same as --max-paths."),
    ("Window: top rows", "Animate", "on", "on | off",
     "White packets travel along the best path from the vantage peer to the target."),
    ("Window: top rows", "Live feed", "off", "on | off",
     "Receive route changes as they happen (RIS Live) instead of only polling. Not in demo mode."),
    ("Window: top rows", "Export SVG…", "-", "button", "Save the current map as an SVG image."),
    ("Window: top rows", "Fit, +, -", "-", "buttons", "Zoom the map (also Ctrl+wheel; drag to pan)."),
    ("Window: top rows", "Theme", "bootstrap-light", "30 themes, half of them dark",
     "Window colours (light and dark). Saved between sessions."),
    ("Window: top rows", "🌙 Dark", "off (follows the theme)", "on | off",
     "Switch between the dark and light twin of the current theme (nord-light <-> nord-dark). "
     "It follows the Theme dropdown and is saved with it. Without ttkbootstrap it flips the built-in "
     "dark/light palette instead."),
    ("Window: event log", "show alternate-path churn", "off", "on | off",
     "Also list updates of paths that are not the best path."),
    ("Window: event log", "mute alert sound", "off", "on | off", "Silence the beeps for every target."),
    ("Window: event log", "desktop notifications", "on (off with --no-notify)", "on | off",
     "Send a desktop pop-up (notify-send) for path changes, rule violations and RPKI invalid. "
     "Greyed out if notify-send is not installed. The beeps, logs and history are not affected. "
     "Saved between sessions."),
    ("Window: event log", "Clear", "-", "button", "Empty the event log view (files are kept)."),
    ("System tray", "router icon", "-", "click / right-click menu",
     "Appears when the app starts. Lamp colour: green all stable, blue path changed, amber fetch error, "
     "red RPKI invalid or rule violated, grey waiting. Tooltip shows the target count and state."),
    ("System tray", "menu: Show / hide window, Check now, Quit", "-", "menu items",
     "Show or hide the main window (also to restore a --minimized start), poll now, or quit the app."),
    ("Window: targets", "Rules…", "-", "button / right-click a target",
     "Edit the expected-path rules of the selected target."),
    ("Window: targets", "Mute this target", "off", "right-click a target",
     "No beep or notification for this target."),
    ("Window: targets", "Remove selected", "-", "button", "Stop watching the selected target."),
    ("Window: history", "Show map at that time / Exit replay", "-", "button, double-click a row",
     "Redraw the map from a stored event; replay is not animated."),

    ("RPKI (automatic)", "RPKI: valid", "-", "shown in the header and the origin AS tooltip",
     "A signed ROA authorises this origin AS for the prefix and its length."),
    ("RPKI (automatic)", "RPKI: INVALID (wrong origin / too specific)", "-", "alert + red origin AS",
     "ROAs exist but do not allow this origin AS or this prefix length: a likely hijack or leak. "
     "Raises RPKI_INVALID (beeps, notification, history); RPKI_RESTORED when it is valid again."),
    ("RPKI (automatic)", "RPKI: not found (no ROA)", "-", "informational",
     "The prefix owner has not published a ROA, so nothing can be verified. No alert."),
    ("RPKI (automatic)", "RPKI: check failed", "-", "informational",
     "RIPEstat could not be reached; retried after 60 s. Results are cached for 15 minutes."),

    ("Rules dialog", "Expected origin AS", "empty", "3356 or AS3356",
     "RULE-VIOLATION if the origin AS is different."),
    ("Rules dialog", "Must pass through (all)", "empty", "AS list",
     "RULE-VIOLATION if any of these ASes is missing from the best path."),
    ("Rules dialog", "Must NOT pass through (any)", "empty", "AS list",
     "RULE-VIOLATION if any of these ASes is on the best path."),
    ("Rules dialog", "Max path length (ASes)", "empty = no limit", "number (prepending collapsed)",
     "RULE-VIOLATION if the best path has more ASes."),
    ("Rules dialog", "apply to all targets", "off", "checkbox", "Copy these rules to every target."),

    ("Alert sound (constants in gui.py)", "ALERT_REPEATS", "3", "number",
     "How many bursts of 3 beeps play for one alert."),
    ("Alert sound (constants in gui.py)", "ALERT_SPAN_S", "10", "seconds",
     "Time from the first to the last burst (3 bursts = at 0, 5 and 10 s)."),
    ("Animation (constants in gui.py)", "PKT_SPEED / PKT_GAP", "140 / 90", "pixels per second / pixels",
     "Packet speed and spacing along the best path."),

    ("Saved settings (settings.json in the log dir)", "targets, rules, muted", "-", "lists",
     "Targets, their rules and per-target mute, restored at start (unless --no-restore)."),
    ("Saved settings (settings.json in the log dir)", "mute_all, dark, theme, live", "-", "values",
     "Global mute, theme and live-feed choice."),
    ("Saved settings (settings.json in the log dir)", "animate, rpki, notify, hl_value, hl_unit", "true, true, true, 60, sec", "values",
     "Packet animation and the blue-path time."),
]


# ---------------------------------------------------------------- the explanation
# ("h1"|"p"|"li"|"code", text)
HELP = [
    ("h1", "What this app does"),
    ("p", "BGP LookingGlass watches how the Internet reaches the IP addresses (or prefixes) you add. "
          "For each target it shows the AS path - the chain of networks packets cross, from many "
          "vantage points around the world to the network that owns the address - and it alerts you "
          "when that path changes or breaks one of your rules."),
    ("h1", "How the data flows"),
    ("li", "1. You add a target (an IP like 8.8.8.8 or a prefix like 1.1.1.0/24). targets.py checks it."),
    ("li", "2. The Monitor thread (engine.py) asks a collector for the target's routes. Normally that "
           "is RIPEstat (collectors.py): one answer holds the route chosen by every RIPE RIS peer "
           "(about 400 routers worldwide). With ⚡ Live feed on, live.py answers instead, from a table "
           "that is kept current by a RIPE RIS Live stream."),
    ("li", "3. Per peer, only the most specific prefix is kept (a /24 beats a /16, because traffic "
           "follows it). The engine then picks the best path: 'consensus' = the path most peers use, "
           "or 'peer' = the route of one router you choose."),
    ("li", "4. It compares that path with the last confirmed one. A different path is a change; with "
           "a flap guard (--confirm N) it must hold for N checks first. A different origin AS is "
           "flagged as a possible hijack."),
    ("li", "5. It checks your expected-path rules (Rules… button) against the best path."),
    ("li", "6. Results travel to the window through a thread-safe queue as 'view' (what to draw), "
           "'event' (what changed) and 'status' messages. Tk is only ever touched by the main thread."),
    ("li", "7. gui.py draws the map with layout.py, fills the tables, and hands every event to "
           "alerts.py, which prints it, logs it, saves it to the history database and raises a "
           "desktop notification. A change or a broken rule also plays three beeps (sound.py)."),
    ("h1", "The screen"),
    ("li", "Path map - peers → transit ASes → origin AS → prefix → target. Green = stable best path, "
           "red = new best path, dashed grey = previous best path, thin grey = alternatives."),
    ("li", "Paths table - the route every peer sees (collector, peer IP, AS, location, path)."),
    ("li", "History - timeline and table of every change and rule violation. 'Show map at that time' "
           "redraws the map as it was; 'Exit replay' returns to live."),
    ("li", "Event log - what just happened. 'show alternate-path churn' adds the non-best path updates."),
    ("li", "Targets list - ✔ stable, ⚠ changed, ⛔ rule violated, ✖ error, 🔕 muted."),
    ("h1", "Polling versus the live feed"),
    ("p", "Polling asks RIPEstat every N seconds (data a few minutes behind real time). ⚡ Live feed "
          "opens one RIS Live stream per target: updates are applied to an in-memory table the moment "
          "they arrive and the engine is woken immediately, so a change shows within seconds. The "
          "table is seeded once from RIPEstat; if the connection drops it is re-seeded."),
    ("h1", "RPKI origin validation"),
    ("p", "For every target the app checks the origin AS of the best path against the RPKI: the "
          "owner of the prefix can publish a signed ROA saying which AS may announce it and how long "
          "the prefix may be. The result is shown in the header and in the origin AS tooltip."),
    ("li", "✔ valid - a ROA authorises this origin AS and prefix length."),
    ("li", "✖ INVALID - ROAs exist but do not allow this origin AS (wrong origin) or this prefix "
           "length (too specific). Likely a hijack or a leak: the origin AS box turns red, the "
           "target is flagged RPKI INVALID and an RPKI_INVALID alert (beeps, notification, history) "
           "is raised. RPKI_RESTORED is logged when it is valid again."),
    ("li", "• not found - no ROA covers the prefix; nothing can be verified, no alert."),
    ("p", "RPKI checks only the origin, not the middle of the path - use the path rules for that. "
          "Switch it on or off with the RPKI toggle at the top of the window (or --no-rpki)."),
    ("h1", "Expected-path rules"),
    ("p", "Per target you can require an origin AS, ASes the path must pass through, ASes it must not "
          "contain and a maximum length. When the best path breaks a rule the target turns ⛔, a "
          "RULE-VIOLATION event is logged with the reason, and you are alerted; RULE-RESTORED follows "
          "when it complies again."),
    ("h1", "Files it writes"),
    ("code", "~/.local/state/bgpwatch/bgpwatch.log     the console text, rotated\n"
             "~/.local/state/bgpwatch/events.jsonl     one JSON object per event\n"
             "~/.local/state/bgpwatch/history.db       SQLite behind the History tab\n"
             "~/.local/state/bgpwatch/settings.json    targets, rules, mutes, theme\n"
             "~/.cache/bgpwatch/asnames.json           AS number → name cache"),
    ("h1", "Threads"),
    ("p", "Main thread: the window (Tk). Monitor thread: polling and analysis. One reader thread per "
          "target when the live feed is on. They never share Tk objects; everything crosses the "
          "queue or a lock-protected table."),
    ("h1", "Reading the other two tabs"),
    ("p", "Component diagram - click a box to highlight its connections and read what it does. "
          "Module matrix - a ● means the module in the row imports the module in the column; "
          "hover a dot to see exactly which names are imported. The matrix is built from the real "
          "source code every time this window opens."),
]


def matrix_csv() -> str:
    mods, edges, _ = import_matrix()
    rows = ["importer," + ",".join(mods)]
    for a in mods:
        rows.append(a + "," + ",".join("1" if (a, b) in edges else "" for b in mods))
    return "\n".join(rows) + "\n"


def edge_points(f: str, t: str) -> tuple:
    """Line between two boxes, clipped to their borders. If the reverse edge also exists the line
    is shifted sideways so the two arrows do not lie on top of each other."""
    def centre(k):
        x, y, w, h = BOXES[k][:4]
        return x + w / 2, y + h / 2

    def clip(k, frm, to):
        x, y, w, h = BOXES[k][:4]
        cx, cy = frm
        dx, dy = to[0] - cx, to[1] - cy
        if dx == 0 and dy == 0:
            return cx, cy
        sx = (w / 2) / abs(dx) if dx else float("inf")
        sy = (h / 2) / abs(dy) if dy else float("inf")
        s = min(sx, sy)
        return cx + dx * s, cy + dy * s
    a, b = centre(f), centre(t)
    if any(ff == t and tt == f for ff, tt, *_ in EDGES):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = (dx * dx + dy * dy) ** 0.5 or 1
        ox, oy = -dy / n * 9, dx / n * 9
        a, b = (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)
    return clip(f, a, b), clip(t, b, a)


def diagram_svg() -> str:
    """The component diagram as a standalone SVG file."""
    from xml.sax.saxutils import escape
    w, h = DIAGRAM_SIZE
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'font-family="sans-serif">',
           '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
           '<path d="M0,0 L8,4 L0,8 z" fill="#555"/></marker></defs>',
           f'<rect width="{w}" height="{h}" fill="#ffffff"/>']
    for f, t, label, dashed in EDGES:
        (x1, y1), (x2, y2) = edge_points(f, t)
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#555" '
                   f'stroke-width="1.4"{dash} marker-end="url(#a)"/>')
        out.append(f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 - 3:.0f}" font-size="10" '
                   f'fill="#444" text-anchor="middle">{escape(label)}</text>')
    for key, (x, y, bw, bh, title, sub, kind) in BOXES.items():
        fill, border = KIND_COLORS[kind]
        out.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8" fill="{fill}" '
                   f'stroke="{border}" stroke-width="2"/>')
        out.append(f'<text x="{x + bw / 2}" y="{y + bh / 2 - 3}" font-size="13" font-weight="bold" '
                   f'text-anchor="middle" fill="#222">{escape(title)}</text>')
        out.append(f'<text x="{x + bw / 2}" y="{y + bh / 2 + 14}" font-size="10" text-anchor="middle" '
                   f'fill="#555">{escape(sub)}</text>')
    out.append("</svg>")
    return "\n".join(out)
