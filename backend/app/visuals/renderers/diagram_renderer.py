"""
Renders DiagramPayload (flowchart / architecture / dfd) to a PNG asset.

Uses matplotlib primitives (no Graphviz dependency) with a hand-rolled
hierarchical layout:
  1. layer assignment  (longest-path topological, or explicit node.layer)
  2. crossing reduction (barycenter ordering, down + up passes)
  3. coordinate assignment (centered per layer)

Node shapes follow standard conventions:
  terminal -> rounded pill   process -> box        decision -> diamond
  data     -> parallelogram  external -> bordered box   store -> open box
  dfd process -> circle

Writes to exports/studio/<visual_id>/v<revision>.png — identical asset
convention to chart_renderer.py, so preview / chat / PDF all reference
the same file (render once, reuse everywhere).
"""
from __future__ import annotations

import os
import textwrap
from collections import deque

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon, Circle

from app.visuals import theme
from app.visuals.schema import VisualSpec, DiagramPayload

EXPORT_DIR = os.path.join("exports", "studio")

NODE_W = 2.8
NODE_H = 1.0
H_GAP = 0.8        
V_GAP = 1.5        
LABEL_WIDTH = 20    


def _wrap_label(text: str, width: int = LABEL_WIDTH) -> str:
    text = (text or "").strip() or " "
    return "\n".join(textwrap.wrap(text, width=width)) or text


def _node_style(node_type: str, kind: str) -> tuple[str, str, str]:
    """Return (fill, border, text_color) for a node."""
    if kind == "dfd":
        if node_type == "process":
            return theme.INDIGO, theme.INDIGO_DARK, theme.PAPER
        if node_type == "external":
            return theme.PAPER, theme.INK_SOFT, theme.INK
        if node_type == "store":
            return theme.GOLD_TINT, theme.GOLD, theme.INK
    if node_type == "terminal":
        return theme.INK, "none", theme.PAPER
    if node_type == "decision":
        return theme.GOLD, theme.GOLD, theme.PAPER
    if node_type == "data":
        return theme.INDIGO_TINT, theme.INDIGO, theme.INK
    if node_type == "external":
        return theme.PAPER, theme.INK_SOFT, theme.INK
    if node_type == "store":
        return theme.GOLD_TINT, theme.GOLD, theme.INK
    return theme.INDIGO, theme.INDIGO_DARK, theme.PAPER


def _assign_layers(nodes, edges, payload: DiagramPayload) -> dict[str, int]:
    if payload.kind == "architecture" and any(n.layer is not None for n in nodes):
        return {n.id: (n.layer if n.layer is not None else 0) for n in nodes}

    ids = [n.id for n in nodes]
    id_set = set(ids)
    succs = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for e in edges:
        if e.source in id_set and e.target in id_set and e.source != e.target:
            succs[e.source].append(e.target)
            indeg[e.target] += 1

    q = deque(i for i in ids if indeg[i] == 0)
    if not q and ids:          
        q.append(ids[0])
    topo, indeg_c = [], dict(indeg)
    while q:
        u = q.popleft()
        topo.append(u)
        for v in succs[u]:
            indeg_c[v] -= 1
            if indeg_c[v] == 0:
                q.append(v)
    for i in ids:                   
        if i not in topo:
            topo.append(i)

    layer = {i: 0 for i in ids}
    for u in topo:
        for v in succs[u]:
            if layer[v] < layer[u] + 1:
                layer[v] = layer[u] + 1
    return layer


def _order_within_layers(nodes, edges, layers) -> dict[int, list]:
    max_layer = max(layers.values()) if layers else 0
    by_layer = {L: [] for L in range(max_layer + 1)}
    for n in nodes:
        by_layer[layers[n.id]].append(n)

    preds = {n.id: [] for n in nodes}
    succs = {n.id: [] for n in nodes}
    id_set = {n.id for n in nodes}
    for e in edges:
        if e.source in id_set and e.target in id_set:
            succs[e.source].append(e.target)
            preds[e.target].append(e.source)

    def positions():
        pos = {}
        for lst in by_layer.values():
            for i, n in enumerate(lst):
                pos[n.id] = i
        return pos

    for _ in range(2):
        for L in range(1, max_layer + 1):
            pos = positions()
            by_layer[L].sort(
                key=lambda n: (
                    sum(pos[p] for p in preds[n.id] if p in pos) / len(preds[n.id])
                    if preds[n.id] else pos[n.id]
                )
            )
        for L in range(max_layer - 1, -1, -1):
            pos = positions()
            by_layer[L].sort(
                key=lambda n: (
                    sum(pos[s] for s in succs[n.id] if s in pos) / len(succs[n.id])
                    if succs[n.id] else pos[n.id]
                )
            )
    return by_layer


def _assign_positions(by_layer, layout: str, nodes) -> dict[str, tuple]:
    """Return {node_id: (x, y, half_w, half_h)}."""
    geom: dict[str, tuple] = {}
    spread_pitch = NODE_W + H_GAP
    layer_pitch = NODE_H + V_GAP
    for L, lst in by_layer.items():
        n = len(lst)
        for i, node in enumerate(lst):
            s = (i - (n - 1) / 2) * spread_pitch  
            l = L * layer_pitch
            if layout == "left_right":
                x, y = l, -s
            else:                                   
                x, y = s, -l
            lines = _wrap_label(node.label).count("\n") + 1
            hh = (NODE_H + (lines - 1) * 0.35) / 2
            geom[node.id] = (x, y, NODE_W / 2, hh)
    return geom


