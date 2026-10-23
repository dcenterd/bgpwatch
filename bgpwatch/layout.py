"""Turn a TargetView into a layered graph (no Graphviz needed).

Reading direction is left -> right:

    vantage peers  ->  transit ASes  ->  origin AS  ->  prefix  ->  target IP

Every AS appears once, so paths that share a transit merge into one node.
Columns use longest-path layering from the target; rows are ordered with
a few barycenter sweeps to reduce crossing edges.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import TargetView, collapse_prepends
from .theme import EDGE_STYLE, node_colors

# drawing priorities - higher wins when several paths share an edge/node
RANK = {"alt": 0, "previous": 1, "best": 2, "changed": 3}
KIND_RANK = {"peer": 0, "transit": 1, "origin": 2}


@dataclass
class Node:
    key: str
    label: str
    sub: str = ""
    kind: str = "transit"      # peer | transit | origin | prefix | target
    status: str = "alt"        # alt | previous | best | changed
    col: int = 0
    row: int = 0
    x: float = 0
    y: float = 0
    paths: int = 0             # how many displayed paths go through it
    asn: int | None = None


@dataclass
class Edge:
    a: str
    b: str
    status: str = "alt"
    weight: int = 0            # number of peers using this adjacency


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)
    width: float = 0
    height: float = 0
    shown_paths: int = 0
    total_paths: int = 0


NODE_W, NODE_H = 118, 40
COL_GAP, ROW_GAP = 170, 58
MARGIN = 30


def build_graph(view: TargetView, name_of=lambda asn: "", max_paths: int = 10,
                short=lambda s: s) -> Graph:
    g = Graph()
    uniq = view.unique_paths()
    g.total_paths = len(uniq)

    # which paths to show: best + previous always, then the most common ones
    chosen: list = []      # (path, count, status)
    def add(path, count, status):
        for i, (p, c, s) in enumerate(chosen):
            if p == path:
                if RANK[status] > RANK[s]:
                    chosen[i] = (p, c, status)
                return
        chosen.append((path, count, status))

    counts = dict(uniq)
    if view.best_path:
        add(view.best_path, counts.get(view.best_path, 1),
            "changed" if view.changed else "best")
    if view.changed and view.previous_path:
        add(view.previous_path, counts.get(view.previous_path, 0), "previous")
    for path, count in uniq:
        if len(chosen) >= max(max_paths, 1) + (1 if view.changed else 0):
            break
        add(path, count, "alt")
    g.shown_paths = len(chosen)

    prefix_key, target_key = "PFX", "TGT"

    def node(key, **kw):
        n = g.nodes.get(key)
        if n is None:
            n = Node(key=key, **kw)
            g.nodes[key] = n
        return n

    for path, count, status in chosen:
        hops = collapse_prepends(path)
        chain = [f"AS{a}" for a in hops] + [prefix_key, target_key]
        for i, key in enumerate(chain):
            if key == prefix_key:
                n = node(key, label=view.prefix or "?", sub="prefix", kind="prefix")
            elif key == target_key:
                n = node(key, label=view.target, sub="target", kind="target")
            else:
                asn = hops[i]
                holder = name_of(asn)
                kind = "origin" if i == len(hops) - 1 else ("peer" if i == 0 else "transit")
                n = node(key, label=key, sub=short(holder), kind=kind, asn=asn)
                # an AS can be a peer in one path and transit/origin in another
                if KIND_RANK[kind] > KIND_RANK.get(n.kind, 0):
                    n.kind = kind
            n.paths += 1
            if RANK[status] > RANK[n.status]:
                n.status = status
        for a, b in zip(chain, chain[1:]):
            e = g.edges.get((a, b))
            if e is None:
                e = g.edges[(a, b)] = Edge(a, b, status, 0)
            e.weight += count
            if RANK[status] > RANK[e.status]:
                e.status = status

    if not g.nodes:
        return g

    # ---- layering: col 0 = target, increasing to the left ----------------
    succ: dict = {k: [] for k in g.nodes}
    pred: dict = {k: [] for k in g.nodes}
    for (a, b) in g.edges:
        succ[a].append(b)
        pred[b].append(a)
    col = {k: 0 for k in g.nodes}
    for _ in range(len(g.nodes) + 2):           # bounded -> safe with loops
        moved = False
        for a in g.nodes:
            want = max((col[b] + 1 for b in succ[a]), default=0)
            if want > col[a] and want <= len(g.nodes):
                col[a] = want
                moved = True
        if not moved:
            break
    # peers that are not used as transit anywhere go to the far-left column
    maxcol = max(col.values())
    for k, n in g.nodes.items():
        if n.kind == "peer" and not pred[k]:
            col[k] = maxcol

    columns: dict = {}
    for k in g.nodes:                            # insertion order = path order
        columns.setdefault(col[k], []).append(k)

    # ---- ordering: barycenter sweeps -------------------------------------
    pos = {k: i for c in columns.values() for i, k in enumerate(c)}
    def bary(k, neigh):
        ns = [pos[n] for n in neigh[k] if n in pos]
        return sum(ns) / len(ns) if ns else pos[k]
    for _ in range(4):
        for c in sorted(columns)[1:]:            # right -> left, look at successors
            columns[c].sort(key=lambda k: bary(k, succ))
            pos.update({k: i for i, k in enumerate(columns[c])})
        for c in sorted(columns, reverse=True)[1:]:   # left -> right, predecessors
            columns[c].sort(key=lambda k: bary(k, pred))
            pos.update({k: i for i, k in enumerate(columns[c])})

    # ---- coordinates -------------------------------------------------------
    tallest = max(len(c) for c in columns.values())
    height = MARGIN * 2 + tallest * ROW_GAP
    ncols = max(columns) + 1
    for c, keys in columns.items():
        offset = (tallest - len(keys)) * ROW_GAP / 2
        for i, k in enumerate(keys):
            n = g.nodes[k]
            n.col, n.row = c, i
            n.x = MARGIN + (ncols - 1 - c) * COL_GAP + NODE_W / 2
            n.y = MARGIN + offset + i * ROW_GAP + ROW_GAP / 2
    g.width = MARGIN * 2 + (ncols - 1) * COL_GAP + NODE_W
    g.height = height
    return g


# ------------------------------------------------------------------------
# SVG export (same picture as the canvas, for reports and tickets)
# ------------------------------------------------------------------------


def to_svg(g: Graph, title: str) -> str:
    from xml.sax.saxutils import escape
    w, h = g.width + 20, g.height + 60
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
           f'viewBox="0 0 {w:.0f} {h:.0f}" font-family="DejaVu Sans, sans-serif">',
           f'<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<text x="12" y="22" font-size="14" font-weight="bold">{escape(title)}</text>']
    oy = 36
    # alt first, then previous, best, changed on top
    for e in sorted(g.edges.values(), key=lambda e: RANK[e.status]):
        a, b = g.nodes[e.a], g.nodes[e.b]
        x1, y1 = a.x + NODE_W / 2, a.y + oy
        x2, y2 = b.x - NODE_W / 2, b.y + oy
        mx = (x1 + x2) / 2
        color, width, dash = EDGE_STYLE[e.status]
        da = f' stroke-dasharray="{dash[0]} {dash[1]}"' if dash else ""
        out.append(f'<path d="M{x1:.1f},{y1:.1f} C{mx:.1f},{y1:.1f} {mx:.1f},{y2:.1f} '
                   f'{x2:.1f},{y2:.1f}" fill="none" stroke="{color}" stroke-width="{width}"{da}/>')
    def clip(t, size):          # approximate: avg glyph width ~0.6 em
        m = int((NODE_W - 8) / (size * 0.6))
        return t if len(t) <= m else t[:max(m - 1, 1)] + "…"

    for n in g.nodes.values():
        fill, outline, text = node_colors(n.kind, n.status)
        x, y = n.x - NODE_W / 2, n.y - NODE_H / 2 + oy
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{NODE_W}" height="{NODE_H}" rx="6" '
                   f'fill="{fill}" stroke="{outline}" stroke-width="{2 if n.status in ("best", "changed") else 1}"/>')
        ty = n.y + oy - (4 if n.sub else -4)
        out.append(f'<text x="{n.x:.1f}" y="{ty:.1f}" font-size="12" font-weight="bold" '
                   f'text-anchor="middle" fill="{text}">{escape(clip(n.label, 12))}</text>')
        if n.sub:
            out.append(f'<text x="{n.x:.1f}" y="{n.y + oy + 12:.1f}" font-size="9.5" '
                       f'text-anchor="middle" fill="{text}">{escape(clip(n.sub, 9.5))}</text>')
    out.append("</svg>")
    return "\n".join(out)
