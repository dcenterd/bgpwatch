"""Tkinter GUI: target list, AS-path map, paths table and event log."""
from __future__ import annotations

import queue
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk as _ttk

try:                                  # optional: themed widgets that accept bootstyle=...
    import ttkbootstrap as _tb
except ImportError:
    _tb = None


class _Ttk:
    """ttk namespace: ttkbootstrap widgets when installed, tkinter.ttk for anything else."""
    def __getattr__(self, name):
        if _tb is not None and hasattr(_tb, name):
            return getattr(_tb, name)
        return getattr(_ttk, name)


ttk = _Ttk()

from .asnames import short_name
from .dialogs import edit_rules
from .helpview import HelpWindow
from .live import LiveCollector
from .layout import NODE_H, NODE_W, RANK, build_graph, to_svg
from .models import Route, TargetView, collapse_prepends, fmt_path
from .sound import play_alert
from .rpki import LABELS as RPKI_LABELS, SHORT as RPKI_SHORT, DemoRpki, RpkiChecker
from .store import Settings
from .tray import Tray, overall_status
from .targets import parse_targets
from .theme import EDGE_STYLE, GREEN, HEADER_BG, NEW_BLUE, RED, HEADER_FG, STATUS_ICON, node_colors


LIGHT = dict(bg="#dcdad5", panel="#ffffff", fg="#222222", dim="#666666", field="#ffffff",
             sel="#4b6983", canvas="#ffffff", log="#fafaf8", legend="#444444")
DARK = dict(bg="#26282b", panel="#1e1f22", fg="#e2e2e2", dim="#9a9a9a", field="#1e1f22",
            sel="#3d5a80", canvas="#1b1c1f", log="#17181a", legend="#cfcfcf")


def counterpart_theme(name: str, names) -> str:
    """The light variant of a dark ttkbootstrap theme and vice versa (the themes come in pairs):
    'nord-dark' <-> 'nord-light'. Returns `name` when there is no counterpart."""
    for a, b in (("-dark", "-light"), ("-light", "-dark")):
        if name.endswith(a) and name[:-len(a)] + b in names:
            return name[:-len(a)] + b
    return name


