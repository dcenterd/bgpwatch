"""Small Tk dialogs."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .rules import Rules, parse_asns


def edit_rules(parent, target: str, current: Rules | None, n_targets: int = 1):
    """Modal dialog. Returns (Rules, apply_to_all) or None when cancelled.
    An empty Rules clears the rules."""
    cur = current or Rules()
    win = tk.Toplevel(parent)
    win.title(f"Expected-path rules · {target}")
    win.transient(parent)
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Alert when the best path of this target breaks any of these rules.\n"
                        "Leave a field empty to skip that rule. AS numbers may be written 3356 or AS3356.",
              justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
    fields = (("Expected origin AS", "origin", "" if cur.origin is None else str(cur.origin)),
              ("Must pass through (all)", "via", ", ".join(map(str, cur.via))),
              ("Must NOT pass through (any)", "avoid", ", ".join(map(str, cur.avoid))),
              ("Max path length (ASes)", "max_len", str(cur.max_len or "")))
    vars_ = {}
    for i, (label, key, val) in enumerate(fields, start=1):
        ttk.Label(frm, text=label + ":").grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
        vars_[key] = tk.StringVar(value=val)
        ttk.Entry(frm, textvariable=vars_[key], width=34).grid(row=i, column=1, sticky="ew")
    v_all = tk.BooleanVar(value=False)
    if n_targets > 1:
        ttk.Checkbutton(frm, text=f"apply to all {n_targets} targets",
                        variable=v_all).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
    result = {}

    def ok():
        origin = parse_asns(vars_["origin"].get())
        lim = parse_asns(vars_["max_len"].get())
        result["v"] = (Rules(origin[0] if origin else None, parse_asns(vars_["via"].get()),
                             parse_asns(vars_["avoid"].get()), lim[0] if lim else 0), v_all.get())
        win.destroy()

    def clear():
        for var in vars_.values():
            var.set("")

    bt = ttk.Frame(frm)
    bt.grid(row=7, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(bt, text="Clear rules", command=clear).pack(side="left", padx=4)
    ttk.Button(bt, text="Cancel", command=win.destroy).pack(side="left", padx=4)
    ttk.Button(bt, text="Save", command=ok).pack(side="left", padx=4)
    win.bind("<Return>", lambda e: ok())
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_visibility()
    parent.wait_window(win)
    return result.get("v")