def _edge_anchors(geom, e, layout: str):
    if e.source not in geom or e.target not in geom:
        return None
    sx, sy, shw, shh = geom[e.source]
    tx, ty, thw, thh = geom[e.target]
    if layout == "left_right":
        return (sx + shw, sy), (tx - thw, ty)
    return (sx, sy - shh), (tx, ty + thh)


def _draw_node(ax, geom, node, kind: str):
    x, y, hw, hh = geom[node.id]
    w, h = hw * 2, hh * 2
    label = _wrap_label(node.label)
    fill, border, txt = _node_style(node.node_type, kind)
    z = 3

    if kind == "dfd" and node.node_type == "process":
        ax.add_patch(Circle((x, y), max(hw, hh), facecolor=fill,
                            edgecolor=border, linewidth=1.2, zorder=z))
    elif node.node_type == "decision":
        dw, dh = hw * 1.3, hh * 1.3
        ax.add_patch(Polygon([(x, y + dh), (x + dw, y), (x, y - dh), (x - dw, y)],
                             closed=True, facecolor=fill, edgecolor=border,
                             linewidth=1.2, zorder=z))
    elif node.node_type == "data":
        sk = hw * 0.35
        ax.add_patch(Polygon([(x - hw + sk, y + hh), (x + hw + sk, y + hh),
                              (x + hw - sk, y - hh), (x - hw - sk, y - hh)],
                             closed=True, facecolor=fill, edgecolor=border,
                             linewidth=1.2, zorder=z))
    else:
        rounding = 0.45 if node.node_type == "terminal" else 0.15
        ax.add_patch(FancyBboxPatch((x - hw, y - hh), w, h,
                                    boxstyle=f"round,pad=0,rounding_size={rounding}",
                                    facecolor=fill, edgecolor=border,
                                    linewidth=1.3, zorder=z))
        if node.node_type == "store":
            ax.plot([x - hw, x + hw], [y + hh * 0.45, y + hh * 0.45],
                    color=border, linewidth=1.0, zorder=z + 1)

    ax.text(x, y, label, ha="center", va="center", color=txt,
            fontsize=9.5, fontweight="medium", zorder=z + 2, linespacing=1.3)


def _draw_edge(ax, start, end, label):
    sx, sy = start
    tx, ty = end
    dx = tx - sx
    rad = 0.0 if abs(dx) < 0.2 else (0.18 if dx > 0 else -0.18)
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14,
                                 color=theme.INK_SOFT, linewidth=1.3,
                                 connectionstyle=f"arc3,rad={rad}", zorder=1))
    if label:
        ax.text((sx + tx) / 2 + 0.15, (sy + ty) / 2, label, fontsize=8,
                color=theme.INK_SOFT, ha="left", va="center", zorder=2,
                bbox=dict(boxstyle="round,pad=0.15", fc=theme.PAPER,
                          ec="none", alpha=0.85))


def _autoscale(ax, geom):
    xs = [g[0] for g in geom.values()]
    ys = [g[1] for g in geom.values()]
    hws = [g[2] for g in geom.values()]
    hhs = [g[3] for g in geom.values()]
    pad = 1.2
    ax.set_xlim(min(xs) - max(hws) - pad, max(xs) + max(hws) + pad)
    ax.set_ylim(min(ys) - max(hhs) - pad, max(ys) + max(hhs) + pad)


def _draw_grounding(fig, spec: VisualSpec):
    badge = theme.GROUNDING_BADGE[spec.grounding.level]
    fig.text(0.985, 0.985, badge["text"], ha="right", va="top",
             fontsize=8, color=badge["color"], style="italic")
    if spec.grounding.level == "illustrative":
        fig.text(0.5, 0.5, "ILLUSTRATIVE", ha="center", va="center",
                 fontsize=30, color=theme.DANGER, alpha=0.07,
                 rotation=18, weight="bold")


def _save(fig, spec: VisualSpec) -> str:
    out_dir = os.path.join(EXPORT_DIR, spec.visual_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"v{spec.revision}.png")
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor=theme.PAPER)
    plt.close(fig)
    return f"/{path.replace(os.sep, '/')}"


def render(spec: VisualSpec) -> str:
    """Render a DiagramPayload to a PNG asset; returns '/exports/studio/.../vN.png'."""
    payload: DiagramPayload = spec.payload
    nodes, edges, kind = payload.nodes, payload.edges, payload.kind

    plt.rcParams["font.family"] = "sans-serif"

    if not nodes:
        fig, ax = plt.subplots(figsize=(6, 3))
        fig.patch.set_facecolor(theme.PAPER)
        ax.set_facecolor(theme.PAPER)
        ax.axis("off")
        ax.text(0.5, 0.5, "No diagram structure provided",
                ha="center", va="center", color=theme.INK_SOFT, fontsize=12)
        return _save(fig, spec)

    layers = _assign_layers(nodes, edges, payload)
    by_layer = _order_within_layers(nodes, edges, layers)
    geom = _assign_positions(by_layer, payload.layout, nodes)

    max_count = max(len(v) for v in by_layer.values())
    n_layers = len(by_layer)
    fig_w = min(14, max(7, max_count * 2.4 + 3))
    fig_h = min(15, max(4.5, n_layers * 1.7 + 2.5))

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(theme.PAPER)
    ax.set_facecolor(theme.PAPER)
    ax.axis("off")

    for e in edges:                
        anchors = _edge_anchors(geom, e, payload.layout)
        if anchors:
            _draw_edge(ax, anchors[0], anchors[1], e.label)
    for n in nodes:
        if n.id in geom:
            _draw_node(ax, geom, n, kind)

    _autoscale(ax, geom)
    if spec.title:
        ax.set_title(spec.title, fontsize=14, fontweight="bold",
                     color=theme.INK, pad=18)
    _draw_grounding(fig, spec)
    return _save(fig, spec)