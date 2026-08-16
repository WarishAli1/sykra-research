"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Loader2, MessageSquare, Network, ZoomIn, ZoomOut, Maximize2, Pause, Play,
  Type, RefreshCw, AlertTriangle, Search, BarChart3, Route, ExternalLink,
  ChevronRight, X, Square, Sun, Moon,
} from "lucide-react";
import { forceCollide, forceX, forceY } from "d3-force";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { GraphNode, GraphScope, GraphViewResponse } from "@/lib/types";
import type { GraphLink, GraphStats, LegendEntry, NodeRel, SuggestMatch } from "@/lib/types";
import { GRAPH_CONFIG as CFG } from "@/lib/GraphConfig";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type RichNode = GraphNode & {
  color?: string; radius?: number; x?: number; y?: number; vx?: number; vy?: number;
  _lw?: number; _label?: string; _weight?: number;
};
type RichLink = GraphLink & {
  source: any; target: any; sourceId: string; targetId: string;
  color: string; dash: number[] | null;
};
type PathResult = { nodes: Set<string>; links: Set<string>; hops: number; chain: string[] };
type Theme = "dark" | "light";

const LINK_LABELS: Record<string, string> = {
  discusses: "discusses", uses: "uses", evaluates: "evaluates on",
  similar: "similar to", cites: "cites",
};

