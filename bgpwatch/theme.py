"""Colours used by both the Tk canvas and the SVG export."""

GREEN = "#2e9e44"      # stable best path
NEW_BLUE = "#1e88ff"   # new best path right after a change (blinks, then turns green)
RED = "#d93636"        # rule violations / errors
GREY_DASH = "#8a8a8a"  # previous best path
GREY = "#bdbdbd"       # alternate (non-best) paths
BLUE = "#1f5fbf"

# status -> (colour, width, dash)
EDGE_STYLE = {
    "alt": (GREY, 1, None),
    "previous": (GREY_DASH, 2, (6, 4)),
    "best": (GREEN, 4, None),
    "changed": (NEW_BLUE, 4, None),
}

STATUS_FILL = {
    "alt": ("#f4f4f2", "#b4b2a9", "#444441"),
    "previous": ("#ececea", "#8a8a8a", "#444441"),
    "best": ("#e3f4e1", GREEN, "#1d5a28"),
    "changed": ("#dcebff", NEW_BLUE, "#0b3a7a"),
}


def node_colors(kind: str, status: str):
    """Return (fill, outline, text) for a node."""
    fill, outline, text = STATUS_FILL[status]
    if kind == "origin":
        fill = "#e3eefb" if status in ("alt", "previous") else fill
        text = "#0c447c" if status in ("alt", "previous") else text
    if kind == "prefix":
        fill, text = "#f1efe8", "#2c2c2a"
    if kind == "target":
        fill, outline, text = BLUE, BLUE, "#ffffff"
    return fill, outline, text


HEADER_BG = {"ok": "#e3f4e1", "changed": "#dcebff", "error": "#fff1d6", "pending": "#eeeeee",
             "violation": "#f9c9c9", "rpki": "#f9c9c9"}
HEADER_FG = {"ok": "#1d5a28", "changed": "#0b3a7a", "error": "#6b4a00", "pending": "#333333",
             "violation": "#6b0000", "rpki": "#6b0000"}
STATUS_ICON = {"ok": "✔", "changed": "⚠", "error": "✖", "pending": "…", "violation": "⛔", "rpki": "⛔"}
