"""
Sykra visual identity — single source of truth.

Used identically by:
  - chart_renderer.py   (matplotlib/seaborn)
  - diagram_renderer.py (graphviz)
  - PDF export          (embeds the same rendered asset, never re-renders)

Colors mirror app/globals.css. Do NOT hardcode colors in renderers.
"""
from __future__ import annotations
from dataclasses import dataclass

PAPER      = "#fbfcfc"
PAPER_DIM  = "#eef2f2"
INK        = "#14181b"
INK_SOFT   = "#5f676d"
INDIGO     = "#0e6b62"  
INDIGO_DARK= "#0a524b"
INDIGO_TINT= "#e1efed"
GOLD       = "#4d7a84"   
GOLD_TINT  = "#e7eff1"
LINE       = "#dce3e3"
DANGER     = "#c2453c"

CATEGORICAL = [
    "#0e6b62", 
    "#4d7a84",
    "#d9a441",
    "#b3573d", 
    "#5e6fa0", 
    "#6f8f5a", 
    "#8a5e8f", 
    "#8a9099", 
]

SEQUENTIAL = ["#dfeeea", "#a9ccc7", "#6f9f99", "#3f7a72", "#0e6b62", "#073f3a"]

DIVERGING = ["#b3573d", "#e0c3ba", "#fbfcfc", "#a9ccc7", "#0e6b62"]

def palette(n: int) -> list[str]:
    """Return n distinguishable colors, cycling safely past the base set."""
    return [CATEGORICAL[i % len(CATEGORICAL)] for i in range(n)]

TITLE_FONT_FAMILY = ["Iowan Old Style", "Georgia", "Palatino", "DejaVu Serif"]
BODY_FONT_FAMILY  = ["Inter", "Segoe UI", "DejaVu Sans"]
FONT_TITLE = {"family": "serif", "size": 14, "weight": "semibold", "color": INK}
FONT_LABEL = {"family": "sans-serif", "size": 11, "color": INK}
FONT_TICK  = {"family": "sans-serif", "size": 9.5, "color": INK_SOFT}
FONT_CAPTION = {"family": "sans-serif", "size": 8.5, "color": INK_SOFT}

GROUNDING_BADGE = {
    "user_provided": {"text": "User-provided data",    "color": GOLD},
    "grounded":      {"text": "Grounded in sources",    "color": INDIGO},
    "mixed":         {"text": "Mixed provenance",       "color": GOLD},
    "illustrative":  {"text": "Illustrative — not from data",  "color": DANGER},
    "user_edited":   {"text": "User-edited value",  "color": GOLD},
    "draft":         {"text": "AI draft — confirm before use", "color": INDIGO},
}


def apply_mpl_style() -> None:
    """Apply the Sykra theme to matplotlib rcParams. Call once per render."""
    import matplotlib.pyplot as plt
    rc = {
        "figure.facecolor": PAPER,
        "axes.facecolor":   PAPER,
        "savefig.facecolor": PAPER,
        "savefig.edgecolor": "none",
        "savefig.dpi": 180,
        "axes.edgecolor": LINE,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": LINE,
        "grid.linewidth": 0.7,
        "grid.linestyle": "--",
        "axes.axisbelow": True,
        "text.color": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK_SOFT,
        "ytick.color": INK_SOFT,
        "font.family": "sans-serif",
        "font.sans-serif": BODY_FONT_FAMILY + ["DejaVu Sans"],
        "axes.titlesize": 14,
        "axes.labelsize": 11,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.frameon": False,
        "legend.fontsize": 9.5,
        "lines.linewidth": 2.0,
        "lines.markersize": 6,
        "patch.edgecolor": "none",
    }
    plt.rcParams.update(rc)


def emit_mplstyle(path: str) -> str:
    """Optionally dump a portable .mplstyle file (for reuse outside this service)."""
    lines = [
        "figure.facecolor: %s" % PAPER,
        "axes.facecolor: %s" % PAPER,
        "axes.edgecolor: %s" % LINE,
        "axes.grid: True",
        "grid.color: %s" % LINE,
        "grid.linestyle: --",
        "axes.axisbelow: True",
        "axes.spines.top: False",
        "axes.spines.right: False",
        "text.color: %s" % INK,
        "xtick.color: %s" % INK_SOFT,
        "ytick.color: %s" % INK_SOFT,
        "font.family: sans-serif",
        "savefig.dpi: 180",
        "savefig.bbox: tight",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path