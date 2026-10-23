"""The Help window: how the app works, the component diagram and the module matrix."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

from . import helpdata as hd
from . import osutil


class HelpWindow:
    CELL = 34

    def __init__(self, parent, pal: dict, dark: bool = False):
        self.parent, self.pal, self.dark = parent, pal, dark
        self.win = tk.Toplevel(parent)
        self.win.title("Help — how BGP LookingGlass works")
        self.win.geometry("1180x780")
        self.win.minsize(800, 520)
        self.win.configure(background=pal["bg"])
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_text(nb)
        self._build_diagram(nb)
        self._build_matrix(nb)
        self._build_params(nb)
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self.win.focus_set()

    # ------------------------------------------------------------------ tab 1: explanation
    def _build_text(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="  How it works  ")
        base = tkfont.nametofont("TkDefaultFont").actual("family")
        t = tk.Text(frame, wrap="word", padx=24, pady=16, bg=self.pal["panel"], fg=self.pal["fg"],
                    relief="flat", highlightthickness=0, cursor="arrow",
                    font=tkfont.Font(family=base, size=11), spacing1=2, spacing3=4)
        ys = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        accent = "#7fb2ff" if self.dark else "#0c447c"
        t.tag_configure("h1", font=tkfont.Font(family=base, size=15, weight="bold"), foreground=accent,
                        spacing1=16, spacing3=6)
        t.tag_configure("p", lmargin1=0, lmargin2=0)
        t.tag_configure("li", lmargin1=18, lmargin2=34)
        t.tag_configure("code", font=tkfont.Font(family=osutil.mono_font(), size=10), lmargin1=18, lmargin2=18,
                        background=self.pal["bg"])
        for style, text in hd.HELP:
            t.insert("end", text + "\n", style)
        t.configure(state="disabled")

    # ------------------------------------------------------------------ tab 4: parameters
    def _build_params(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="  Parameters  ")
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="Filter:").pack(side="left")
        self.v_pfilter = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.v_pfilter, width=30)
        e.pack(side="left", padx=4)
        self.v_pfilter.trace_add("write", lambda *a: self._fill_params())
        ttk.Label(top, text="every command-line option, window control, rule and saved setting"
                  ).pack(side="left", padx=10)
        cols = ("name", "default", "values", "desc")
        self.tv_params = ttk.Treeview(frame, columns=cols, show="tree headings", selectmode="browse")
        for col, text, w, stretch in (("#0", "Group", 150, False), ("name", "Parameter", 210, False),
                                      ("default", "Default", 110, False), ("values", "Values", 180, False),
                                      ("desc", "What it does", 480, True)):
            self.tv_params.heading(col, text=text)
            self.tv_params.column(col, width=w, stretch=stretch)
        self.info_p = tk.Label(frame, anchor="w", justify="left", wraplength=1100, padx=10, pady=6,
                               bg=self.pal["panel"], fg=self.pal["fg"],
                               text="Select a row to read its full text.")
        self.info_p.pack(side="bottom", fill="x")
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tv_params.yview)
        self.tv_params.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.tv_params.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.tv_params.bind("<<TreeviewSelect>>", self._param_selected)
        self._fill_params()

    def _param_selected(self, _e=None):
        sel = self.tv_params.selection()
        vals = self.tv_params.item(sel[0], "values") if sel else ()
        if len(vals) == 4:
            name, default, values, desc = vals
            self.info_p.configure(text=f"{name}\nDefault: {default}    Values: {values}\n{desc}")

    def _fill_params(self):
        tv, q = self.tv_params, self.v_pfilter.get().strip().lower()
        tv.delete(*tv.get_children())
        groups: dict = {}
        for group, name, default, values, desc in hd.PARAMS:
            if q and q not in f"{group} {name} {default} {values} {desc}".lower():
                continue
            if group not in groups:
                groups[group] = tv.insert("", "end", text=group, open=True)
            tv.insert(groups[group], "end", values=(name, default, values, desc))

    # ------------------------------------------------------------------ tab 2: diagram
    def _build_diagram(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="  Component diagram  ")
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=(6, 2))
        leg = tk.Canvas(top, height=24, bg=self.pal["bg"], highlightthickness=0)
        leg.pack(side="left", fill="x", expand=True)
        x = 6
        for kind, name in hd.KIND_NAMES.items():
            fill, border = hd.KIND_COLORS[kind]
            leg.create_rectangle(x, 5, x + 18, 19, fill=fill, outline=border, width=2)
            t = leg.create_text(x + 24, 12, text=name, anchor="w", fill=self.pal["fg"])
            x = leg.bbox(t)[2] + 18
        leg.create_line(x, 12, x + 30, 12, dash=(6, 4), fill=self.pal["fg"], arrow="last")
        leg.create_text(x + 36, 12, text="control / wake-up", anchor="w", fill=self.pal["fg"])
        ttk.Button(top, text="Save diagram (SVG)…", command=self._save_svg).pack(side="right")

        cf = ttk.Frame(frame)
        cf.pack(fill="both", expand=True)
        w, h = hd.DIAGRAM_SIZE
        self.dc = tk.Canvas(cf, bg=self.pal["canvas"], highlightthickness=0, scrollregion=(0, 0, w, h))
        xs = ttk.Scrollbar(cf, orient="horizontal", command=self.dc.xview)
        ys = ttk.Scrollbar(cf, orient="vertical", command=self.dc.yview)
        self.dc.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.dc.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        cf.rowconfigure(0, weight=1)
        cf.columnconfigure(0, weight=1)
        self.info_d = tk.Label(frame, anchor="w", justify="left", wraplength=1100, padx=10, pady=6,
                               bg=self.pal["panel"], fg=self.pal["fg"],
                               text="Click a box to highlight its connections and read what it does.")
        self.info_d.pack(fill="x")
        self.dz, self._active = 1.0, None
        self._draw_diagram()
        self.dc.bind("<Configure>", self._fit_diagram)

    def _fit_diagram(self, event=None):
        """Scale the diagram to the window (up to 1.3x), so it is fully visible."""
        w, h = hd.DIAGRAM_SIZE
        cw, ch = self.dc.winfo_width(), self.dc.winfo_height()
        if cw < 50 or ch < 50:
            return
        scale = max(0.4, min(cw / w, ch / h, 1.3))
        if abs(scale - self.dz) > 0.02:
            self.dz = scale
            self._draw_diagram(self._active)

    def _draw_diagram(self, active: str | None = None):
        c, z = self.dc, self.dz
        self._active = active
        c.delete("all")
        c.configure(scrollregion=(0, 0, hd.DIAGRAM_SIZE[0] * z, hd.DIAGRAM_SIZE[1] * z))
        line = "#9aa0a6" if self.dark else "#5f6368"
        linked = set()
        if active:
            for f, t, *_ in hd.EDGES:
                if active in (f, t):
                    linked.update((f, t))
        fs = lambda n: max(6, int(round(n * z)))  # noqa: E731
        for f, t, label, dashed in hd.EDGES:
            (x1, y1), (x2, y2) = hd.edge_points(f, t)
            x1, y1, x2, y2 = x1 * z, y1 * z, x2 * z, y2 * z
            hot = active in (f, t) if active else False
            dim = active is not None and not hot
            color = "#1e88e5" if hot else ("#555555" if dim and self.dark else "#c5c9cd" if dim else line)
            c.create_line(x1, y1, x2, y2, fill=color, width=2.6 if hot else 1.3,
                          dash=(6, 4) if dashed else (), arrow="last", arrowshape=(9, 11, 4))
            if not dim:
                pair = any(ff == t and tt == f for ff, tt, *_ in hd.EDGES)
                frac = (0.3 if f < t else 0.7) if pair else 0.5     # keep a two-way pair apart
                tx = c.create_text(x1 + (x2 - x1) * frac, y1 + (y2 - y1) * frac, text=label,
                                   fill="#1e88e5" if hot else self.pal["fg"],
                                   font=("TkDefaultFont", fs(8), "bold" if hot else "normal"))
                bx = c.bbox(tx)
                bg = c.create_rectangle(bx[0] - 2, bx[1], bx[2] + 2, bx[3], fill=self.pal["canvas"], outline="")
                c.tag_lower(bg, tx)
        for key, (x, y, bw, bh, title, sub, kind) in hd.BOXES.items():
            fill, border = hd.KIND_COLORS[kind]
            dim = active is not None and key != active and key not in linked
            tag = f"box_{key}"
            x, y, bw, bh = x * z, y * z, bw * z, bh * z
            c.create_rectangle(x, y, x + bw, y + bh,
                               fill=("#3a3d41" if self.dark else "#dddddd") if dim else fill,
                               outline=border, width=3 if key == active else 2, tags=(tag,))
            c.create_text(x + bw / 2, y + bh / 2 - 8 * z, text=title,
                          font=("TkDefaultFont", fs(10), "bold"),
                          fill="#888888" if dim else "#222222", tags=(tag,))
            c.create_text(x + bw / 2, y + bh / 2 + 10 * z, text=sub, font=("TkDefaultFont", fs(8)),
                          fill="#888888" if dim else "#555555", tags=(tag,))
            c.tag_bind(tag, "<Button-1>", lambda e, k=key: self._pick_box(k))
            c.tag_bind(tag, "<Enter>", lambda e: c.configure(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda e: c.configure(cursor=""))
        c.bind("<Button-1>", lambda e: self._pick_box(None) if not c.find_withtag("current") else None)

    def _pick_box(self, key):
        self._draw_diagram(key)
        self.info_d.configure(text=hd.box_info(key) if key else
                              "Click a box to highlight its connections and read what it does.")

    def _save_svg(self):
        path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".svg",
                                            initialfile="bgp-lookingglass-components.svg",
                                            filetypes=[("SVG image", "*.svg")])
        if path:
            Path(path).write_text(hd.diagram_svg(), encoding="utf-8")

    # ------------------------------------------------------------------ tab 3: matrix
    def _build_matrix(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="  Module matrix  ")
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="● = the module in the ROW imports the module in the COLUMN "
                            "(read from the real source code). Hover a dot for details.").pack(side="left")
        ttk.Button(top, text="Save matrix (CSV)…", command=self._save_csv).pack(side="right")
        self.mods, self.edges, self.external = hd.import_matrix()
        n, cell = len(self.mods), self.CELL
        self.left, self.topm = 120, 118
        w = self.left + n * cell + 90
        h = self.topm + n * cell + 50
        cf = ttk.Frame(frame)
        cf.pack(fill="both", expand=True)
        self.mc = tk.Canvas(cf, bg=self.pal["canvas"], highlightthickness=0, scrollregion=(0, 0, w, h))
        xs = ttk.Scrollbar(cf, orient="horizontal", command=self.mc.xview)
        ys = ttk.Scrollbar(cf, orient="vertical", command=self.mc.yview)
        self.mc.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.mc.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        cf.rowconfigure(0, weight=1)
        cf.columnconfigure(0, weight=1)
        ext = "; ".join(f"{m}: {', '.join(v)} ({hd.EXTERNAL_INFO.get(v[0], 'third-party')})"
                        for m, v in self.external.items()) or "none"
        self.info_m = tk.Label(frame, anchor="w", justify="left", wraplength=1100, padx=10, pady=6,
                               bg=self.pal["panel"], fg=self.pal["fg"],
                               text="Hover a cell or a module name.   Third-party packages: " + ext)
        self.info_m.pack(fill="x")
        self._ext_text = self.info_m.cget("text")
        self._draw_matrix()
        self.mc.bind("<Motion>", self._matrix_motion)
        self.mc.bind("<Leave>", lambda e: self._draw_matrix())

    def _draw_matrix(self, hot: tuple | None = None):
        c, mods, edges, cell = self.mc, self.mods, self.edges, self.CELL
        left, top, n = self.left, self.topm, len(self.mods)
        c.delete("all")
        fg, dim = self.pal["fg"], self.pal["dim"]
        grid = "#3a3d41" if self.dark else "#e3e5e8"
        hl = "#2a3b52" if self.dark else "#e4efff"
        uses = {m: sum(1 for (a, _b) in edges if a == m) for m in mods}
        used = {m: sum(1 for (_a, b) in edges if b == m) for m in mods}
        hr, hc = (hot if hot else (None, None))
        for i, m in enumerate(mods):                    # highlight band for the hovered row/column
            if hr == i:
                c.create_rectangle(0, top + i * cell, left + n * cell + 90, top + (i + 1) * cell,
                                   fill=hl, outline="")
            if hc == i:
                c.create_rectangle(left + i * cell, 0, left + (i + 1) * cell, top + n * cell + 40,
                                   fill=hl, outline="")
        for i, m in enumerate(mods):
            x = left + i * cell + cell / 2
            c.create_text(x, top - 6, text=m + ".py" if m != "main" else "main.py", angle=90,
                          anchor="w", fill=fg, font=("TkDefaultFont", 10, "bold" if hc == i else "normal"))
            y = top + i * cell + cell / 2
            c.create_text(left - 8, y, text=m + ".py", anchor="e", fill=fg,
                          font=("TkDefaultFont", 10, "bold" if hr == i else "normal"))
            c.create_text(left + n * cell + 12, y, text=f"imports {uses[m]}", anchor="w", fill=dim,
                          font=("TkDefaultFont", 8))
            c.create_text(x, top + n * cell + 14, text=str(used[m]), fill=dim, font=("TkDefaultFont", 9))
        c.create_text(left + n * cell / 2, top + n * cell + 34, text="↑ how many modules import it",
                      fill=dim, font=("TkDefaultFont", 8))
        for i in range(n + 1):
            c.create_line(left, top + i * cell, left + n * cell, top + i * cell, fill=grid)
            c.create_line(left + i * cell, top, left + i * cell, top + n * cell, fill=grid)
        for i, a in enumerate(mods):
            for j, b in enumerate(mods):
                cx, cy = left + j * cell + cell / 2, top + i * cell + cell / 2
                if i == j:
                    c.create_rectangle(cx - cell / 2 + 1, cy - cell / 2 + 1, cx + cell / 2 - 1,
                                       cy + cell / 2 - 1, fill="#cfd3d8" if not self.dark else "#4a4d52",
                                       outline="")
                elif (a, b) in edges:
                    on = hot is not None and (hr == i or hc == j)
                    r = 9 if (hot == (i, j)) else 7
                    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#1e88e5" if on else "#2e7d32",
                                  outline="")

    def _matrix_motion(self, e):
        c = self.mc
        x, y = c.canvasx(e.x) - self.left, c.canvasy(e.y) - self.topm
        n, cell = len(self.mods), self.CELL
        j, i = int(x // cell), int(y // cell)
        if 0 <= i < n and 0 <= j < n:
            self._draw_matrix((i, j))
            a, b = self.mods[i], self.mods[j]
            if (a, b) in self.edges:
                self.info_m.configure(text=f"{a}.py imports from {b}.py:  " + ", ".join(self.edges[(a, b)]))
            else:
                self.info_m.configure(text=f"{a}.py does not import {b}.py" if a != b else f"{a}.py")
        elif 0 <= i < n and x < 0:                       # hovering a row label
            a = self.mods[i]
            self._draw_matrix((i, -1))
            uses = [b for (x_, b) in self.edges if x_ == a]
            usedby = [x_ for (x_, b) in self.edges if b == a]
            self.info_m.configure(text=f"{hd.MODULE_INFO.get(a, (a, ''))[1]}\nImports: "
                                  f"{', '.join(uses) or '-'}   ·   Imported by: {', '.join(usedby) or '-'}")
        else:
            self._draw_matrix()
            self.info_m.configure(text=self._ext_text)

    def _save_csv(self):
        path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv",
                                            initialfile="bgp-lookingglass-modules.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            Path(path).write_text(hd.matrix_csv(), encoding="utf-8")
