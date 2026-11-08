"""Small Tk dialogs."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import messenger
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


def edit_messenger(parent, cfg: dict):
    """Modal dialog for the Telegram / webhook push. Returns the new config dict, or None if cancelled."""
    cfg = {**messenger.default_config(), **cfg}
    win = tk.Toplevel(parent)
    win.title("Messenger notifications")
    win.transient(parent)
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, justify="left", text=(
        "Send every path-change / rule / RPKI alert to your phone.\n"
        "Telegram: create a bot with @BotFather, send it a message, then get your chat ID\n"
        "(e.g. from @userinfobot, or https://api.telegram.org/bot<token>/getUpdates).\n"
        "Webhook: a Discord or Slack webhook URL, or an ntfy.sh topic URL.")
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
    v_en = tk.BooleanVar(value=bool(cfg["enabled"]))
    v_kind = tk.StringVar(value=cfg["kind"])
    v_tok, v_chat, v_url = (tk.StringVar(value=cfg[k]) for k in ("token", "chat_id", "url"))
    ttk.Checkbutton(frm, text="Enable messenger notifications", variable=v_en
                    ).grid(row=1, column=0, columnspan=2, sticky="w")
    ttk.Label(frm, text="Service:").grid(row=2, column=0, sticky="w", pady=3)
    ttk.Combobox(frm, textvariable=v_kind, values=messenger.KINDS, state="readonly", width=12
                 ).grid(row=2, column=1, sticky="w")
    rows = {}
    for i, (label, var, show) in enumerate((("Bot token", v_tok, "*"), ("Chat ID", v_chat, ""),
                                            ("Webhook URL", v_url, "*")), start=3):
        lb = ttk.Label(frm, text=label + ":")
        en = ttk.Entry(frm, textvariable=var, width=46, show=show)
        lb.grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
        en.grid(row=i, column=1, sticky="ew")
        rows[label] = (lb, en)

    def layout(*_):
        tg = v_kind.get() == "telegram"
        for label, (lb, en) in rows.items():
            if (label == "Webhook URL") == tg:
                lb.grid_remove(); en.grid_remove()
            else:
                lb.grid(); en.grid()
    v_kind.trace_add("write", layout)
    layout()
    v_px, v_pu, v_pp = (tk.StringVar(value=cfg[k]) for k in ("proxy", "proxy_user", "proxy_pass"))
    ttk.Label(frm, text="Proxy (optional):").grid(row=6, column=0, sticky="w", pady=(10, 3), padx=(0, 10))
    ttk.Entry(frm, textvariable=v_px, width=46).grid(row=6, column=1, sticky="ew", pady=(10, 3))
    ttk.Label(frm, text="   http://host:port  or  socks5://host:port - leave empty for a direct connection",
              foreground="#777777").grid(row=7, column=0, columnspan=2, sticky="w")
    ttk.Label(frm, text="Proxy user:").grid(row=8, column=0, sticky="w", pady=3)
    ttk.Entry(frm, textvariable=v_pu, width=46).grid(row=8, column=1, sticky="ew")
    ttk.Label(frm, text="Proxy password:").grid(row=9, column=0, sticky="w", pady=3)
    ttk.Entry(frm, textvariable=v_pp, width=46, show="*").grid(row=9, column=1, sticky="ew")
    ttk.Label(frm, text="   user / password only if the proxy needs a login",
              foreground="#777777").grid(row=10, column=0, columnspan=2, sticky="w")
    status = ttk.Label(frm, text="", wraplength=420, justify="left")
    status.grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 0))
    result = {}

    def current():
        return {"enabled": v_en.get(), "kind": v_kind.get(), "token": v_tok.get().strip(),
                "chat_id": v_chat.get().strip(), "url": v_url.get().strip(),
                "proxy": v_px.get().strip(), "proxy_user": v_pu.get().strip(), "proxy_pass": v_pp.get()}

    def test():
        status.configure(text="Sending…")
        win.update_idletasks()
        err = messenger.send(current(), "BGP LookingGlass", "Test message - notifications work.")
        status.configure(text="✔ Sent - check your messenger." if err is None else f"✘ {err}")

    def ok():
        result["v"] = current()
        win.destroy()

    bt = ttk.Frame(frm)
    bt.grid(row=12, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(bt, text="Send test", command=test).pack(side="left", padx=4)
    ttk.Button(bt, text="Cancel", command=win.destroy).pack(side="left", padx=4)
    ttk.Button(bt, text="Save", command=ok).pack(side="left", padx=4)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_visibility()
    parent.wait_window(win)
    return result.get("v")