function hexToRgba(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
const linkKey = (s: string, t: string) => (s < t ? `${s}|${t}` : `${t}|${s}`);
const posCache: Map<string, { x: number; y: number }> =
  ((globalThis as any).__gvPos ??= new Map<string, { x: number; y: number }>());

const THEMES = {
  dark: {
    canvasBg: "radial-gradient(120% 90% at 75% 10%, #131b2c 0%, #0b101b 48%, #070a12 100%)",
    labelBg: "rgba(7,10,16,0.78)", labelText: "rgba(235,240,250,0.92)",
    rim: "rgba(255,255,255,0.18)", rimWidth: 0.75, uploadRing: "rgba(255,255,255,0.85)",
    linkLabelBg: "rgba(7,10,16,0.70)", labelBorder: null as string | null,
    linkText: {
      cites: "rgba(248,113,113,0.95)", similar: "rgba(129,140,248,0.95)",
      evaluates: "rgba(34,211,238,0.90)", uses: "rgba(251,191,36,0.90)",
      default: "rgba(203,213,225,0.80)",
    } as Record<string, string>,
  },
  light: {
    canvasBg: "radial-gradient(120% 90% at 75% 10%, #ffffff 0%, #f1f5fb 48%, #e7edf6 100%)",
    labelBg: "rgba(255,255,255,0.9)", labelText: "rgba(17,24,39,0.92)",
    rim: "rgba(15,23,42,0.35)", rimWidth: 1, uploadRing: "rgba(15,23,42,0.75)",
    linkLabelBg: "rgba(255,255,255,0.9)", labelBorder: "rgba(15,23,42,0.10)",
    linkText: {
      cites: "rgba(153,27,27,0.95)", similar: "rgba(67,56,202,0.95)",
      evaluates: "rgba(8,145,178,0.95)", uses: "rgba(146,64,14,0.95)",
      default: "rgba(51,65,85,0.85)",
    } as Record<string, string>,
  },
};

export function GraphView({
  sessionId, activeTurnId, messagePaperLinks,
}: {
  sessionId: string;
  activeTurnId?: string | null;
  messagePaperLinks?: string[];
}) {
  const [scope, setScope] = useState<GraphScope>(activeTurnId ? "message" : "conversation");
  const [view, setView] = useState<GraphViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [labelsAuto, setLabelsAuto] = useState(true);
  const [physicsOn, setPhysicsOn] = useState(true);
  const [selectedNode, setSelectedNode] = useState<RichNode | null>(null);
  const [trail, setTrail] = useState<RichNode[]>([]);
  const [highlightSet, setHighlightSet] = useState<Set<string> | null>(null);
  const [pathMode, setPathMode] = useState(false);
  const [pathA, setPathA] = useState<RichNode | null>(null);
  const [pathResult, setPathResult] = useState<PathResult | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [yearCut, setYearCut] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searching, setSearching] = useState(false);
  const [sugs, setSugs] = useState<SuggestMatch[] | null>(null);
  const [sugOpen, setSugOpen] = useState(false);
  const [hoverLink, setHoverLink] = useState<RichLink | null>(null);
  const [theme, setTheme] = useState<Theme>(() => {
    try { return (localStorage.getItem("graph-theme") as Theme) || "light"; } catch { return "light"; }
  });
  const [nonce, setNonce] = useState(0);

  const mouseRef = useRef({ x: 0, y: 0 });
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const liveNodesRef = useRef<RichNode[]>([]);
  const pendingSpotlightRef = useRef<string | null>(null);
  const [dims, setDims] = useState({ width: 800, height: 600 });
  const fittedOnce = useRef(false);
  const metaRef = useRef({ small: true });
  const fxRef = useRef<{ focus: Set<string> | null; focusId: string | null; hl: Set<string> | null; path: { nodes: Set<string>; links: Set<string> } | null }>(
    { focus: null, focusId: null, hl: null, path: null }
  );
  const glowCache = useRef(new Map<string, HTMLCanvasElement>());

  const T = THEMES[theme];
  const linkAlpha = theme === "dark" ? { strong: 0.45, normal: 0.28 } : { strong: 0.75, normal: 0.55 };
  const ui = theme === "dark" ? {
    panel: "border-white/10 bg-black/45 backdrop-blur",
    text: "text-white/85", dim: "text-white/50", faint: "text-white/40",
    btn: "text-white/70 hover:bg-white/10 hover:text-white",
    input: "text-white/85 placeholder:text-white/35",
    card: "border-white/15 bg-[#10141d]/95",
    chip: "bg-white/10 text-white/75",
    hoverRow: "hover:bg-white/10",
    methodChip: "bg-amber-500/20 text-amber-200",
    datasetChip: "bg-cyan-500/20 text-cyan-200",
    relatedChip: "bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30",
  } : {
    panel: "border-slate-900/10 bg-white/85 backdrop-blur",
    text: "text-slate-700", dim: "text-slate-500", faint: "text-slate-400",
    btn: "text-slate-600 hover:bg-slate-900/10 hover:text-slate-900",
    input: "text-slate-700 placeholder:text-slate-400",
    card: "border-slate-900/15 bg-white/95",
    chip: "bg-slate-900/10 text-slate-600",
    hoverRow: "hover:bg-slate-900/5",
    methodChip: "bg-amber-500/15 text-amber-700",
    datasetChip: "bg-cyan-500/15 text-cyan-700",
    relatedChip: "bg-indigo-500/15 text-indigo-700 hover:bg-indigo-500/25",
  };

  useEffect(() => {
    try { localStorage.setItem("graph-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  const paperLinksKey = (messagePaperLinks ?? []).join("|");
  useEffect(() => {
    if (!sessionId) { setLoading(false); setView(null); return; }
    let cancelled = false;
    let settled = false;
    if (!view) setLoading(true);
    const t = setTimeout(() => {
      api.graphView(sessionId, {
        scope,
        paper_links: scope === "message" ? (messagePaperLinks ?? []) : undefined,
        max_year: null,
      })
        .then((res) => { if (!cancelled) { setView(res); setError(null); } })
        .catch((e) => { if (!cancelled) setError(e?.message ?? "Could not build the knowledge graph."); })
        .finally(() => { settled = true; if (!cancelled) setLoading(false); });
    }, 120);
    const wd = setTimeout(() => {
      if (!settled && !cancelled) {
        setLoading(false);
        setError("The graph service timed out. Click Rebuild (↻) to try again.");
      }
    }, 60000);
    return () => { cancelled = true; clearTimeout(t); clearTimeout(wd); };
  }, [sessionId, scope, paperLinksKey, nonce]);

  const rebuild = () => {
    setLoading(true); setError(null); setSelectedNode(null); setTrail([]);
    setHighlightSet(null); setPathResult(null); setYearCut(null);
    api.ensureGraph(sessionId, true).finally(() => setNonce((n) => n + 1));
  };

  useEffect(() => { fittedOnce.current = false; }, [nonce, scope]);
  useEffect(() => { if (!activeTurnId && scope === "message") setScope("conversation"); }, [activeTurnId, scope]);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDims({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const colored = useMemo(() => {
    if (!view) return null;
    const nodes: RichNode[] = view.nodes.map((n) => {
      const deg = n.degree ?? 0;
      let color: string, radius: number;
      if (n.type === "paper") {
        color = n.cluster != null ? CFG.palette[n.cluster % CFG.palette.length] : CFG.paperFallbackColor;
        radius = 4.5 + Math.min(Math.log1p(n.citation_count ?? 0) * 1.1, 6) + Math.min(deg, 6) * 0.45;
      } else if (n.type === "concept") {
        color = n.cluster != null ? CFG.palette[n.cluster % CFG.palette.length] : CFG.conceptFallbackColor;
        radius = 3.5 + Math.min(deg, 16) * 0.55;
      } else if (n.type === "method") {
        color = CFG.methodColor; radius = 3 + Math.min(deg, 10) * 0.4;
      } else {
        color = CFG.datasetColor; radius = 3 + Math.min(deg, 10) * 0.4;
      }
      const cached = posCache.get(n.id);
      return { ...n, color, radius, ...(cached ? { x: cached.x, y: cached.y } : {}) };
    });
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const links: RichLink[] = view.links.map((l) => ({
      ...l, sourceId: l.source, targetId: l.target,
      color:
        l.type === "uses" ? CFG.edgeColors.uses
        : l.type === "evaluates" ? CFG.edgeColors.evaluates
        : l.type === "cites" ? CFG.edgeColors.cites
        : l.type === "similar" ? CFG.edgeColors.similar
        : l.type === "discusses" ? (nodeById.get(l.target)?.color ?? CFG.conceptFallbackColor)
        : CFG.conceptFallbackColor,
      dash: l.type === "similar" ? CFG.dashForWeight(l.weight ?? 0.6) : null,
    }));
    return { nodes, links, nodeById };
  }, [view]);

  const visible = useMemo(() => {
    if (!colored) return null;
    let nodes = colored.nodes;
    let links = colored.links;
    if (yearCut != null) {
      const keep = new Set<string>();
      for (const n of nodes) {
        if (n.type === "paper" && (n.year == null || n.year <= yearCut)) keep.add(n.id);
      }
      for (const l of links) {
        const s = colored.nodeById.get(l.sourceId);
        const t = colored.nodeById.get(l.targetId);
        if (!s || !t) continue;
        if ((keep.has(l.sourceId) && (t.type !== "paper" || keep.has(l.targetId))) ||
            (keep.has(l.targetId) && (s.type !== "paper" || keep.has(l.sourceId)))) {
          keep.add(l.sourceId); keep.add(l.targetId);
        }
      }
      nodes = nodes.filter((n) => keep.has(n.id));
      links = links.filter((l) => keep.has(l.sourceId) && keep.has(l.targetId));
    }
    const n = nodes.length, m = links.length;
    const stats = {
      nodes: n, links: m,
      density: n > 1 ? (2 * m) / (n * (n - 1)) : 0,
      avg_degree: n ? (2 * m) / n : 0,
    };
    return { nodes, links, stats };
  }, [colored, yearCut]);

  const graphDataObj = useMemo(
    () => (visible && visible.nodes.length
      ? { nodes: visible.nodes as any, links: visible.links as any }
      : null),
    [visible]
  );

  useEffect(() => {
    liveNodesRef.current = colored?.nodes ?? [];
    metaRef.current.small = (visible?.nodes.length ?? 0) <= 60;
  }, [colored, visible]);

  useEffect(() => {
    const id = pendingSpotlightRef.current;
    if (!id || !colored) return;
    const n = colored.nodeById.get(id);
    if (n) {
      pendingSpotlightRef.current = null;
      setSelectedNode(n); setTrail([n]);
      spotlightMany([id]);
    }
  }, [colored]);

  const focusNode = trail.length ? trail[trail.length - 1] : null;
  const focusSet = useMemo(() => {
    if (!focusNode || !visible) return null;
    const s = new Set([focusNode.id]);
    for (const l of visible.links) {
      if (l.sourceId === focusNode.id) s.add(l.targetId);
      if (l.targetId === focusNode.id) s.add(l.sourceId);
    }
    return s;
  }, [focusNode, visible]);

  useEffect(() => {
    fxRef.current = { focus: focusSet, focusId: focusNode?.id ?? null, hl: highlightSet, path: pathResult };
  }, [focusSet, focusNode, highlightSet, pathResult]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !colored?.nodes.length || typeof fg.d3Force !== "function") return;
    const n = colored.nodes.length;
    const charge = fg.d3Force("charge");
    // Lower distanceMax prevents disconnected clusters from repelling each other across the canvas
    if (charge) { charge.strength(n <= 40 ? -55 : -80); charge.distanceMax(160); }
    const link = fg.d3Force("link");
    if (link) {
      const scale = n <= 30 ? 0.8 : 1;
      link.distance((l: any) =>
        (({ similar: 30, cites: 26, discusses: 18, uses: 15, evaluates: 15 } as Record<string, number>)[l.type] ?? 24) * scale);
    }
    const g = n <= 30 ? 0.18 : n <= 60 ? 0.12 : 0.08;
    fg.d3Force("x", forceX(0).strength(g) as any);
    fg.d3Force("y", forceY(0).strength(g) as any);
    fg.d3Force("collide", forceCollide<any>().radius((d: any) => (d.radius ?? 4) + 2.5).strength(0.7) as any);
    if (typeof fg.d3ReheatSimulation === "function") fg.d3ReheatSimulation();
  }, [colored]);

  const gStats: GraphStats | null = view?.global_stats ?? null;
  useEffect(() => {
    if (!playing || !gStats) return;
    const min = gStats.min_year, max = gStats.max_year;
    if (min == null || max == null) { setPlaying(false); return; }
    const id = setInterval(() => {
      setYearCut((y) => {
        const next = (y ?? min) + 1;
        if (next >= max) { setPlaying(false); return null; }
        return next;
      });
    }, 700);
    return () => clearInterval(id);
  }, [playing, gStats]);

  const glowSprite = (color: string) => {
    let s = glowCache.current.get(color);
    if (!s) {
      s = document.createElement("canvas");
      s.width = s.height = 64;
      const c = s.getContext("2d")!;
      const g = c.createRadialGradient(32, 32, 0, 32, 32, 32);
      g.addColorStop(0, hexToRgba(color, 0.28));
      g.addColorStop(1, hexToRgba(color, 0));
      c.fillStyle = g;
      c.fillRect(0, 0, 64, 64);
      glowCache.current.set(color, s);
    }
    return s;
  };

  const nodeAlpha = (id: string) => {
    const fx = fxRef.current;
    if (fx.path) return fx.path.nodes.has(id) ? 1 : 0.10;
    if (fx.focus) return fx.focus.has(id) ? 1 : 0.10;
    if (fx.hl) return fx.hl.has(id) ? 1 : 0.15;
    return 1;
  };

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    if (typeof node.x !== "number" || typeof node.y !== "number" || !isFinite(node.x) || !isFinite(node.y)) return;
    const r = node.radius ?? 5;
    const color = node.color ?? "#94a3b8";
    const a = nodeAlpha(node.id);
    const glow = r * CFG.glowMultiplier;
    if (theme === "light") {
      ctx.globalCompositeOperation = "multiply";
      ctx.globalAlpha = a * 0.55;
      ctx.drawImage(glowSprite(color), node.x - glow, node.y - glow, glow * 2, glow * 2);
      ctx.globalCompositeOperation = "source-over";
    } else {
      ctx.globalAlpha = a;
      ctx.drawImage(glowSprite(color), node.x - glow, node.y - glow, glow * 2, glow * 2);
    }
    ctx.globalAlpha = a;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = T.rim;
    ctx.lineWidth = T.rimWidth;
    ctx.stroke();
    if (node.type === "paper" && node.source === "user_upload") {
      ctx.strokeStyle = T.uploadRing;
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
    if (fxRef.current.focusId === node.id) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 2.2, 0, 2 * Math.PI);
      ctx.strokeStyle = T.uploadRing;
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    if (a < 0.5) return;
    const lz = r >= 9 ? 0.9 : r >= 6.5 ? 1.8 : 2.8;
    const isHub = (node.degree ?? 0) >= CFG.hubLabelDegree;
    const inFocus = fxRef.current.focus?.has(node.id) ?? false;
    const show = !labelsAuto
      ? true
      : (isHub && globalScale >= 0.9) || globalScale >= lz || inFocus
        || selectedNode?.id === node.id || fxRef.current.focusId === node.id;
    if (!show) return;
    const fontSize = Math.max(3.5, 11 / globalScale);
    const maxChars = node.type === "paper" ? 32 : 20;
    if (node._label == null) {
      const raw: string = node.name ?? " ";
      node._label = raw.length > maxChars ? raw.slice(0, maxChars - 1) + "\u2026" : raw;
      node._weight = node.type === "paper" ? 600 : 500;
      ctx.font = `${node._weight} 10px ui-sans-serif, system-ui`;
      node._lw = ctx.measureText(node._label).width;
    }
    const w = node._lw * (fontSize / 10);
    const padX = 2.5, padY = 1.2;
    ctx.fillStyle = T.labelBg;
    ctx.fillRect(node.x - w / 2 - padX, node.y + r + 2, w + padX * 2, fontSize + padY * 2);
    if (T.labelBorder) {
      ctx.strokeStyle = T.labelBorder;
      ctx.lineWidth = 0.5;
      ctx.strokeRect(node.x - w / 2 - padX, node.y + r + 2, w + padX * 2, fontSize + padY * 2);
    }
    ctx.fillStyle = T.labelText;
    ctx.font = `${node._weight} ${fontSize}px ui-sans-serif, system-ui`;
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText(node._label, node.x, node.y + r + 2 + padY);
  }, [labelsAuto, selectedNode, theme]);

  const paintLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const s = link.source, t = link.target;
    if (typeof s !== "object" || typeof t !== "object" || !s || !t) return;
    if (typeof s.x !== "number" || typeof t.x !== "number" || !isFinite(s.x) || !isFinite(t.x)) return;
    const fx = fxRef.current;
    const key = linkKey(link.sourceId, link.targetId);
    let a = 1;
    if (fx.path) a = fx.path.links.has(key) ? 1 : 0.06;
    else if (fx.focusId) a = (link.sourceId === fx.focusId || link.targetId === fx.focusId) ? 1 : 0.06;
    else if (fx.hl) a = fx.hl.has(link.sourceId) && fx.hl.has(link.targetId) ? 1 : 0.10;
    if (a < 0.5) return;
    if (globalScale < CFG.linkLabelZoom) return;
    const label = LINK_LABELS[link.type] ?? link.type;
    if (!label) return;
    const midX = (s.x + t.x) / 2, midY = (s.y + t.y) / 2;
    const fontSize = Math.max(2.8, 9 / globalScale);
    ctx.font = `500 ${fontSize}px ui-sans-serif, system-ui`;
    const w = ctx.measureText(label).width;
    const padX = 2, padY = 1;
    ctx.fillStyle = T.linkLabelBg;
    ctx.fillRect(midX - w / 2 - padX, midY - fontSize / 2 - padY, w + padX * 2, fontSize + padY * 2);
    ctx.fillStyle = T.linkText[link.type] ?? T.linkText.default;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(label, midX, midY);
  }, [theme]);

  const paintPointer = useCallback((node: any, color: string, ctx: CanvasRenderingContext2D) => {
    if (typeof node.x !== "number" || typeof node.y !== "number" || !isFinite(node.x) || !isFinite(node.y)) return;
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(node.x, node.y, (node.radius ?? 5) + 3, 0, 2 * Math.PI); ctx.fill();
  }, []);
  const paintLinkPointer = useCallback((link: any, color: string, ctx: CanvasRenderingContext2D) => {
    const s = link.source, t = link.target;
    if (typeof s !== "object" || typeof t !== "object") return;
    ctx.strokeStyle = color; ctx.lineWidth = 6;
    ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y); ctx.stroke();
  }, []);
  const cachePositions = useCallback(() => {
    for (const n of liveNodesRef.current) {
      if (typeof n.x === "number" && typeof n.y === "number") posCache.set(n.id, { x: n.x, y: n.y });
    }
  }, []);

  useEffect(() => () => cachePositions(), [cachePositions]);
  const spotlightMany = (ids: string[]) => {
    const tryIt = (attempt = 0) => {
      const objs = liveNodesRef.current.filter((n) => ids.includes(n.id) && typeof n.x === "number");
      if (!objs.length) { if (attempt < 6) setTimeout(() => tryIt(attempt + 1), 250); return; }
      const cx = objs.reduce((s, n) => s + (n.x ?? 0), 0) / objs.length;
      const cy = objs.reduce((s, n) => s + (n.y ?? 0), 0) / objs.length;
      const fg = fgRef.current; if (!fg) return;
      if (typeof fg.centerAt === "function") fg.centerAt(cx, cy, 600);
      if (typeof fg.zoom === "function") fg.zoom(1.8, 600);
    };
    tryIt();
  };

  const requestPath = async (a: RichNode, b: RichNode) => {
    try {
      const res = await api.graphPath(sessionId, {
        a: a.id, b: b.id, scope,
        paper_links: scope === "message" ? (messagePaperLinks ?? []) : undefined,
        max_year: yearCut,
      });
      if (!res.path) { setPathResult(null); return; }
      setPathResult({
        nodes: new Set(res.path.nodes),
        links: new Set(res.path.links.map(([s, t]) => linkKey(s, t))),
        hops: res.path.hops,
        chain: res.path.nodes,
      });
      setTrail([]); setHighlightSet(null);
    } catch { setPathResult(null); }
  };

  const onNodeClick = (n: any) => {
    if (pathMode) {
      if (!pathA) { setPathA(n); return; }
      setPathMode(false); setPathA(null);
      void requestPath(pathA, n);
      return;
    }
    if (trail.length === 1 && trail[0].id === n.id) {
      setSelectedNode(null);
      setTrail([]);
      return;
    }
    setSelectedNode(n);
    setTrail([n]);
  };

  const drillTo = (n: RichNode) => {
    setSelectedNode(n);
    setTrail((prev) => [...prev.filter((p) => p.id !== n.id), n]);
  };
  
  const onBackgroundClick = () => {
    setSelectedNode(null); setHighlightSet(null); setPathResult(null); 
    setPathA(null); setPathMode(false); setTrail([]);
  };

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { 
        setPathMode(false); setPathA(null); 
        setTrail([]); setSelectedNode(null); setHighlightSet(null); setPathResult(null);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  useEffect(() => {
    const q = searchQ.trim();
    if (q.length < 2) { setSugs(null); return; }
    const t = setTimeout(() => {
      api.suggestGraph(sessionId, q).then((r) => setSugs(r.matches)).catch(() => setSugs(null));
    }, 180);
    return () => clearTimeout(t);
  }, [searchQ, sessionId]);

  const onSearchSubmit = async () => {
    const q = searchQ.trim(); if (!q) return;
    setSugOpen(false); setSearching(true);
    try {
      const res = await api.queryGraph(sessionId, q);
      const ids = res.matches.filter((m) => m.score > 0.25).map((m) => m.id);
      if (ids.length) { setHighlightSet(new Set(ids)); setTrail([]); spotlightMany(ids); }
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  const selectSug = (m: SuggestMatch) => {
    const n = colored?.nodeById.get(m.id);
    setSugs(null); setSugOpen(false); setSearchQ("");
    if (n) {
      setSelectedNode(n); setTrail([n]);
      spotlightMany([m.id]);
    } else {
      pendingSpotlightRef.current = m.id;
      if (scope === "message") setScope("conversation");
    }
  };

  const zoomBy = (f: number) => { const fg = fgRef.current; if (fg && typeof fg.zoom === "function") fg.zoom(fg.zoom() * f, 220); };
  const fit = () => { const fg = fgRef.current; if (fg && typeof fg.zoomToFit === "function") fg.zoomToFit(350, 50); };
  const ctrlBtn = `flex h-7 w-7 items-center justify-center rounded-md transition-colors ${ui.btn}`;
  const st = visible?.stats ?? null;
  const rel: NodeRel | null = selectedNode ? view?.rel?.[selectedNode.id] ?? null : null;
  const legendColor = (e: LegendEntry) =>
    e.cluster != null ? CFG.palette[e.cluster % CFG.palette.length]
    : e.kind === "method" ? CFG.methodColor
    : e.kind === "dataset" ? CFG.datasetColor
    : CFG.paperFallbackColor;

  return (
    <div className="h-full w-full p-3">
      <div className="relative h-full w-full overflow-hidden rounded-2xl border border-[#1c2536] flex flex-col"
        style={{ background: T.canvasBg }}
        onMouseMove={(e) => {
          const r = containerRef.current?.getBoundingClientRect();
          if (!r) return;
          mouseRef.current = { x: e.clientX - r.left, y: e.clientY - r.top };
          if (tooltipRef.current) {
            tooltipRef.current.style.transform = `translate(${mouseRef.current.x + 12}px, ${mouseRef.current.y + 12}px)`;
          }
        }}>
        {/* scope toggle */}
        <div className={`flex items-center gap-1 px-3 py-1.5 shrink-0 border-b ${theme === "dark" ? "border-white/5" : "border-slate-900/10"}`}>
          <button onClick={() => activeTurnId && setScope("message")} disabled={!activeTurnId}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${scope === "message" ? "bg-indigo-500 text-white" : `${ui.dim} hover:bg-white/5 ${theme === "dark" ? "hover:text-white/80" : "hover:text-slate-700"} disabled:opacity-40`}`}>
            <MessageSquare className="h-3 w-3" /> This Message
          </button>
          <button onClick={() => setScope("conversation")}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${scope === "conversation" ? "bg-indigo-500 text-white" : `${ui.dim} hover:bg-white/5 ${theme === "dark" ? "hover:text-white/80" : "hover:text-slate-700"}`}`}>
            <Network className="h-3 w-3" /> Whole Conversation
          </button>
          <span className={`ml-auto text-[10.5px] ${ui.faint}`}>
            {st ? `${st.nodes} nodes · ${st.links} links · density ${st.density.toFixed(2)} · avg deg ${st.avg_degree.toFixed(1)}` : ""}
          </span>
        </div>

        <div ref={containerRef} className="flex-1 min-h-0 relative">
          {graphDataObj && (
            <ForceGraph2D
              ref={fgRef}
              graphData={graphDataObj}
              backgroundColor="rgba(0,0,0,0)"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={paintPointer}
              linkCanvasObject={paintLink}
              linkCanvasObjectMode={() => "after"}
              linkPointerAreaPaint={paintLinkPointer}
              linkColor={(l: any) => hexToRgba(l.color ?? "#94a3b8", l.type === "similar" || l.type === "cites" ? linkAlpha.strong : linkAlpha.normal)}
              linkLineDash={(l: any) => l.dash}
              linkWidth={(l: any) =>
                fxRef.current.path?.links.has(linkKey(l.sourceId, l.targetId)) ? 2
                : l.type === "similar" || l.type === "cites" ? 1.2 : 0.6}
              linkCurvature={0.12}
              linkDirectionalArrowLength={(l: any) => (l.type === "cites" ? 4 : 0)}
              linkDirectionalArrowRelPos={0.9}
              d3AlphaDecay={physicsOn ? 0.02 : 0.6}
              warmupTicks={60}
              d3VelocityDecay={0.5}
              minZoom={0.35}
              maxZoom={6}
              onNodeClick={onNodeClick}
              nodeLabel={() => ""}
              onLinkHover={(l: any) => setHoverLink(l ?? null)}
              onBackgroundClick={onBackgroundClick}
              onEngineStop={() => {
                cachePositions();
                if (!fittedOnce.current) {
                  fittedOnce.current = true;
                  const fg = fgRef.current;
                  if (fg && typeof fg.zoomToFit === "function") fg.zoomToFit(400, 50);
                }
              }}
              width={dims.width}
              height={dims.height}
            />
          )}

          {hoverLink && (
            <div ref={tooltipRef}
              className={`pointer-events-none absolute left-0 top-0 z-20 rounded-md border px-2.5 py-1.5 text-[10.5px] ${ui.card} ${ui.text}`}>
              <span className="font-medium">
                {hoverLink.type === "similar" ? `similar to ${(hoverLink.weight ?? 0).toFixed(2)}` : LINK_LABELS[hoverLink.type] ?? hoverLink.type}
              </span>
              {hoverLink.type === "similar" && (
                <span className={`ml-1.5 ${ui.dim}`}>
                  {(hoverLink.weight ?? 0) >= 0.75 ? "high confidence" : (hoverLink.weight ?? 0) >= 0.6 ? "medium" : "weak"}
                </span>
              )}
            </div>
          )}

          {/* search + typeahead */}
          <div className="absolute top-3 left-3 w-72">
            <div className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 ${ui.panel}`}>
              {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin opacity-50" /> : <Search className={`h-3.5 w-3.5 ${ui.faint}`} />}
              <input value={searchQ}
                onChange={(e) => { setSearchQ(e.target.value); setSugOpen(true); }}
                onFocus={() => setSugOpen(true)}
                onBlur={() => setTimeout(() => setSugOpen(false), 120)}
                onKeyDown={(e) => { if (e.key === "Enter") onSearchSubmit(); if (e.key === "Escape") { setSearchQ(""); setSugs(null); } }}
                placeholder="Ask the graph… e.g. multimodal explainability"
                className={`w-full bg-transparent text-[11.5px] outline-none ${ui.input}`} />
            </div>
            {sugOpen && sugs && sugs.length > 0 && (
              <div className={`mt-1 overflow-hidden rounded-lg border shadow-xl ${ui.card}`}>
                {sugs.map((m) => (
                  <button key={m.id} onMouseDown={() => selectSug(m)}
                    className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] ${ui.text} ${ui.hoverRow}`}>
                    <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${ui.chip}`}>{m.type}</span>
                    <span className="truncate">{m.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* breadcrumb */}
          {(trail.length > 0 || pathResult) && (
            <div className={`absolute top-14 left-3 flex max-w-[70%] items-center gap-1 overflow-hidden rounded-lg border px-2 py-1 ${ui.panel}`}>
              <button onClick={() => { setTrail([]); setSelectedNode(null); setPathResult(null); }}
                className="shrink-0 text-[10.5px] text-indigo-300 hover:text-indigo-200">Galaxy</button>
              {pathResult ? (
                <>
                  {pathResult.chain.map((id, i) => {
                    const n = colored?.nodeById.get(id);
                    return (
                      <span key={id} className="flex min-w-0 items-center gap-1">
                        <ChevronRight className={`h-3 w-3 shrink-0 ${ui.faint}`} />
                        <button onClick={() => n && setSelectedNode(n)}
                          className={`truncate text-[10.5px] ${i === pathResult.chain.length - 1 ? (theme === "dark" ? "text-white/90" : "text-slate-800") : ui.dim}`}>
                          {n?.name ?? id}
                        </button>
                      </span>
                    );
                  })}
                  <span className="ml-2 flex shrink-0 items-center gap-1 text-[10.5px] text-emerald-300">
                    path · {pathResult.hops} hops
                    <button onClick={() => setPathResult(null)} className={`${ui.dim} hover:opacity-100`}><X className="h-3 w-3" /></button>
                  </span>
                </>
              ) : (
                trail.map((t, i) => (
                  <span key={t.id} className="flex min-w-0 items-center gap-1">
                    <ChevronRight className={`h-3 w-3 shrink-0 ${ui.faint}`} />
                    <button onClick={() => { setTrail(trail.slice(0, i + 1)); setSelectedNode(t); }}
                      className={`truncate text-[10.5px] ${i === trail.length - 1 ? (theme === "dark" ? "text-white/90" : "text-slate-800") : ui.dim}`}>
                      {t.name}
                    </button>
                  </span>
                ))
              )}
            </div>
          )}

          {/* controls */}
          <div className={`absolute top-3 right-3 z-20 flex flex-col gap-0.5 rounded-lg border p-1 ${ui.panel}`}>
            <button className={ctrlBtn} title="Zoom in" onClick={() => zoomBy(1.5)}><ZoomIn className="h-3.5 w-3.5" /></button>
            <button className={ctrlBtn} title="Zoom out" onClick={() => zoomBy(1 / 1.5)}><ZoomOut className="h-3.5 w-3.5" /></button>
            <button className={ctrlBtn} title="Fit to view" onClick={fit}><Maximize2 className="h-3.5 w-3.5" /></button>
            <button className={`${ctrlBtn} ${pathMode || pathA ? "text-emerald-300 bg-white/10" : ""}`}
              title="Trace path: click two nodes (Esc cancels)"
              onClick={() => { setPathMode((v) => !v); setPathA(null); setPathResult(null); }}>
              <Route className="h-3.5 w-3.5" />
            </button>
            <button className={`${ctrlBtn} ${showStats ? (theme === "dark" ? "text-white bg-white/10" : "text-slate-900 bg-slate-900/10") : ""}`}
              title="Graph analytics" onClick={() => setShowStats(v => !v)}>
              <BarChart3 className="h-3.5 w-3.5" />
            </button>
            <button className={ctrlBtn} title={physicsOn ? "Freeze layout" : "Re-run layout"}
              onClick={() => setPhysicsOn((on) => { if (!on && fgRef.current && typeof fgRef.current.d3ReheatSimulation === "function") fgRef.current.d3ReheatSimulation(); return !on; })}>
              {physicsOn ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </button>
            <button className={`${ctrlBtn} ${!labelsAuto ? (theme === "dark" ? "text-white bg-white/10" : "text-slate-900 bg-slate-900/10") : ""}`}
              title={labelsAuto ? "Labels: adaptive (zoom/hub aware)" : "Labels: show all"}
              onClick={() => setLabelsAuto(v => !v)}>
              <Type className="h-3.5 w-3.5" />
            </button>
            <button className={ctrlBtn} title={theme === "dark" ? "Light mode" : "Dark mode"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
            <button className={ctrlBtn} title="Rebuild graph" onClick={rebuild}><RefreshCw className="h-3.5 w-3.5" /></button>
          </div>

         {pathMode && (
            <div className={`absolute top-3 right-14 rounded-md border px-2.5 py-1.5 text-[10.5px] backdrop-blur ${
              theme === "dark"
                ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
                : "border-emerald-600/40 bg-emerald-100/80 text-emerald-800"
            }`}>
              {pathA ? `Now click the target node (from “${pathA.name.slice(0, 24)}…”)` : "Click the start node"}
            </div>
          )}

          {/* stats panel */}
          {showStats && gStats && (
            <div className={`absolute top-3 right-14 w-60 rounded-lg border p-3 ${ui.panel}`}>
              <p className={`mb-2 text-[9.5px] font-semibold uppercase tracking-wider ${ui.faint}`}>Graph analytics</p>
              <div className={`grid grid-cols-2 gap-x-3 gap-y-1.5 text-[10.5px] ${ui.text}`}>
                <span>Papers</span><span className="text-right">{gStats.papers}</span>
                <span>Concepts</span><span className="text-right">{gStats.concepts}</span>
                <span>Methods</span><span className="text-right">{gStats.methods}</span>
                <span>Datasets</span><span className="text-right">{gStats.datasets}</span>
                <span>Relationships</span><span className="text-right">{gStats.links}</span>
                <span>Density</span><span className="text-right">{gStats.density.toFixed(3)}</span>
                <span>Avg degree</span><span className="text-right">{gStats.avg_degree.toFixed(1)}</span>
              </div>
              <div className={`mt-2 border-t pt-2 text-[10.5px] space-y-1 ${theme === "dark" ? "border-white/10" : "border-slate-900/10"} ${ui.text}`}>
                <p>Most central concept: <span>{gStats.top_concept ?? "—"}</span></p>
                {gStats.top_paper && <p>Most cited: <span>{String(gStats.top_paper.name).slice(0, 34)}… ({gStats.top_paper.citation_count})</span></p>}
                {gStats.min_year != null && <p>Span: <span>{gStats.min_year}–{gStats.max_year}</span></p>}
              </div>
            </div>
          )}

          {/* legend */}
          {view && view.legend.length > 0 && (
            <div className={`absolute bottom-3 left-3 rounded-lg border px-3 py-2 ${ui.panel}`}>
              <p className={`mb-1 text-[9.5px] font-semibold uppercase tracking-wider ${ui.faint}`}>Node color = topic cluster · size = influence</p>
              <div className="flex flex-col gap-1">
                {view.legend.map((e) => {
                  const c = legendColor(e);
                  return (
                    <span key={e.name} className={`flex items-center gap-1.5 text-[10.5px] ${ui.dim}`}>
                      <span className="h-2 w-2 rounded-full" style={{ background: c, boxShadow: `0 0 6px ${c}` }} />
                      {e.name}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {/* year timeline */}
          {gStats?.min_year != null && gStats.max_year != null && gStats.max_year - gStats.min_year >= 1 && (
            <div className={`absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-lg border px-3 py-1.5 ${ui.panel}`}>
              <button className={ui.btn}
                onClick={() => { if (playing) { setPlaying(false); } else { setYearCut(gStats.min_year); setPlaying(true); } }}>
                {playing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
              </button>
              <span className={`w-10 text-center text-[10.5px] tabular-nums ${ui.text}`}>{yearCut ?? gStats.max_year}</span>
              <input type="range" min={gStats.min_year} max={gStats.max_year} value={yearCut ?? gStats.max_year}
                onChange={(e) => { setPlaying(false); const v = parseInt(e.target.value, 10); setYearCut(v >= gStats.max_year! ? null : v); }}
                className="w-40 accent-indigo-500" />
              <button className={`text-[10px] ${ui.dim}`} onClick={() => { setYearCut(null); setPlaying(false); }}>all</button>
            </div>
          )}

          {/* detail card */}
          {selectedNode && (
            <div className={`absolute bottom-14 left-1/2 -translate-x-1/2 w-[460px] max-w-[92%] rounded-xl border p-4 shadow-xl z-10 ${ui.card}`}>
              <div className="mb-2 flex items-center gap-2">
                <span className="inline-block rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold text-white"
                  style={{ background: selectedNode.color ?? "#64748b" }}>
                  {selectedNode.type[0].toUpperCase() + selectedNode.type.slice(1)}
                </span>
                {selectedNode.year != null && <span className={`text-[10.5px] ${ui.dim}`}>{selectedNode.year}</span>}
                {selectedNode.citation_count != null && selectedNode.citation_count > 0 && (
                  <span className={`text-[10.5px] ${ui.dim}`}>{selectedNode.citation_count.toLocaleString()} citations</span>
                )}
                <span className={`ml-auto text-[10.5px] ${ui.faint}`}>{selectedNode.degree ?? 0} connections</span>
                <button onClick={() => setSelectedNode(null)} className={`${ui.dim} text-[13px]`}>✕</button>
              </div>
              <p className={`text-[14px] leading-snug ${theme === "dark" ? "text-white" : "text-slate-900"}`}>{selectedNode.name}</p>
              {selectedNode.type === "paper" && (selectedNode.authors?.length ?? 0) > 0 && (
                <p className={`mt-1 truncate text-[11px] ${ui.dim}`}>{selectedNode.authors!.join(", ")}</p>
              )}
              {selectedNode.excerpt && <p className={`mt-2 line-clamp-2 text-[11.5px] leading-relaxed ${ui.dim}`}>{selectedNode.excerpt}</p>}
              {rel && (
                <div className="mt-2.5 space-y-1.5">
                  {rel.concepts.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className={`text-[9.5px] uppercase tracking-wide ${ui.faint}`}>topics</span>
                      {rel.concepts.slice(0, 5).map((c) => <span key={c} className={`rounded-full px-2 py-0.5 text-[10px] ${ui.chip}`}>{c}</span>)}
                    </div>
                  )}
                  {rel.methods.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className={`text-[9.5px] uppercase tracking-wide ${ui.faint}`}>methods</span>
                      {rel.methods.slice(0, 5).map((m) => <span key={m} className={`rounded-full px-2 py-0.5 text-[10px] ${ui.methodChip}`}>{m}</span>)}
                    </div>
                  )}
                  {rel.datasets.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className={`text-[9.5px] uppercase tracking-wide ${ui.faint}`}>datasets</span>
                      {rel.datasets.slice(0, 5).map((d) => <span key={d} className={`rounded-full px-2 py-0.5 text-[10px] ${ui.datasetChip}`}>{d}</span>)}
                    </div>
                  )}
                  {rel.papers.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className={`text-[9.5px] uppercase tracking-wide ${ui.faint}`}>related</span>
                      {rel.papers.slice(0, 3).map((p) => (
                        <button key={p.id}
                          onClick={() => { const n = colored?.nodeById.get(p.id); if (n) drillTo(n); }}
                          className={`max-w-[160px] truncate rounded-full px-2 py-0.5 text-[10px] ${ui.relatedChip}`}>
                          {p.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {selectedNode.type === "paper" && /^https?:/i.test(selectedNode.id) && (
                <a href={selectedNode.id} target="_blank" rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-indigo-500 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-indigo-400">
                  <ExternalLink className="h-3 w-3" /> Open paper
                </a>
              )}
            </div>
          )}

          {loading && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/30">
              <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
              <p className={`text-[12px] ${theme === "dark" ? "text-white/60" : "text-slate-500"}`}>Mapping your research galaxy…</p>
            </div>
          )}
          {!loading && error && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3">
              <AlertTriangle className="h-5 w-5 text-red-400" />
              <p className={`text-[12px] ${theme === "dark" ? "text-white/60" : "text-slate-500"}`}>{error}</p>
              <button onClick={() => setNonce(n => n + 1)} className="pointer-events-auto rounded-md bg-indigo-500 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-indigo-400">Retry</button>
            </div>
          )}
          {!loading && !error && (!visible || visible.nodes.length === 0) && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <p className={`text-[12.5px] ${theme === "dark" ? "text-white/50" : "text-slate-500"}`}>
                {scope === "message" ? "No papers were surfaced in this message. Switch to Whole Conversation."
                  : yearCut != null ? "Nothing published this early yet — drag the year slider right."
                  : "No graph yet. Ask a research question or upload a paper, then explore."}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}