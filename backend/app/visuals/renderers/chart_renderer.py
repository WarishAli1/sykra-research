import os, uuid
from app.visuals import theme
from app.visuals.schema import (
    VisualSpec, ChartPayload, ProvenanceKind,
)

EXPORT_DIR = os.path.join("exports", "studio")


def render_chart(spec: VisualSpec) -> str:
    """Render a ChartPayload to a PNG asset. Returns '/exports/studio/.../vN.png'.

    Anti-hallucination guardrails baked into the render:
      - ILLUSTRATIVE specs get a visible 'Illustrative' banner.
      - GROUNDED specs get a compact source line in the figure footer.
    """
    import matplotlib.pyplot as plt
    theme.apply_mpl_style()

    payload: ChartPayload = spec.payload
    fig, ax = plt.subplots(figsize=(8, 5))

    if payload.chart_type == "scatter":
        _scatter(ax, payload)
    elif payload.chart_type == "pie":
        _pie(ax, payload)
    else:
        _bar_or_line(ax, payload)

    ax.set_title(spec.title, fontdict=theme.FONT_TITLE, pad=14)
    if payload.x_label:
        ax.set_xlabel(payload.x_label, fontdict=theme.FONT_LABEL)
    if payload.y_label:
        ax.set_ylabel(payload.y_label, fontdict=theme.FONT_LABEL)
    if payload.log_y:
        ax.set_yscale("log")
    if payload.series and payload.chart_type != "pie":
        ax.legend()

    _draw_grounding(fig, spec)

    out_dir = os.path.join(EXPORT_DIR, spec.visual_id)
    os.makedirs(out_dir, exist_ok=True)
    fname = f"v{spec.revision}.png"
    path = os.path.join(out_dir, fname)
    fig.savefig(path)
    plt.close(fig)
    return f"/{path.replace(os.sep, '/')}"


def _bar_or_line(ax, payload: ChartPayload):
    import numpy as np
    xs = np.arange(len(payload.categories))
    n = len(payload.series)
    width = 0.8 / max(n, 1)
    for i, s in enumerate(payload.series):
        color = theme.palette(n)[i]
        if payload.chart_type == "bar":
            offset = (i - (n - 1) / 2) * width
            ax.bar(xs + offset, s.values, width, label=s.label, color=color)
            if payload.show_values:
                for x, v in zip(xs + offset, s.values):
                    if v is not None:
                        ax.text(x, v, f"{v:g}", ha="center", va="bottom",
                                **theme.FONT_TICK)
        else: 
            ax.plot(xs, s.values, marker="o", label=s.label, color=color)
    ax.set_xticks(xs)
    ax.set_xticklabels(payload.categories)


def _pie(ax, payload: ChartPayload):
    s = payload.series[0]
    colors = theme.palette(len(s.values))
    wedges, _, _ = ax.pie(
        s.values, labels=payload.categories, colors=colors, autopct="%1.1f%%",
        startangle=90, pctdistance=0.85,
        wedgeprops=dict(width=0.35, edgecolor=theme.PAPER, linewidth=2),
    )
    ax.add_patch(plt.Circle((0, 0), 0.66, fc=theme.PAPER))
    ax.set_aspect("equal")


def _scatter(ax, payload: ChartPayload):
    n = len(payload.series)
    for i, s in enumerate(payload.series):
        ax.scatter(s.x_values, s.values, label=s.label, color=theme.palette(n)[i], s=42)
    ax.grid(True)


def _draw_grounding(fig, spec: VisualSpec):
    """Stamp provenance into the figure itself."""
    badge = theme.GROUNDING_BADGE[spec.grounding.level]
    fig.text(0.985, 0.985, badge["text"], ha="right", va="top",
             fontsize=8, color=badge["color"], style="italic")
    if spec.grounding.level in ("grounded", "mixed") and spec.grounding.citations:
        refs = ", ".join(f"[{c}]" for c in spec.grounding.citations[:6])
        fig.text(0.015, 0.012, f"Source: {refs}", ha="left", va="bottom",
                 **theme.FONT_CAPTION)
    if spec.grounding.level == "illustrative":
        fig.text(0.5, 0.5, "ILLUSTRATIVE", ha="center", va="center",
                 fontsize=34, color=theme.DANGER, alpha=0.08,
                 rotation=20, weight="bold")