class BGPWatchApp:
    POLL_MS = 150

    def __init__(self, root: tk.Tk, monitor, names, alerter, q: queue.Queue,
                 max_paths: int = 10, demo: bool = False, autostart: bool = True,
                 settings: Settings | None = None, minimized: bool = False, tray: bool = True):
        self.root, self.monitor, self.names, self.alerter, self.q = root, monitor, names, alerter, q
        self.demo, self._rpki = demo, None
        self.views: dict = {}
        self.selected: str | None = None
        self.zoom = 1.0
        self.vantage_map: dict = {}
        self._tip = None
        self._graph = None
        self._flow, self._pkts, self._pkt_r, self._pkt_t0 = None, [], 4, 0.0
        self._anim_id = None
        self._blink_on, self._hl_check = None, 0.0
        self._needs_fit = True
        self.settings = settings or Settings(alerter.log_dir / "settings.json")
        self.muted_targets: set = alerter.muted      # shared with the Alerter (no notification)
        self.hist_view = None                        # TargetView rebuilt from a history row
        self.hist_event = None
        self._hist_rows: list = []
        self.pal = LIGHT
        # ttkbootstrap root (themes, bootstyle buttons) when available, plain ttk otherwise
        self.tb = hasattr(root, "style") and hasattr(root.style, "colors")
        self.sty_run, self.sty_stop = (("success.TButton", "danger.TButton") if self.tb
                                       else ("Run.TButton", "Stop.TButton"))
        self.live: LiveCollector | None = None
        self._poll_collector = monitor.collector      # what "live feed off" goes back to
        self._poll_pause = monitor.pause_between

        root.title("BGP LookingGlass" + ("  [DEMO DATA]" if demo else ""))
        root.geometry("1280x820")
        root.minsize(900, 600)
        self._fonts()
        self._style()
        self._build_toolbar()
        self._build_body()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<F1>", lambda e: self._help())
        root.after(self.POLL_MS, self._drain_queue)
        self.v_mute.set(bool(self.settings.data.get("mute_all")))
        self.v_dark.set(self._is_dark() if self.tb else bool(self.settings.data.get("dark")))
        self.v_mute.trace_add("write", lambda *a: self._save_settings())
        self._apply_theme()
        if demo:
            self.cb_live.state(["disabled"])
            self.l_live.configure(text="live feed: n/a in demo")
        elif self.settings.data.get("live"):
            self.v_live.set(True)
            self._toggle_live()
        self.root.after(1000, self._live_status)
        self._animate()

        for t in monitor.targets():
            self._list_insert(t)
        if monitor.targets():
            self._select(monitor.targets()[0])
            if autostart:
                self._toggle_run()
        self.tray = Tray(q)                          # router icon in the system tray
        if tray:
            self.tray.start()
        if minimized:
            root.iconify()

    # ------------------------------------------------------------------ setup
    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont").actual("family")
        self.f_node = tkfont.Font(family=base, size=10, weight="bold")
        self.f_sub = tkfont.Font(family=base, size=8)
        self.f_head = tkfont.Font(family=base, size=12, weight="bold")
        self.f_head2 = tkfont.Font(family="monospace", size=10)
        self.f_mono = tkfont.Font(family="monospace", size=9)
        self.f_legend = tkfont.Font(family=base, size=9)
        # map fonts scale with zoom, so they are separate objects
        self.m_node = tkfont.Font(family=base, size=10, weight="bold")
        self.m_sub = tkfont.Font(family=base, size=8)

    def _bs(self, name: str) -> dict:
        """bootstyle=... keyword for ttkbootstrap widgets (nothing on plain ttk)."""
        return {"bootstyle": name} if self.tb else {}

    def _style(self):
        if self.tb:
            self.root.style.configure("Treeview", rowheight=26)
            return
        st = ttk.Style()
        if "clam" in st.theme_names():
            st.theme_use("clam")
        st.configure("Treeview", rowheight=24)
        st.configure("Run.TButton", foreground="#1d5a28")
        st.configure("Stop.TButton", foreground="#7a1a1a")

    LOGO = Path(__file__).resolve().parent / "assets" / "logo.jpeg"

    def _load_logo(self, height: int):
        """The logo scaled to `height` px (also used as the window icon); None without Pillow/file."""
        try:
            from PIL import Image, ImageTk
            img = Image.open(self.LOGO).convert("RGB")
            w = round(img.width * height / img.height)
            logo = ImageTk.PhotoImage(img.resize((w, height), Image.LANCZOS), master=self.root)
            icon = ImageTk.PhotoImage(img.resize((64, round(64 * img.height / img.width)), Image.LANCZOS),
                                      master=self.root)
            self.root.iconphoto(True, icon)
            self._icon = icon
            return logo
        except Exception:                      # no Pillow, missing/corrupt file: plain text title
            return None

    def _build_toolbar(self):
        head = ttk.Frame(self.root, padding=(8, 6, 8, 0))
        head.pack(fill="x")
        self._logo = self._load_logo(height=60)
        if self._logo:
            ttk.Label(head, image=self._logo).pack(side="left")
        else:
            ttk.Label(head, text="BGP LookingGlass", font=("TkDefaultFont", 14, "bold")).pack(side="left")
        ttk.Button(head, text="?  Help", command=self._help,
                   **self._bs("info-outline")).pack(side="right", padx=(10, 0))
        self.v_rpki = tk.BooleanVar(value=self.monitor.rpki is not None
                                    and bool(self.settings.data.get("rpki", True)))
        self.monitor.rpki = self._rpki_checker() if self.v_rpki.get() else None
        ttk.Checkbutton(head, text="RPKI", variable=self.v_rpki, command=self._toggle_rpki,
                        **self._bs("round-toggle")).pack(side="left", padx=(20, 0))
        self.v_dark = tk.BooleanVar(value=False)
        if self.tb:
            self.v_theme = tk.StringVar(value=self.root.style.theme.name)
            cb = ttk.Combobox(head, textvariable=self.v_theme, state="readonly", width=16,
                              values=sorted(self.root.style.theme_names()))
            cb.pack(side="right")
            cb.bind("<<ComboboxSelected>>", lambda e: self._pick_theme())
            ttk.Label(head, text="Theme:").pack(side="right", padx=(14, 4))
            ttk.Checkbutton(head, text="🌙 Dark", variable=self.v_dark, command=self._toggle_dark,
                            **self._bs("round-toggle")).pack(side="right", padx=(0, 14))
        else:
            ttk.Checkbutton(head, text="🌙 dark", variable=self.v_dark,
                            command=self._toggle_dark).pack(side="right")
        self.b_live = ttk.Button(head, text="⏪ Exit replay → live", command=self._back_to_live,
                                 **self._bs("primary"))          # shown only while replaying
        bar = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        bar.pack(fill="x")
        ttk.Label(bar, text="IP / prefix:").pack(side="left")
        self.e_targets = ttk.Entry(bar, width=42)
        self.e_targets.pack(side="left", padx=4)
        self.e_targets.insert(0, "")
        self.e_targets.bind("<Return>", lambda e: self._add_from_entry())
        ttk.Button(bar, text="Add", command=self._add_from_entry, **self._bs("primary")).pack(side="left")
        ttk.Button(bar, text="Load file…", command=self._load_file, **self._bs("secondary-outline")).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Save list…", command=self._save_list, **self._bs("secondary-outline")).pack(side="left", padx=(4, 12))
        self.b_run = ttk.Button(bar, text="▶ Start", style=self.sty_run, command=self._toggle_run)
        self.b_run.pack(side="left")
        ttk.Button(bar, text="↻ Check now", command=self.monitor.check_now, **self._bs("info-outline")).pack(side="left", padx=4)
        ttk.Button(bar, text="✔ Acknowledge", command=self._ack, **self._bs("warning-outline")).pack(side="left")
        self.l_status = ttk.Label(head, text="Stopped", foreground="#666")
        self.l_status.pack(side="right", padx=(0, 12))

        bar2 = ttk.Frame(self.root, padding=(8, 2, 8, 6))
        bar2.pack(fill="x")
        ttk.Label(bar2, text="Interval (s):").pack(side="left")
        self.v_interval = tk.StringVar(value=str(self.monitor.interval))
        sp = ttk.Spinbox(bar2, from_=10, to=3600, increment=10, width=6,
                         textvariable=self.v_interval, command=self._apply_interval)
        sp.pack(side="left", padx=(2, 12))
        sp.bind("<Return>", lambda e: self._apply_interval())
        sp.bind("<FocusOut>", lambda e: self._apply_interval())

        ttk.Label(bar2, text="Best path =").pack(side="left")
        self.v_mode = tk.StringVar(value=self.monitor.mode)
        cb = ttk.Combobox(bar2, textvariable=self.v_mode, values=["consensus", "peer"],
                          state="readonly", width=10)
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_mode())
        ttk.Label(bar2, text="Vantage peer:").pack(side="left", padx=(8, 0))
        self.v_vantage = tk.StringVar(value=self.monitor.vantage)
        self.cb_vantage = ttk.Combobox(bar2, textvariable=self.v_vantage, width=22, state="readonly")
        self.cb_vantage.pack(side="left", padx=2)
        self.cb_vantage.bind("<<ComboboxSelected>>", lambda e: self._apply_mode())

        ttk.Label(bar2, text="Paths shown:").pack(side="left", padx=(12, 0))
        self.v_max = tk.StringVar(value="10")
        sp2 = ttk.Spinbox(bar2, from_=1, to=60, width=4, textvariable=self.v_max,
                          command=self._redraw)
        sp2.pack(side="left", padx=2)
        sp2.bind("<Return>", lambda e: self._redraw())

        ttk.Button(bar2, text="Export SVG…", command=self._export_svg, **self._bs("secondary-outline")).pack(side="right")
        self.v_anim = tk.BooleanVar(value=bool(self.settings.data.get("animate", True)))
        ttk.Checkbutton(bar2, text="Animate", variable=self.v_anim, command=self._toggle_anim,
                        **self._bs("round-toggle")).pack(side="left", padx=(14, 0))
        ttk.Label(bar, text="New path blue:").pack(side="left", padx=(14, 0))
        self.v_hl = tk.StringVar(value=str(self.settings.data.get("hl_value", 60)))
        self.v_hl_unit = tk.StringVar(value=self.settings.data.get("hl_unit", "sec"))
        sp3 = ttk.Spinbox(bar, from_=0, to=9999, width=4, textvariable=self.v_hl,
                          command=self._save_settings)
        sp3.pack(side="left", padx=2)
        sp3.bind("<FocusOut>", lambda e: self._save_settings())
        cb3 = ttk.Combobox(bar, textvariable=self.v_hl_unit, values=("sec", "min"), width=4, state="readonly")
        cb3.pack(side="left")
        cb3.bind("<<ComboboxSelected>>", lambda e: self._save_settings())
        self.v_live = tk.BooleanVar(value=False)
        self.cb_live = ttk.Checkbutton(bar2, text="⚡ Live feed", variable=self.v_live,
                                       command=self._toggle_live, **self._bs("round-toggle"))
        self.cb_live.pack(side="left", padx=(14, 4))
        self.l_live = ttk.Label(head, text="", foreground="#2e7d32")
        self.l_live.pack(side="right", padx=(0, 14))
        ttk.Button(bar2, text="Fit", width=4, command=self._fit, **self._bs("secondary-outline")).pack(side="right", padx=2)
        ttk.Button(bar2, text="−", width=3, command=lambda: self._zoom_by(1 / 1.2), **self._bs("secondary-outline")).pack(side="right")
        ttk.Button(bar2, text="+", width=3, command=lambda: self._zoom_by(1.2), **self._bs("secondary-outline")).pack(side="right")

    def _build_body(self):
        outer = ttk.PanedWindow(self.root, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ---- left: targets -------------------------------------------------
        left = ttk.Frame(outer, width=200)
        ttk.Label(left, text="Targets", font=self.f_node).pack(anchor="w", pady=(0, 4))
        self.tv_targets = ttk.Treeview(left, show="tree", selectmode="browse", height=12)
        self.tv_targets.pack(fill="both", expand=True)
        for s in ("ok", "changed", "error", "pending", "violation", "rpki"):
            self.tv_targets.tag_configure(s, foreground=HEADER_FG[s], background=HEADER_BG[s]
                                          if s == "changed" else "")
        self.tv_targets.bind("<<TreeviewSelect>>", self._on_select)
        ttk.Button(left, text="Rules…", command=self._edit_rules, **self._bs("secondary-outline")).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="Remove selected", command=self._remove, **self._bs("danger-outline")).pack(fill="x", pady=(4, 0))
        self.menu = tk.Menu(self.root, tearoff=False)
        self.v_tmute = tk.BooleanVar(value=False)
        self.menu.add_command(label="Expected-path rules…", command=self._edit_rules)
        self.menu.add_checkbutton(label="🔕 Mute alerts for this target", variable=self.v_tmute,
                                  command=self._toggle_target_mute)
        self.menu.add_separator()
        self.menu.add_command(label="Remove", command=self._remove)
        self.tv_targets.bind("<Button-3>", self._target_menu)
        outer.add(left, weight=0)

        # ---- right: map/table + log ---------------------------------------
        right = ttk.PanedWindow(outer, orient="vertical")
        outer.add(right, weight=1)

        nb = ttk.Notebook(right)
        self.nb = nb
        right.add(nb, weight=4)

        # map tab
        mapf = ttk.Frame(nb)
        nb.add(mapf, text="  Path map  ")
        self.header = tk.Label(mapf, text="Add an IP address to start", anchor="w", justify="left",
                               font=self.f_head, padx=10, pady=6, bg=HEADER_BG["pending"],
                               fg=HEADER_FG["pending"])
        self.header.pack(fill="x")
        self.header2 = tk.Label(mapf, text="", anchor="w", justify="left", font=self.f_head2,
                                padx=10, pady=4, bg=HEADER_BG["pending"], fg="#333")
        self.header2.pack(fill="x")
        self._legend(mapf)
        cf = ttk.Frame(mapf)
        cf.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(cf, bg="#ffffff", highlightthickness=0)
        xs = ttk.Scrollbar(cf, orient="horizontal", command=self.canvas.xview)
        ys = ttk.Scrollbar(cf, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        cf.rowconfigure(0, weight=1)
        cf.columnconfigure(0, weight=1)
        c = self.canvas
        c.bind("<ButtonPress-1>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B1-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<Control-MouseWheel>", lambda e: self._zoom_by(1.1 if e.delta > 0 else 1 / 1.1))
        c.bind("<Control-Button-4>", lambda e: self._zoom_by(1.1))
        c.bind("<Control-Button-5>", lambda e: self._zoom_by(1 / 1.1))
        c.bind("<MouseWheel>", lambda e: c.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Shift-MouseWheel>", lambda e: c.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Button-4>", lambda e: c.yview_scroll(-1, "units"))
        c.bind("<Button-5>", lambda e: c.yview_scroll(1, "units"))
        c.bind("<Configure>", lambda e: self._center_hint())

        # paths tab
        tabf = ttk.Frame(nb)
        nb.add(tabf, text="  Paths table  ")
        cols = ("role", "collector", "peer", "peer_as", "location", "prefix", "path")
        self.tv_paths = ttk.Treeview(tabf, columns=cols, show="headings")
        for col, w, txt in (("role", 110, "Role"), ("collector", 70, "Collector"),
                            ("peer", 150, "Peer IP"), ("peer_as", 80, "Peer AS"),
                            ("location", 140, "Location"), ("prefix", 120, "Prefix"),
                            ("path", 420, "AS path")):
            self.tv_paths.heading(col, text=txt)
            self.tv_paths.column(col, width=w, stretch=(col == "path"))
        self.tv_paths.tag_configure("best", background="#e3f4e1", foreground="#1d5a28")
        self.tv_paths.tag_configure("changed", background="#dcebff", foreground="#0b3a7a")
        self.tv_paths.tag_configure("previous", foreground="#777777")
        ys2 = ttk.Scrollbar(tabf, orient="vertical", command=self.tv_paths.yview)
        self.tv_paths.configure(yscrollcommand=ys2.set)
        self.tv_paths.pack(side="left", fill="both", expand=True)
        ys2.pack(side="right", fill="y")

        self._build_history_tab(nb)
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_history())

        # log pane
        logf = ttk.Frame(right)
        right.add(logf, weight=1)
        top = ttk.Frame(logf)
        top.pack(fill="x")
        ttk.Label(top, text="Event log", font=self.f_node).pack(side="left")
        self.v_showalt = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="show alternate-path churn", variable=self.v_showalt).pack(side="left", padx=10)
        self.v_mute = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="🔇 mute alert sound", variable=self.v_mute, **self._bs("round-toggle")).pack(side="left", padx=10)
        self.v_notify = tk.BooleanVar(value=bool(self.alerter.notify_enabled)
                                      and bool(self.settings.data.get("notify", True)))
        self.alerter.notify_enabled = self.v_notify.get()
        cb_n = ttk.Checkbutton(top, text="🔔 desktop notifications", variable=self.v_notify,
                               command=self._toggle_notify, **self._bs("round-toggle"))
        cb_n.pack(side="left", padx=10)
        if not self.alerter.notify_cmd:                    # notify-send is not installed
            self.v_notify.set(False)
            self.alerter.notify_enabled = False
            cb_n.state(["disabled"])
        ttk.Button(top, text="Clear", command=lambda: self.t_log.delete("1.0", "end"), **self._bs("secondary-outline")).pack(side="right")
        logbody = ttk.Frame(logf)
        logbody.pack(fill="both", expand=True)
        self.t_log = tk.Text(logbody, height=8, font=self.f_mono, wrap="none", bg="#fafaf8")
        ys_log = ttk.Scrollbar(logbody, orient="vertical", command=self.t_log.yview)
        xs_log = ttk.Scrollbar(logbody, orient="horizontal", command=self.t_log.xview)
        self.t_log.configure(yscrollcommand=ys_log.set, xscrollcommand=xs_log.set)
        ys_log.pack(side="right", fill="y")
        xs_log.pack(side="bottom", fill="x")
        self.t_log.pack(side="left", fill="both", expand=True)
        self.t_log.tag_configure("alert", foreground="#b31d1d")
        self.t_log.tag_configure("error", foreground="#8a5a00")
        self.t_log.tag_configure("info", foreground="#777777")
        self.t_log.tag_configure("first", foreground="#1d5a28")

    def _legend(self, parent):
        lg = tk.Canvas(parent, height=26, bg="#ffffff", highlightthickness=0)
        self.legend_canvas = lg
        lg.pack(fill="x")
        x = 12
        for status, text in (("best", "best path (stable)"), ("changed", "new best path (blinks, then green)"),
                             ("previous", "previous best path"), ("alt", "alternate paths")):
            color, width, dash = EDGE_STYLE[status]
            lg.create_line(x, 13, x + 28, 13, fill=color, width=width, dash=dash or ())
            lg.create_text(x + 34, 13, text=text, anchor="w", font=self.f_legend, fill="#444")
            x += 34 + self.f_legend.measure(text) + 24
        lg.create_text(x + 10, 13, anchor="w", font=self.f_legend, fill="#888",
                       text="drag = pan · Ctrl+wheel = zoom · hover a node for details")

    # ------------------------------------------------------------- targets
    def _list_insert(self, t: str):
        if not self.tv_targets.exists(t):
            self.tv_targets.insert("", "end", iid=t, text=f"{STATUS_ICON['pending']}  {t}{self._mute_mark(t)}",
                                   tags=("pending",))

    def _add_from_entry(self):
        good, bad = parse_targets(self.e_targets.get())
        if bad:
            messagebox.showerror("Invalid address", "Not an IP address or prefix:\n  " + "\n  ".join(bad))
        self._add_targets(good)
        if good and not bad:
            self.e_targets.delete(0, "end")

    def _add_targets(self, targets):
        added = [t for t in targets if self.monitor.add_target(t)]
        for t in added:
            self._list_insert(t)
        if added:
            self._save_settings()
            if not self.selected:
                self._select(added[0])
            if self.monitor.running:
                self.monitor.check_now()

    def _load_file(self):
        path = filedialog.askopenfilename(title="Load targets (one IP/prefix per line)",
                                          filetypes=[("Text", "*.txt *.lst *.conf"), ("All", "*")])
        if not path:
            return
        lines = [ln.split("#")[0] for ln in Path(path).read_text().splitlines()]
        good, bad = parse_targets(" ".join(lines))
        if bad:
            messagebox.showwarning("Skipped entries", "Ignored:\n  " + "\n  ".join(bad[:20]))
        self._add_targets(good)

    def _remove(self):
        t = self.selected
        if not t:
            return
        self.monitor.remove_target(t)
        if self.live:
            self.live.forget(t)
        self.monitor.rules.pop(t, None)
        self.muted_targets.discard(t)
        self.views.pop(t, None)
        self._save_settings()
        self.tv_targets.delete(t)
        self.selected = None
        rest = self.tv_targets.get_children()
        if rest:
            self._select(rest[0])
        else:
            self._redraw()

    def _select(self, t: str):
        if self.tv_targets.exists(t):
            self.tv_targets.selection_set(t)
            self.tv_targets.see(t)
        self.selected = t
        self._leave_replay()
        self._needs_fit = True
        self._redraw()
        self._refresh_history()

    def _on_select(self, _e=None):
        sel = self.tv_targets.selection()
        if sel and sel[0] != self.selected:
            self.selected = sel[0]
            self._leave_replay()
            self._needs_fit = True
            self._redraw()
            self._refresh_history()

    def _update_list_item(self, v):
        if self.tv_targets.exists(v.target):
            self.tv_targets.item(v.target, text=f"{STATUS_ICON.get(v.status, '?')}  {v.target}"
                                                f"{self._mute_mark(v.target)}", tags=(v.status,))

    # ------------------------------------------------------------- controls
    def _toggle_run(self):
        if self.monitor.running:
            self.monitor.stop()
            self.b_run.configure(text="▶ Start", style=self.sty_run)
            self.l_status.configure(text="Stopped")
        else:
            self._apply_interval()
            self.monitor.start()
            self.monitor.check_now()
            self.b_run.configure(text="■ Stop", style=self.sty_stop)

    def _ack(self):
        if self.selected:
            self.monitor.acknowledge(self.selected)

    def _apply_interval(self):
        try:
            self.monitor.set_options(interval=int(self.v_interval.get()))
        except ValueError:
            self.v_interval.set(str(self.monitor.interval))

    def _apply_mode(self):
        mode = self.v_mode.get()
        vantage = self.vantage_map.get(self.v_vantage.get(), "")
        if mode == "peer" and not vantage:
            messagebox.showinfo("Pick a vantage peer",
                                "Choose a collector/peer in 'Vantage peer'. Its route is then "
                                "treated as the best path for every target.\n\n"
                                "Until then the consensus path is used.")
        self.monitor.set_options(mode=mode, vantage=vantage if mode == "peer" else "")

    def _refresh_vantage_list(self, v):
        items = {}
        for r in sorted(v.routes, key=lambda r: (r.collector, r.peer_ip)):
            loc = f" {r.peer_location}" if r.peer_location else ""
            items[f"{r.vantage}  AS{r.peer_asn}{loc}"] = r.vantage
        self.vantage_map = items
        self.cb_vantage.configure(values=list(items))

    # ------------------------------------------------------------- tray
    def _tray_action(self, action: str):
        if action == "check":
            self.monitor.check_now()
        elif action == "toggle":
            if self.root.state() in ("withdrawn", "iconic"):
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            else:
                self.root.withdraw()

    def _update_tray(self):
        views = list(self.views.values())
        status = overall_status(views)
        words = {"ok": "all stable", "changed": "path changed", "error": "fetch error",
                 "alert": "ALERT (RPKI invalid / rule violated)", "idle": "waiting"}
        self.tray.update(status, f"{len(views)} target(s), {words[status]}")

    # ------------------------------------------------------------- queue
    def _drain_queue(self):
        redraw = False
        try:
            for _ in range(500):
                kind, payload = self.q.get_nowait()
                if kind == "view":
                    self.views[payload.target] = payload
                    self._update_list_item(payload)
                    if payload.target == self.selected:
                        redraw = True
                elif kind == "event":
                    self._on_event(payload)
                elif kind == "tray":
                    if payload == "quit":
                        self._on_close()
                        return                       # the window is gone: no more polling
                    self._tray_action(payload)
                elif kind == "status":
                    self.l_status.configure(text=payload)
                elif kind == "countdown" and self.monitor.running:
                    txt = self.l_status.cget("text").split(" · next")[0]
                    self.l_status.configure(text=f"{txt} · next poll in {payload}s")
        except queue.Empty:
            pass
        if redraw:
            self._redraw()
        self._update_tray()
        self.root.after(self.POLL_MS, self._drain_queue)

    def _on_event(self, ev):
        if ev.kind != "ALT_CHANGED" or self.v_showalt.get():
            self.alerter.handle(ev)
        else:
            self.alerter.log.info(ev.console_block())   # file only
        if ev.kind == "ALT_CHANGED" and not self.v_showalt.get():
            return
        tag = {"alert": "alert", "error": "error"}.get(ev.severity,
                                                      "first" if ev.kind == "FIRST_SEEN" else "info")
        text = ev.console_block() if ev.severity == "alert" else ev.summary()
        self.t_log.insert("end", text + "\n", tag)
        if int(self.t_log.index("end-1c").split(".")[0]) > 3000:
            self.t_log.delete("1.0", "500.0")
        self.t_log.see("end")
        if ev.severity == "alert":
            self._beep(ev.target)
        if ev.kind not in ("ALT_CHANGED", "FETCH_ERROR"):
            self._refresh_history()

    ALERT_REPEATS, ALERT_SPAN_S = 3, 10      # 3 bursts of 3 beeps, first to last 10 s apart

    def _beep(self, target: str = ""):
        """3 beeps, repeated 3 times over 10 s (t = 0, 5, 10 s) when a best path changes or a
        rule breaks, unless muted (all / this target). Muting stops the bursts still to come."""
        step = int(self.ALERT_SPAN_S * 1000 / (self.ALERT_REPEATS - 1))
        for i in range(self.ALERT_REPEATS):
            if i == 0:
                self._beep_burst(target)
            else:
                self.root.after(i * step, lambda: self._beep_burst(target))

    def _beep_burst(self, target: str = ""):
        if self.v_mute.get() or target in self.muted_targets:
            return
        if not play_alert():
            for i in range(3):
                self.root.after(i * 300, self.root.bell)

    # ------------------------------------------------------------- drawing
    def _header(self, v):
        if v is None:
            self.header.configure(text="Add an IP address to start", bg=HEADER_BG["pending"],
                                  fg=HEADER_FG["pending"])
            self.header2.configure(text="", bg=HEADER_BG["pending"], fg="#333333")
            return
        if self.hist_view is not None:
            ev = self.hist_event
            self.header.configure(
                text=f"⏪ HISTORY SNAPSHOT  │  {ev.timestamp:%Y-%m-%d %H:%M:%S}  │  "
                     f"{ev.kind.replace('_', ' ')}  │  {v.target}  │  Prefix: {v.prefix or '-'}",
                bg="#dde7f5", fg="#0c447c")
            line2 = f"Best path then:  {fmt_path(v.best_path)}"
            if v.previous_path:
                line2 += f"\nPrevious path:   {fmt_path(v.previous_path)}"
            if ev.detail:
                line2 += f"\nNote: {ev.detail}"
            self.header2.configure(text=line2, bg="#dde7f5", fg="#0c447c")
            return
        origin = v.best_path[-1] if v.best_path else (v.routes[0].origin_asn if v.routes else None)
        oname = short_name(self.names.get(origin)) if origin else ""
        status = {"ok": "STABLE", "changed": "⚠ PATH CHANGED", "error": "✖ ERROR",
                  "pending": "waiting…", "violation": "⛔ RULE VIOLATION",
                  "rpki": "⛔ RPKI INVALID"}.get(v.status, v.status)
        poll = v.last_poll.strftime("%H:%M:%S") if v.last_poll else "-"
        self.header.configure(
            text=f"Target: {v.target}    │  Prefix: {v.prefix or '-'}    │  Origin: "
                 f"{'AS%s' % origin if origin else '-'} {('(' + oname + ')') if oname else ''}    "
                 f"│  Last poll: {poll}    │  {status}",
            bg=HEADER_BG.get(v.status, "#eee"), fg=HEADER_FG.get(v.status, "#333"))
        line2 = f"Best path [{v.best_label}]:  {fmt_path(v.best_path)}"
        if v.changed and v.previous_path:
            when = v.changed_at.strftime("%H:%M:%S") if v.changed_at else ""
            line2 += f"\nPrevious (until {when}):  {fmt_path(v.previous_path)}"
        if v.rpki:
            line2 += f"\nRPKI {RPKI_SHORT.get(v.rpki, v.rpki)}" + (f": {v.rpki_detail}" if v.rpki_detail else "")
        rules = self.monitor.rules.get(v.target)
        if rules:
            line2 += f"\nRules [{rules.describe()}]:  " + \
                     ("⛔ " + "; ".join(v.violations) if v.violations else "✔ path complies")
        if v.error:
            line2 += f"\nError: {v.error}"
        self.header2.configure(text=line2, bg=HEADER_BG.get(v.status, "#eee"), fg="#333333")

    def _current_view(self):
        if self.hist_view is not None:
            return self.hist_view
        return self.views.get(self.selected) if self.selected else None

    def _redraw(self, fit: bool = False):
        v = self._current_view()
        self._header(v)
        self._fill_table(v)
        if v and self.hist_view is None:
            self._refresh_vantage_list(v)
        c = self.canvas
        c.delete("all")
        self._hide_tip()
        self._graph = None
        if v is None or not v.routes:
            msg = ("Add one or more IP addresses above (comma separated) and press Start."
                   if v is None else (v.error or "Waiting for the first poll…"))
            c.create_text(0, 0, text=msg, fill="#888", font=self.f_head, tags=("hint",))
            c.configure(scrollregion=(0, 0, 1, 1))
            self._center_hint()
            return
        try:
            maxp = max(1, int(self.v_max.get()))
        except ValueError:
            maxp = 10
        g = build_graph(v, self.names.get, maxp, short_name)
        self._graph = g
        if (fit or self._needs_fit) and self.canvas.winfo_width() > 50:
            self._fit(redraw=False)
            self._needs_fit = False
        self._draw_graph(g, v)
        self._blink_on = None
        self._build_flow(g, v)

    @staticmethod
    def _clip(font, text, maxw):
        """Shorten text with an ellipsis so it fits inside maxw pixels."""
        if font.measure(text) <= maxw:
            return text
        while text and font.measure(text + "…") > maxw:
            text = text[:-1]
        return text + "…"

    @staticmethod
    def _bezier(x1, y1, x2, y2, steps: int = 24):
        """Flattened S-curve (same shape as the SVG export): flat ends, smooth middle."""
        mx = (x1 + x2) / 2
        pts = []
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            pts += [u**3 * x1 + 3 * u * u * t * mx + 3 * u * t * t * mx + t**3 * x2,
                    u**3 * y1 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y2]
        return pts

    # ---- packets travelling along the best path (peer -> origin -> prefix -> target)
    PKT_MS, PKT_SPEED, PKT_GAP = 40, 140.0, 90.0      # frame time, px/s, px between packets

    def _rpki_checker(self):
        """The RPKI checker to use (created once; simulated in demo mode)."""
        if self.monitor.rpki is not None:
            self._rpki = self.monitor.rpki
        if getattr(self, "_rpki", None) is None:
            self._rpki = DemoRpki() if self.demo else RpkiChecker()
        return self._rpki

    def _toggle_rpki(self):
        """Switch the RPKI origin validation on or off and re-check the targets now."""
        self.monitor.rpki = self._rpki_checker() if self.v_rpki.get() else None
        self._save_settings()
        if self.monitor.running:
            self.monitor.check_now()
        else:
            for v in self.views.values():
                if not self.v_rpki.get():
                    v.rpki = v.rpki_detail = ""
            self._redraw()

    def _toggle_notify(self):
        """Desktop (notify-send) pop-ups on or off; the beeps and the logs are not affected."""
        self.alerter.notify_enabled = self.v_notify.get()
        self._save_settings()

    def _toggle_anim(self):
        self._save_settings()
        self._redraw()

    def _build_flow(self, g, v):
        """Polyline of the whole best path in canvas pixels, or None."""
        self._flow, self._pkts = None, []
        if not v or not v.best_path or not self.v_anim.get() or self.hist_view is not None:
            return
        z, nw = self.zoom, NODE_W * self.zoom
        chain = [f"AS{a}" for a in collapse_prepends(v.best_path)] + ["PFX", "TGT"]
        pts: list = []
        for a, b in zip(chain, chain[1:]):
            if (a, b) not in g.edges:
                return
            na, nb = g.nodes[a], g.nodes[b]
            seg = self._bezier(na.x * z + nw / 2, na.y * z, nb.x * z - nw / 2, nb.y * z)
            pts += seg if not pts else seg[2:]
            # hop through the node box so the packet does not jump at the boundary
            pts += [nb.x * z + nw / 2, nb.y * z] if b != "TGT" else []
        xy = list(zip(pts[0::2], pts[1::2]))
        cum = [0.0]
        for (xa, ya), (xb, yb) in zip(xy, xy[1:]):
            cum.append(cum[-1] + ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5)
        if cum[-1] < 10:
            return
        self._flow = (xy, cum)
        n = max(2, int(cum[-1] / (self.PKT_GAP * z)))
        r = 4 * z
        color = NEW_BLUE if v.changed else GREEN
        self._pkts = [(self.canvas.create_oval(0, 0, 0, 0, fill="#ffffff", outline=color,
                                               width=max(1.5, 2 * z), tags=("pkt",)), i / n)
                      for i in range(n)]
        self._pkt_r = r
        self._pkt_t0 = time.monotonic()

    def _hl_number(self) -> int:
        try:
            return max(0, int(self.v_hl.get()))
        except ValueError:
            return 60

    def _hl_seconds(self) -> int:
        """How long a new best path stays blue; 0 = until acknowledged."""
        return self._hl_number() * (60 if self.v_hl_unit.get() == "min" else 1)

    def _expire_highlights(self):
        limit = self._hl_seconds()
        if not limit:
            return
        now = datetime.now()
        for t, v in list(self.views.items()):
            if v.changed and v.changed_at and (now - v.changed_at).total_seconds() >= limit:
                self.monitor.acknowledge(t)         # -> view update -> redraws green

    def _blink(self):
        on = int(time.monotonic() * 2.5) % 2 == 0
        if on == self._blink_on:
            return
        self._blink_on = on
        c = self.canvas
        for item in c.find_withtag("chg_edge"):
            c.itemconfigure(item, fill=NEW_BLUE if on else "#a9d0ff")
        for item in c.find_withtag("chg_node"):
            c.itemconfigure(item, fill="#dcebff" if on else "#ffffff",
                            outline=NEW_BLUE if on else "#a9d0ff")

    def _animate(self):
        self._anim_id = None
        self._blink()
        now = time.monotonic()
        if now - self._hl_check >= 1.0:
            self._hl_check = now
            self._expire_highlights()
        if self._flow and self._pkts and self.v_anim.get():
            xy, cum = self._flow
            total = cum[-1]
            shift = (time.monotonic() - self._pkt_t0) * self.PKT_SPEED * self.zoom / total
            r, c, j = self._pkt_r, self.canvas, 0
            for item, off in self._pkts:
                d = ((off + shift) % 1.0) * total
                while j + 1 < len(cum) - 1 and cum[j + 1] < d:
                    j += 1
                while j > 0 and cum[j] > d:
                    j -= 1
                seg = cum[j + 1] - cum[j] or 1.0
                f = min(max((d - cum[j]) / seg, 0.0), 1.0)
                x = xy[j][0] + (xy[j + 1][0] - xy[j][0]) * f
                y = xy[j][1] + (xy[j + 1][1] - xy[j][1]) * f
                c.coords(item, x - r, y - r, x + r, y + r)
                c.tag_raise(item)
        self._anim_id = self.root.after(self.PKT_MS, self._animate)

    @staticmethod
    def _clip_mid(font, text, maxw):
        """IPv6: keep both ends ('2001:4860…:8888/128'), the full address is in the tooltip."""
        if font.measure(text) <= maxw:
            return text
        head, tail = len(text) // 2, len(text) // 2
        while head > 2 and font.measure(text[:head] + "…" + text[len(text) - tail:]) > maxw:
            head -= 1
            tail = max(tail - (head % 2), 3)
        return text[:head] + "…" + text[len(text) - tail:]

    def _draw_graph(self, g, v):
        c, z = self.canvas, self.zoom
        self.m_node.configure(size=max(8, int(round(10 * z))))
        self.m_sub.configure(size=max(7, int(round(8 * z))))
        nw, nh = NODE_W * z, NODE_H * z
        for e in sorted(g.edges.values(), key=lambda e: RANK[e.status]):
            a, b = g.nodes[e.a], g.nodes[e.b]
            x1, y1 = a.x * z + nw / 2, a.y * z
            x2, y2 = b.x * z - nw / 2, b.y * z
            color, width, dash = EDGE_STYLE[e.status]
            if e.status == "alt":
                width = 1 + min(e.weight, 30) / 10          # thicker = more peers
            c.create_line(*self._bezier(x1, y1, x2, y2),
                          fill=color, width=max(1, width * z), dash=dash or (),
                          tags=("chg_edge",) if e.status == "changed" else (),
                          arrow="last" if e.status in ("best", "changed") else None,
                          arrowshape=(8 * z, 10 * z, 4 * z), capstyle="round")
        for n in g.nodes.values():
            fill, outline, text = node_colors(n.kind, n.status)
            bad_origin = (n.kind == "origin" and v.rpki.startswith("invalid")
                          and n.status in ("best", "changed"))
            if bad_origin:
                fill, outline, text = "#fde3e3", RED, "#7a1a1a"       # RPKI-invalid origin: no blinking
            x, y = n.x * z, n.y * z
            tag = f"node:{n.key}"
            c.create_rectangle(x - nw / 2, y - nh / 2, x + nw / 2, y + nh / 2, fill=fill,
                               outline=outline, width=(2.5 if n.status in ("best", "changed") else 1) * max(z, .6),
                               tags=(tag, "node") + (("chg_node",) if n.status == "changed" and n.kind != "target" and not bad_origin else ()))
            maxw = nw - 8 * z
            font = self.m_node
            if font.measure(n.label) > maxw and self.m_sub.measure(n.label) <= maxw:
                font = self.m_sub                      # long IPv6 address: smaller type instead of "…"
            label = self._clip_mid(font, n.label, maxw) if ":" in n.label else self._clip(font, n.label, maxw)
            if n.sub:
                c.create_text(x, y - 7 * z, text=label, font=font, fill=text, tags=(tag, "node"))
                c.create_text(x, y + 9 * z, text=self._clip(self.m_sub, n.sub, maxw), font=self.m_sub,
                              fill=text, tags=(tag, "node"))
            else:
                c.create_text(x, y, text=label, font=self.m_node, fill=text, tags=(tag, "node"))
            c.tag_bind(tag, "<Enter>", lambda e, n=n: self._show_tip(e, n, v))
            c.tag_bind(tag, "<Leave>", lambda e: self._hide_tip())
        # column captions
        cols = {}
        for n in g.nodes.values():
            cols.setdefault(n.col, []).append(n)
        maxcol = max(cols)
        for col, ns in cols.items():
            kinds = {n.kind for n in ns}
            cap = ("target IP" if "target" in kinds else "prefix" if "prefix" in kinds else
                   "origin AS" if kinds == {"origin"} else
                   "vantage peers" if col == maxcol else "transit")
            c.create_text(ns[0].x * z, 12, text=cap, fill="#999", font=self.f_legend)
        note = f"{g.shown_paths} of {g.total_paths} distinct paths shown · {len(v.routes)} peers"
        c.create_text(8, g.height * z + 14, text=note, anchor="w", fill="#999", font=self.f_legend)
        c.configure(scrollregion=(0, 0, g.width * z + 20, g.height * z + 30))

    def _center_hint(self):
        items = self.canvas.find_withtag("hint")
        if items:
            self.canvas.coords(items[0], self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    def _fit(self, redraw: bool = True):
        g = self._graph
        if not g or not g.width:
            return
        cw = max(self.canvas.winfo_width(), 400)
        ch = max(self.canvas.winfo_height(), 300)
        self.zoom = max(0.8, min(1.6, (cw - 20) / g.width, (ch - 30) / g.height))
        if redraw:
            self._redraw()

    def _zoom_by(self, f: float):
        self.zoom = max(0.3, min(3.0, self.zoom * f))
        self._redraw()

    # tooltip drawn on the canvas itself (no extra toplevel windows)
    def _show_tip(self, event, n, v):
        self._hide_tip()
        if n.kind == "target":
            lines = [f"Target {v.target}", f"Covered by {v.prefix}", f"{len(v.routes)} peers report a route"]
        elif n.kind == "prefix":
            lines = [f"Prefix {n.label}", "Most specific route seen by the peers"]
        else:
            holder = self.names.get(n.asn) or "(name unknown)"
            through = sum(1 for r in v.routes if n.asn in r.as_path)
            role = {"peer": "vantage peer", "transit": "transit", "origin": "origin AS"}[n.kind]
            lines = [f"AS{n.asn}  {holder}", f"Role: {role}",
                     f"In {through} of {len(v.routes)} peers' paths"]
            if v.rpki and v.best_path and n.asn == v.best_path[-1]:
                lines.append("RPKI: " + RPKI_LABELS.get(v.rpki, v.rpki))
            if v.best_path and n.asn in v.best_path:
                lines.append("On the BEST path" + (" (new)" if v.changed else ""))
            elif v.previous_path and n.asn in v.previous_path and v.changed:
                lines.append("Was on the PREVIOUS best path")
        c = self.canvas
        x, y = c.canvasx(event.x) + 14, c.canvasy(event.y) + 14
        t = c.create_text(x + 8, y + 6, text="\n".join(lines), anchor="nw", font=self.f_mono,
                          fill="#222", tags=("tip",))
        x1, y1, x2, y2 = c.bbox(t)
        r = c.create_rectangle(x1 - 8, y1 - 6, x2 + 8, y2 + 6, fill="#fffbe6", outline="#c9b46b",
                               tags=("tip",))
        c.tag_lower(r, t)

    def _hide_tip(self):
        self.canvas.delete("tip")

    def _fill_table(self, v):
        tv = self.tv_paths
        tv.delete(*tv.get_children())
        if not v:
            return
        best_vantage = v.best.vantage if v.best else None
        rows = []
        for r in v.routes:
            if r.vantage == best_vantage:
                role = "NEW BEST" if v.changed else "BEST"
                tag = "changed" if v.changed else "best"
            elif r.as_path == v.best_path:
                role, tag = "same as best", "best" if not v.changed else "changed"
            else:
                role, tag = "alternate", ""
            rows.append((0 if role.endswith("BEST") else 1 if role == "same as best" else 2,
                         (role, r.collector, r.peer_ip, f"AS{r.peer_asn}", r.peer_location,
                          r.prefix, fmt_path(r.as_path)), tag))
        if v.changed and v.previous_path:
            rows.append((0.5, ("PREVIOUS", "", "", "", "", v.prefix, fmt_path(v.previous_path)), "previous"))
        for _, values, tag in sorted(rows, key=lambda x: (x[0], x[1][6])):
            tv.insert("", "end", values=values, tags=(tag,) if tag else ())

    # ------------------------------------------------------------- rules / mute / settings
    def _mute_mark(self, t: str) -> str:
        return "  🔕" if t in self.muted_targets else ""

    def _save_settings(self):
        d = self.settings.data
        d["targets"] = self.monitor.targets()
        d["rules"] = {t: r.to_dict() for t, r in self.monitor.rules.items()}
        d["muted"] = sorted(self.muted_targets)
        d["mute_all"] = bool(self.v_mute.get())
        d["dark"] = bool(self.v_dark.get())
        d["animate"] = bool(self.v_anim.get())
        d["rpki"] = bool(self.v_rpki.get())
        d["notify"] = bool(self.v_notify.get())
        d["hl_value"] = self._hl_number()
        d["hl_unit"] = self.v_hl_unit.get()
        if self.tb:
            d["theme"] = self.root.style.theme.name
        d["live"] = self.live is not None
        self.settings.save()

    def _edit_rules(self):
        t = self.selected
        if not t:
            messagebox.showinfo("Rules", "Select a target first.")
            return
        res = edit_rules(self.root, t, self.monitor.rules.get(t), len(self.monitor.targets()))
        if res is None:
            return
        rules, to_all = res
        for tgt in (self.monitor.targets() if to_all else [t]):
            self.monitor.set_rules(tgt, rules)
        self._save_settings()
        self.l_status.configure(text=f"Rules for {t}: {rules.describe()}")
        self._redraw()

    def _target_menu(self, event):
        iid = self.tv_targets.identify_row(event.y)
        if not iid:
            return
        self.tv_targets.selection_set(iid)
        self._select(iid)
        self.v_tmute.set(iid in self.muted_targets)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _toggle_target_mute(self):
        t = self.selected
        if not t:
            return
        if self.v_tmute.get():
            self.muted_targets.add(t)
        else:
            self.muted_targets.discard(t)
        v = self.views.get(t)
        if v:
            self._update_list_item(v)
        elif self.tv_targets.exists(t):
            self.tv_targets.item(t, text=f"{STATUS_ICON['pending']}  {t}{self._mute_mark(t)}")
        self._save_settings()

    def _save_list(self):
        targets = self.monitor.targets()
        if not targets:
            messagebox.showinfo("Save list", "There are no targets to save.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="targets.txt",
                                            filetypes=[("Text", "*.txt"), ("All", "*")])
        if path:
            Path(path).write_text("# BGP LookingGlass targets\n" + "\n".join(targets) + "\n",
                                  encoding="utf-8")

    # ------------------------------------------------------------- help
    def _help(self):
        win = getattr(self, "_help_win", None)
        if win is not None and win.win.winfo_exists():
            win.win.lift()
            win.win.focus_set()
            return
        self._help_win = HelpWindow(self.root, self.pal, self._is_dark())

    # ------------------------------------------------------------- live feed
    def _toggle_live(self):
        if self.v_live.get() and self.live is None:
            self.live = LiveCollector(self._poll_collector, on_update=lambda t: self.monitor.check_now())
            self.monitor.collector = self.live
            self.monitor.pause_between = 0            # reading memory, nothing to be polite about
            self.l_status.configure(text="Live feed on: seeding from RIPEstat, then following RIS Live…")
        elif not self.v_live.get() and self.live is not None:
            self.live.close()
            self.live = None
            self.monitor.collector = self._poll_collector
            self.monitor.pause_between = self._poll_pause
            self.l_live.configure(text="")
        self._save_settings()
        self.monitor.check_now()

    def _live_status(self):
        if self.live is not None:
            self.l_live.configure(text=self.live.status())
        self.root.after(1000, self._live_status)

    # ------------------------------------------------------------- dark theme
    def _toggle_dark(self):
        """Dark / light switch. With ttkbootstrap it jumps to the other variant of the current
        theme (nord-light <-> nord-dark); on plain Tk it flips the built-in palette."""
        if self.tb:
            if self.v_dark.get() != self._is_dark():
                cur = self.root.style.theme.name
                other = counterpart_theme(cur, set(self.root.style.theme_names()))
                if other == cur:                      # a theme without a pair
                    other = "bootstrap-dark" if self.v_dark.get() else "bootstrap-light"
                self.v_theme.set(other)
                self._pick_theme()
            return
        self._apply_theme()
        self._save_settings()
        self._redraw()

    def _pick_theme(self):
        self.root.style.theme_use(self.v_theme.get())
        self.v_dark.set(self._is_dark())              # keep the switch in step with the dropdown
        self._apply_theme()
        self._save_settings()
        self._redraw()
        self._refresh_history()

    def _is_dark(self) -> bool:
        if self.tb:
            theme = self.root.style.theme
            return (getattr(theme, "mode", None) or theme.type) == "dark"
        return bool(self.v_dark.get())

    def _theme_palette(self) -> dict:
        """Colours for the plain-tk widgets (canvas, log, timeline) taken from the active theme."""
        c = self.root.style.colors
        mode = getattr(self.root.style.theme, "mode", None) or self.root.style.theme.type
        dark = mode == "dark"
        return dict(bg=c.bg, panel=c.inputbg, fg=c.fg, dim="#9a9a9a" if dark else "#666666",
                    field=c.inputbg, sel=c.selectbg, canvas=c.inputbg, log=c.inputbg,
                    legend=c.fg)

    def _apply_theme(self):
        if self.tb:
            pal = self.pal = self._theme_palette()
            st = None
        else:
            pal = self.pal = DARK if self.v_dark.get() else LIGHT
            st = ttk.Style()
        if st is not None:
            st.configure(".", background=pal["bg"], foreground=pal["fg"], fieldbackground=pal["field"],
                         bordercolor=pal["dim"], lightcolor=pal["bg"], darkcolor=pal["bg"],
                         troughcolor=pal["bg"], insertcolor=pal["fg"])
            st.configure("Treeview", background=pal["panel"], fieldbackground=pal["panel"],
                         foreground=pal["fg"])
            st.map("Treeview", background=[("selected", pal["sel"])],
                   foreground=[("selected", "#ffffff")])
            st.configure("Treeview.Heading", background=pal["bg"], foreground=pal["fg"])
            st.configure("TNotebook", background=pal["bg"])
            st.configure("TNotebook.Tab", background=pal["bg"], foreground=pal["fg"])
            st.map("TNotebook.Tab", background=[("selected", pal["panel"])])
            st.configure("TEntry", fieldbackground=pal["field"], foreground=pal["fg"])
            st.configure("TCombobox", fieldbackground=pal["field"], foreground=pal["fg"],
                         background=pal["bg"], arrowcolor=pal["fg"])
            st.map("TCombobox", fieldbackground=[("readonly", pal["field"])],
                   foreground=[("readonly", pal["fg"])])
            st.configure("TSpinbox", fieldbackground=pal["field"], foreground=pal["fg"],
                         arrowcolor=pal["fg"])
            st.configure("TButton", background=pal["bg"], foreground=pal["fg"])
            st.map("TButton", background=[("active", pal["sel"])], foreground=[("disabled", pal["dim"])])
            st.configure("TCheckbutton", background=pal["bg"], foreground=pal["fg"])
            st.configure("TLabel", background=pal["bg"], foreground=pal["fg"])
            st.configure("Run.TButton", foreground="#2e9e44")
            st.configure("Stop.TButton", foreground="#d93636")
        if not self.tb:
            self.root.configure(background=pal["bg"])
        self.canvas.configure(bg=pal["canvas"])
        self.legend_canvas.configure(bg=pal["canvas"])
        for item in self.legend_canvas.find_all():
            if self.legend_canvas.type(item) == "text":
                self.legend_canvas.itemconfigure(item, fill=pal["legend"])
        self.t_log.configure(bg=pal["log"], fg=pal["fg"], insertbackground=pal["fg"])
        dark = self._is_dark()
        for tag, light, dk in (("alert", "#b31d1d", "#ff7b7b"), ("error", "#8a5a00", "#e8b85a"),
                               ("info", "#777777", "#a0a0a0"), ("first", "#1d5a28", "#6fd48a")):
            self.t_log.tag_configure(tag, foreground=dk if dark else light)
        # target list: bright text on a dark background; the "changed" row keeps its pale-blue band
        for s, dk in (("ok", "#6fd48a"), ("pending", "#cfcfcf"), ("error", "#e8b85a"),
                      ("violation", "#ff8a8a"), ("rpki", "#ff8a8a")):
            self.tv_targets.tag_configure(s, foreground=dk if dark else HEADER_FG[s])
        self.tl_canvas.configure(bg=pal["panel"])
        self.l_status.configure(foreground=pal["dim"])
        self.root.option_add("*TCombobox*Listbox.background", pal["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
        self.menu.configure(background=pal["panel"], foreground=pal["fg"])

    # ------------------------------------------------------------- history tab
    KIND_COLORS = {"BEST_CHANGED": "#d93636", "ORIGIN_CHANGED": "#8b1a1a", "PREFIX_CHANGED": "#d93636",
                   "BEST_LOST": "#8b1a1a", "BEST_RESTORED": "#2e9e44", "FIRST_SEEN": "#2e9e44",
                   "RULE_VIOLATION": "#e07b00", "RULE_RESTORED": "#2e9e44",
                   "RPKI_INVALID": "#b00020", "RPKI_RESTORED": "#2e9e44"}

    def _build_history_tab(self, nb):
        hf = ttk.Frame(nb)
        nb.add(hf, text="  History  ")
        self._hist_tab = nb.index("end") - 1
        bar = ttk.Frame(hf, padding=(4, 4))
        bar.pack(fill="x")
        self.v_hist_sel = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="selected target only", variable=self.v_hist_sel,
                        command=self._refresh_history).pack(side="left")
        self.l_hist = ttk.Label(bar, text="")
        self.l_hist.pack(side="left", padx=12)
        ttk.Button(bar, text="Clear history…", command=self._clear_history, **self._bs("danger-outline")).pack(side="right")
        ttk.Button(bar, text="⏪ Show map at that time", command=self._show_snapshot, **self._bs("primary")).pack(side="right", padx=6)
        self.tl_canvas = tk.Canvas(hf, height=62, bg="#ffffff", highlightthickness=0)
        self.tl_canvas.pack(fill="x", padx=4)
        self.tl_canvas.bind("<Configure>", lambda e: self._draw_timeline())
        self.tl_canvas.bind("<Button-1>", self._timeline_click)
        cols = ("time", "target", "event", "previous", "new", "note")
        body = ttk.Frame(hf)
        body.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self.tv_hist = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for col, w, txt in (("time", 140, "Time"), ("target", 110, "Target"), ("event", 130, "Event"),
                            ("previous", 200, "Previous path"), ("new", 200, "New path"),
                            ("note", 300, "Note")):
            self.tv_hist.heading(col, text=txt)
            self.tv_hist.column(col, width=w, stretch=(col == "note"))
        for kind, color in self.KIND_COLORS.items():
            self.tv_hist.tag_configure(kind, foreground=color)
        ys = ttk.Scrollbar(body, orient="vertical", command=self.tv_hist.yview)
        self.tv_hist.configure(yscrollcommand=ys.set)
        self.tv_hist.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tv_hist.bind("<Double-1>", lambda e: self._show_snapshot())
        self.tv_hist.bind("<<TreeviewSelect>>", lambda e: self._draw_timeline())

    def _refresh_history(self):
        if not hasattr(self, "tv_hist"):
            return
        if self.nb.index("current") != self._hist_tab:
            return                                  # only work while the tab is visible
        target = self.selected if self.v_hist_sel.get() else None
        keep = None                                 # keep the chosen row when new events arrive
        tv = self.tv_hist
        if tv.selection():
            old = self._hist_rows[int(tv.selection()[0])]
            keep = (old.timestamp, old.kind, old.target)
        self._hist_rows = self.alerter.history.query(target, 500)
        tv.delete(*tv.get_children())
        for i, ev in enumerate(self._hist_rows):
            tv.insert("", "end", iid=str(i), tags=(ev.kind,), values=(
                f"{ev.timestamp:%Y-%m-%d %H:%M:%S}", ev.target, ev.kind.replace("_", " ").title(),
                fmt_path(ev.old_path) if ev.old_path else "", fmt_path(ev.new_path) if ev.new_path else "",
                ev.detail.splitlines()[0] if ev.detail else ""))
        for i, ev in enumerate(self._hist_rows):
            if keep == (ev.timestamp, ev.kind, ev.target):
                tv.selection_set(str(i))
                break
        self.l_hist.configure(text=f"{len(self._hist_rows)} event(s)" +
                              (f" for {target}" if target else " (all targets)"))
        self._draw_timeline()

    def _timeline_x(self, ev, t0, t1, w):
        span = max((t1 - t0).total_seconds(), 1)
        return 14 + (ev.timestamp - t0).total_seconds() / span * (w - 28)

    def _draw_timeline(self):
        c = self.tl_canvas
        c.delete("all")
        rows = self._hist_rows
        w = c.winfo_width()
        fg = self.pal["dim"]
        if not rows or w < 60:
            c.create_text(10, 23, anchor="w", fill=fg, text="No history yet - changes appear here "
                          "as they happen.")
            return
        t0, t1 = rows[-1].timestamp, rows[0].timestamp
        c.create_line(14, 26, w - 14, 26, fill=fg)
        sel = self.tv_hist.selection()
        sel_i = int(sel[0]) if sel else -1
        for i, ev in enumerate(rows):
            x = self._timeline_x(ev, t0, t1, w)
            color = self.KIND_COLORS.get(ev.kind, "#888888")
            r = 7 if i == sel_i else 4
            c.create_oval(x - r, 26 - r, x + r, 26 + r, fill=color, outline="#000000" if i == sel_i else color,
                          tags=(f"ev{i}",))
        c.create_text(14, 6, anchor="w", fill=fg, text=f"{t0:%Y-%m-%d %H:%M:%S}")
        c.create_text(w - 14, 6, anchor="e", fill=fg, text=f"{t1:%Y-%m-%d %H:%M:%S}")
        x = 14
        for color, label in (("#d93636", "path change"), ("#e07b00", "rule violation"),
                             ("#b00020", "RPKI invalid"), ("#2e9e44", "first seen / restored")):
            c.create_oval(x, 46, x + 8, 54, fill=color, outline=color)
            t = c.create_text(x + 13, 50, anchor="w", fill=fg, text=label)
            x = c.bbox(t)[2] + 18
        c.create_text(x, 50, anchor="w", fill=fg, text="· click a dot to select it")

    def _timeline_click(self, event):
        rows = self._hist_rows
        if not rows:
            return
        t0, t1, w = rows[-1].timestamp, rows[0].timestamp, self.tl_canvas.winfo_width()
        best = min(range(len(rows)), key=lambda i: abs(self._timeline_x(rows[i], t0, t1, w) - event.x))
        if abs(self._timeline_x(rows[best], t0, t1, w) - event.x) <= 12:
            self.tv_hist.selection_set(str(best))
            self.tv_hist.see(str(best))

    def _clear_history(self):
        target = self.selected if self.v_hist_sel.get() else None
        what = f"for {target}" if target else "for ALL targets"
        if messagebox.askyesno("Clear history", f"Delete the recorded history {what}?"):
            self.alerter.history.clear(target)
            self._refresh_history()

    def _show_snapshot(self):
        sel = self.tv_hist.selection()
        if not sel:
            messagebox.showinfo("History", "Select an event in the list first.")
            return
        ev = self._hist_rows[int(sel[0])]
        if not ev.snapshot and not ev.new_path:
            messagebox.showinfo("History", "No path data was stored for this event.")
            return
        routes, n = [], 0
        for path, count in ev.snapshot or [(ev.new_path, 1)]:
            for _ in range(count):
                n += 1
                routes.append(Route(ev.target, ev.prefix, "history", f"p{n}", path))
        self.hist_event = ev
        self.hist_view = TargetView(
            target=ev.target, status="changed" if ev.old_path else "ok", prefix=ev.prefix,
            routes=routes, best_path=ev.new_path, previous_path=ev.old_path,
            changed=bool(ev.old_path and ev.kind in ("BEST_CHANGED", "ORIGIN_CHANGED",
                                                    "PREFIX_CHANGED", "BEST_RESTORED")),
            changed_at=ev.timestamp, last_poll=ev.timestamp, best_label="at that time")
        if ev.target != self.selected:
            self.selected = ev.target
            if self.tv_targets.exists(ev.target):
                self.tv_targets.selection_set(ev.target)
        self.b_live.pack(side="right", padx=(0, 14))
        self.nb.select(0)
        self._needs_fit = True
        self._redraw()

    def _leave_replay(self):
        if self.hist_view is not None:
            self.hist_view = self.hist_event = None
            self.b_live.pack_forget()

    def _back_to_live(self):
        self._leave_replay()
        self._needs_fit = True
        self._redraw()

    # ------------------------------------------------------------- misc
    def _export_svg(self):
        if not self._graph or not self.selected:
            messagebox.showinfo("Nothing to export", "Select a target with data first.")
            return
        v = self._current_view()
        name = f"{self.selected.replace('/', '_')}_{datetime.now():%Y-%m-%d_%H%M}.svg"
        path = filedialog.asksaveasfilename(defaultextension=".svg", initialfile=name,
                                            filetypes=[("SVG image", "*.svg")])
        if path:
            title = (f"{v.target}  ({v.prefix})  best: {fmt_path(v.best_path)}  "
                     f"[{v.best_label}]  {v.last_poll:%Y-%m-%d %H:%M:%S}")
            Path(path).write_text(to_svg(self._graph, title), encoding="utf-8")

    def _on_close(self):
        if self._anim_id:
            self.root.after_cancel(self._anim_id)
        self._save_settings()
        self.tray.stop()
        if self.live:
            self.live.close()
        self.monitor.shutdown()
        self.names.save()
        self.root.destroy()
