"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Loader2, MessageSquare, Network, ZoomIn, ZoomOut, Maximize2, Pause, Play,
  Type, RefreshCw, AlertTriangle, Search, BarChart3, Route, ExternalLink,
  ChevronRight, X, Square,
} from "lucide-react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { FullGraphData, GraphNode, GraphScope } from "@/lib/types";
import { GRAPH_CONFIG as CFG } from "@/lib/GraphConfig";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type RichNode = GraphNode & {
  degree?: number; color?: string; radius?: number; year?: number | null;
};

type RichLink = {
  source: any; target: any; type: string; weight?: number;
  sourceId: string; targetId: string; color: string; dash: number[] | null;
};

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


export function GraphView({
  sessionId, activeTurnId, messagePaperLinks,
}: {
  sessionId: string;
  activeTurnId?: string | null;
  messagePaperLinks?: string[];
}) {
  const [scope, setScope] = useState<GraphScope>(activeTurnId ? "message" : "conversation");
  const [graphData, setGraphData] = useState<FullGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [labelsAuto, setLabelsAuto] = useState(true);
  const [physicsOn, setPhysicsOn] = useState(true);
  const [selectedNode, setSelectedNode] = useState<RichNode | null>(null);
  const [trail, setTrail] = useState<RichNode[]>([]);
  const [highlightSet, setHighlightSet] = useState<Set<string> | null>(null);
  const [pathMode, setPathMode] = useState(false);
  const [pathA, setPathA] = useState<RichNode | null>(null);
  const [pathResult, setPathResult] = useState<{ nodes: Set<string>; links: Set<string>; hops: number } | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [yearCut, setYearCut] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searching, setSearching] = useState(false);
  const [hoverLink, setHoverLink] = useState<RichLink | null>(null);
  const mouseRef = useRef({ x: 0, y: 0 });
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 800, height: 600 });
  const fittedOnce = useRef(false);
  const metaRef = useRef({ small: true });
  const fxRef = useRef<{ focus: Set<string> | null; focusId: string | null; hl: Set<string> | null; path: { nodes: Set<string>; links: Set<string> } | null }>(
    { focus: null, focusId: null, hl: null, path: null }
  );

  const load = useCallback((force = false) => {
    setLoading(true); setError(null); setSelectedNode(null); setTrail([]);
    setHighlightSet(null); setPathResult(null);
    api.ensureGraph(sessionId, force)
      .then(setGraphData)
      .catch((e) => setError(e?.message ?? "Could not build the knowledge graph."))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => { fittedOnce.current = false; load(false); }, [load]);
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

  const enriched = useMemo(() => {
    if (!graphData) return null;
    const ids = new Set(graphData.nodes.map((n) => n.id));
    const links: RichLink[] = graphData.links
      .filter((l) => ids.has(l.source) && ids.has(l.target))
      .map((l) => ({
        ...l, sourceId: l.source, targetId: l.target,
        color:
          l.type === "uses" ? CFG.edgeColors.uses
          : l.type === "evaluates" ? CFG.edgeColors.evaluates
          : l.type === "cites" ? CFG.edgeColors.cites
          : l.type === "similar" ? CFG.edgeColors.similar
          : CFG.conceptFallbackColor,
        dash: l.type === "similar" ? CFG.dashForWeight(l.weight ?? 0.6) : null,
      }));
    const degree: Record<string, number> = {};
    for (const l of links) {
      degree[l.sourceId] = (degree[l.sourceId] ?? 0) + 1;
      degree[l.targetId] = (degree[l.targetId] ?? 0) + 1;
    }
    const concepts = graphData.nodes.filter((n) => n.type === "concept")
      .sort((a, b) => (degree[b.id] ?? 0) - (degree[a.id] ?? 0));
    const conceptColor: Record<string, string> = {};
    concepts.forEach((c, i) => (conceptColor[c.id] = CFG.palette[i % CFG.palette.length]));
    for (const l of links) {
      if (l.type === "discusses" && conceptColor[l.targetId]) l.color = conceptColor[l.targetId];
    }
    const paperColor: Record<string, string> = {};
    for (const l of links) {
      if (l.type === "discusses" && !paperColor[l.sourceId] && conceptColor[l.targetId]) {
        paperColor[l.sourceId] = conceptColor[l.targetId];
      }
    }
    const nodes: RichNode[] = graphData.nodes.map((n) => {
      const deg = degree[n.id] ?? 0;
      let color: string, radius: number;
      if (n.type === "paper") {
        color = paperColor[n.id] ?? CFG.paperFallbackColor;
        radius = 4.5 + Math.min(Math.log1p(n.citation_count ?? 0) * 1.1, 6) + Math.min(deg, 6) * 0.45;
      } else if (n.type === "concept") {
        color = conceptColor[n.id] ?? CFG.conceptFallbackColor;
        radius = 3.5 + Math.min(deg, 16) * 0.55;
      } else if (n.type === "method") {
        color = CFG.methodColor; radius = 3 + Math.min(deg, 10) * 0.4;
      } else {
        color = CFG.datasetColor; radius = 3 + Math.min(deg, 10) * 0.4;
      }
      const year = parseInt(String(n.published ?? "").slice(0, 4), 10);
      return { ...n, degree: deg, color, radius, year: isNaN(year) ? null : year };
    });
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const rel: Record<string, { concepts: string[]; methods: string[]; datasets: string[]; papers: { id: string; name: string }[] }> = {};
    const relOf = (id: string) => (rel[id] ??= { concepts: [], methods: [], datasets: [], papers: [] });
    for (const l of links) {
      const t = nodeById.get(l.targetId);
      const s = nodeById.get(l.sourceId);
      if (!t || !s) continue;
      if (l.type === "discusses") relOf(l.sourceId).concepts.push(t.name);
      else if (l.type === "uses") relOf(l.sourceId).methods.push(t.name);
      else if (l.type === "evaluates") relOf(l.sourceId).datasets.push(t.name);
      else if (l.type === "cites" || l.type === "similar") relOf(l.sourceId).papers.push({ id: t.id, name: t.name });
      if (l.type === "cites" || l.type === "similar") relOf(l.targetId).papers.push({ id: s.id, name: s.name });
    }
    const papers = nodes.filter((n) => n.type === "paper");
    const years = papers.map((p) => p.year).filter((y): y is number => y != null);
    const stats = {
      nodes: nodes.length, links: links.length,
      papers: papers.length, concepts: concepts.length,
      methods: nodes.filter((n) => n.type === "method").length,
      datasets: nodes.filter((n) => n.type === "dataset").length,
      density: nodes.length > 1 ? (2 * links.length) / (nodes.length * (nodes.length - 1)) : 0,
      avgDegree: nodes.length ? (2 * links.length) / nodes.length : 0,
      topConcept: concepts[0]?.name ?? "—",
      topPaper: [...papers].sort((a, b) => (b.citation_count ?? 0) - (a.citation_count ?? 0))[0],
      minYear: years.length ? Math.min(...years) : null,
      maxYear: years.length ? Math.max(...years) : null,
    };
    const legend = [
      ...concepts.slice(0, 5).map((c) => ({ name: c.name, color: conceptColor[c.id] })),
      { name: "methods", color: CFG.methodColor },
      { name: "datasets", color: CFG.datasetColor },
      { name: "unclustered papers", color: CFG.paperFallbackColor },
    ];
    return { nodes, links, legend, stats, rel };
  }, [graphData]);

  const visible = useMemo(() => {
    if (!enriched) return null;
    let nodes = enriched.nodes;
    let links = enriched.links;
    if (scope === "message" && messagePaperLinks?.length) {
      const keep = new Set<string>();
      for (const n of nodes) if (n.type === "paper" && messagePaperLinks.includes(n.id)) keep.add(n.id);
      for (const l of links) if (keep.has(l.sourceId) || keep.has(l.targetId)) { keep.add(l.sourceId); keep.add(l.targetId); }
      nodes = nodes.filter((n) => keep.has(n.id));
      links = links.filter((l) => keep.has(l.sourceId) && keep.has(l.targetId));
    }
    if (yearCut != null && enriched.stats.maxYear != null && yearCut < enriched.stats.maxYear) {
      const keep = new Set<string>();
      for (const n of nodes) {
        if (n.type === "paper") { if (n.year == null || n.year <= yearCut) keep.add(n.id); }
      }
      for (const l of links) {
        const s = nodes.find((n) => n.id === l.sourceId);
        const t = nodes.find((n) => n.id === l.targetId);
        const touchesKeptPaper =
          (keep.has(l.sourceId) && (t?.type !== "paper" || keep.has(l.targetId))) ||
          (keep.has(l.targetId) && (s?.type !== "paper" || keep.has(l.sourceId)));
        if (touchesKeptPaper) { keep.add(l.sourceId); keep.add(l.targetId); }
      }
      nodes = nodes.filter((n) => keep.has(n.id));
      links = links.filter((l) => keep.has(l.sourceId) && keep.has(l.targetId));
    }
    return { ...enriched, nodes, links };
  }, [enriched, scope, messagePaperLinks, yearCut]);

  useEffect(() => {
    metaRef.current.small = (visible?.nodes.length ?? 0) <= 60;
    fittedOnce.current = false;
  }, [visible]);

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
    if (!fg || !visible?.nodes.length) return;
    const n = visible.nodes.length;
    const charge = fg.d3Force("charge");
    if (charge) { charge.strength(n <= 40 ? -60 : CFG.chargeStrength); charge.distanceMax(n <= 40 ? 180 : 320); }
    const scale = n <= 30 ? 0.7 : 1;
    fg.d3Force("link")?.distance((l: any) => (CFG.linkDistance[l.type] ?? 30) * scale);
    fg.d3ReheatSimulation();
  }, [visible]);

  useEffect(() => {
    if (!playing || !enriched) return;
    const min = enriched.stats.minYear, max = enriched.stats.maxYear;
    if (min == null || max == null) { setPlaying(false); return; }
    const id = setInterval(() => {
      setYearCut((y) => {
        const next = (y ?? min) + 1;
        if (next >= max) { setPlaying(false); return null; }
        return next;
      });
    }, 700);
    return () => clearInterval(id);
  }, [playing, enriched]);

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
    ctx.globalAlpha = a;

    // soft halo (kept — this is what makes hubs "glow" like the reference)
    const glow = r * CFG.glowMultiplier;
    const g = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, glow);
    g.addColorStop(0, hexToRgba(color, 0.28));
    g.addColorStop(1, hexToRgba(color, 0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(node.x, node.y, glow, 0, 2 * Math.PI); ctx.fill();

    // ✅ uniform circular geometry for every node type
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // hairline rim so circles read crisply on the dark canvas (professional finish)
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.lineWidth = 0.75;
    ctx.stroke();

    // user-uploaded papers keep a stronger ring (meaning now encoded by ring, not shape)
    if (node.type === "paper" && node.source === "user_upload") {
      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    if (a < 0.5) return;
    const lz = r >= 9 ? 0.6 : r >= 6.5 ? 1.5 : 2.6;
    const isHub = (node.degree ?? 0) >= CFG.hubLabelDegree;
    const show = !labelsAuto || isHub || metaRef.current.small || globalScale >= lz ||
      selectedNode?.id === node.id || fxRef.current.focusId === node.id;
    if (!show) return;
    const fontSize = Math.max(3.5, 11 / globalScale);
    const maxChars = node.type === "paper" ? 32 : 20;
    const raw: string = node.name ?? " ";
    const label = raw.length > maxChars ? raw.slice(0, maxChars - 1) + "\u2026" : raw;
    ctx.font = `${node.type === "paper" ? 600 : 500} ${fontSize}px ui-sans-serif, system-ui`;
    const w = ctx.measureText(label).width;
    const padX = 2.5, padY = 1.2;
    ctx.fillStyle = "rgba(7,10,16,0.78)";
    ctx.fillRect(node.x - w / 2 - padX, node.y + r + 2, w + padX * 2, fontSize + padY * 2);
    ctx.fillStyle = "rgba(235,240,250,0.92)";
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText(label, node.x, node.y + r + 2 + padY);
  }, [labelsAuto, selectedNode]);

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
    if (!metaRef.current.small && globalScale < CFG.linkLabelZoom) return;
    if (metaRef.current.small && globalScale < 0.7) return;
    const label = LINK_LABELS[link.type] ?? link.type;
    if (!label) return;
    const midX = (s.x + t.x) / 2, midY = (s.y + t.y) / 2;
    const fontSize = Math.max(2.8, 9 / globalScale);
    ctx.font = `500 ${fontSize}px ui-sans-serif, system-ui`;
    const w = ctx.measureText(label).width;
    const padX = 2, padY = 1;
    ctx.fillStyle = "rgba(7,10,16,0.70)";
    ctx.fillRect(midX - w / 2 - padX, midY - fontSize / 2 - padY, w + padX * 2, fontSize + padY * 2);
    ctx.fillStyle =
      link.type === "cites" ? "rgba(248,113,113,0.95)"
      : link.type === "similar" ? "rgba(129,140,248,0.95)"
      : link.type === "evaluates" ? "rgba(34,211,238,0.90)"
      : link.type === "uses" ? "rgba(251,191,36,0.90)"
      : "rgba(203,213,225,0.80)";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(label, midX, midY);
  }, []);

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

  const bfsPath = (a: RichNode, b: RichNode) => {
    if (!visible) return null;
    const adj: Record<string, { to: string; key: string }[]> = {};
    for (const l of visible.links) {
      (adj[l.sourceId] ??= []).push({ to: l.targetId, key: linkKey(l.sourceId, l.targetId) });
      (adj[l.targetId] ??= []).push({ to: l.sourceId, key: linkKey(l.sourceId, l.targetId) });
    }
    const prev: Record<string, { from: string; key: string }> = {};
    const q = [a.id];
    const seen = new Set([a.id]);
    while (q.length) {
      const cur = q.shift()!;
      if (cur === b.id) break;
      for (const { to, key } of adj[cur] ?? []) {
        if (seen.has(to)) continue;
        seen.add(to); prev[to] = { from: cur, key }; q.push(to);
      }
    }
    if (!seen.has(b.id)) return null;
    const nodes = new Set<string>(); const links = new Set<string>();
    let cur = b.id; nodes.add(cur); let hops = 0;
    while (cur !== a.id) { const p = prev[cur]; links.add(p.key); nodes.add(p.from); cur = p.from; hops++; }
    return { nodes, links, hops };
  };

  const onNodeClick = (n: any) => {
    if (pathMode) {
      if (!pathA) { setPathA(n); return; }
      const res = bfsPath(pathA, n);
      setPathResult(res ?? null);
      setPathMode(false); setPathA(null);
      if (!res) setSelectedNode(null);
      return;
    }
    setSelectedNode(n);
    setTrail((prev) => [...prev.filter((p) => p.id !== n.id), n]);
  };

  const onBackgroundClick = () => {
    setSelectedNode(null); setHighlightSet(null); setPathResult(null); setPathA(null); setPathMode(false);
  };

  const spotlightMany = (ids: string[]) => {
    const fg = fgRef.current; if (!fg) return;
    const objs = (fg.graphData()?.nodes ?? []).filter((n: any) => ids.includes(n.id) && typeof n.x === "number");
    if (!objs.length) return;
    const cx = objs.reduce((s: number, n: any) => s + n.x, 0) / objs.length;
    const cy = objs.reduce((s: number, n: any) => s + n.y, 0) / objs.length;
    fg.centerAt(cx, cy, 600); fg.zoom(1.8, 600);
  };

  const onSearchSubmit = async () => {
    const q = searchQ.trim(); if (!q) return;
    setSearching(true);
    try {
      const res = await api.queryGraph(sessionId, q);
      const ids = res.matches.filter((m) => m.score > 0.25).map((m) => m.id);
      if (ids.length) { setHighlightSet(new Set(ids)); setTrail([]); spotlightMany(ids); }
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  const zoomBy = (f: number) => { const fg = fgRef.current; if (fg) fg.zoom(fg.zoom() * f, 220); };
  const fit = () => fgRef.current?.zoomToFit(350, 60);

  const ctrlBtn = "flex h-7 w-7 items-center justify-center rounded-md text-white/70 hover:bg-white/10 hover:text-white transition-colors";
  const st = visible?.stats;
  const rel = selectedNode ? visible?.rel?.[selectedNode.id] : null;

  const ScopeToggle = (
    <div className="flex items-center gap-1 px-3 py-1.5 shrink-0 border-b border-white/5">
      <button onClick={() => activeTurnId && setScope("message")} disabled={!activeTurnId}
        className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${scope === "message" ? "bg-indigo-500 text-white" : "text-white/50 hover:bg-white/5 hover:text-white/80 disabled:opacity-40"}`}>
        <MessageSquare className="h-3 w-3" /> This Message
      </button>
      <button onClick={() => setScope("conversation")}
        className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${scope === "conversation" ? "bg-indigo-500 text-white" : "text-white/50 hover:bg-white/5 hover:text-white/80"}`}>
        <Network className="h-3 w-3" /> Whole Conversation
      </button>
      <span className="ml-auto text-[10.5px] text-white/40">
        {visible ? `${visible.nodes.length} nodes · ${visible.links.length} links · density ${st!.density.toFixed(2)} · avg deg ${st!.avgDegree.toFixed(1)}` : ""}
      </span>
    </div>
  );

  return (
    <div className="h-full w-full p-3">
      <div className="relative h-full w-full overflow-hidden rounded-2xl border border-[#1c2536] flex flex-col"
        style={{ background: "radial-gradient(120% 90% at 75% 10%, #131b2c 0%, #0b101b 48%, #070a12 100%)" }}
        onMouseMove={(e) => {
          const r = containerRef.current?.getBoundingClientRect();
          if (r) mouseRef.current = { x: e.clientX - r.left, y: e.clientY - r.top };
        }}>
        {ScopeToggle}
        <div ref={containerRef} className="flex-1 min-h-0 relative">
          {visible && visible.nodes.length > 0 && (
            <ForceGraph2D
              ref={fgRef}
              graphData={{ nodes: visible.nodes as any, links: visible.links as any }}
              backgroundColor="rgba(0,0,0,0)"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={paintPointer}
              linkCanvasObject={paintLink}
              linkCanvasObjectMode={() => "after"}
              linkPointerAreaPaint={paintLinkPointer}
              linkColor={(l: any) => hexToRgba(l.color ?? "#94a3b8", l.type === "similar" || l.type === "cites" ? 0.45 : 0.28)}
              linkLineDash={(l: any) => l.dash}
              linkWidth={(l: any) => (l.type === "similar" || l.type === "cites" ? 1.2 : 0.6)}
              linkCurvature={0.12}
              linkDirectionalArrowLength={(l: any) => (l.type === "cites" ? 4 : 0)}
              linkDirectionalArrowRelPos={0.9}
              d3AlphaDecay={physicsOn ? 0.0228 : 0.6}
              onNodeClick={onNodeClick}
              onLinkHover={(l: any) => setHoverLink(l ?? null)}
              onBackgroundClick={onBackgroundClick}
              onEngineStop={() => { if (!fittedOnce.current) { fittedOnce.current = true; fgRef.current?.zoomToFit(400, 70); } }}
              width={dims.width}
              height={dims.height}
            />
          )}

          {hoverLink && (
            <div className="pointer-events-none absolute z-20 rounded-md border border-white/15 bg-[#10141d]/95 px-2.5 py-1.5 text-[10.5px] text-white/85 backdrop-blur"
              style={{ left: mouseRef.current.x + 12, top: mouseRef.current.y + 12 }}>
              <span className="font-medium">{hoverLink.type === "similar" ? `similar to ${(hoverLink.weight ?? 0).toFixed(2)}` : LINK_LABELS[hoverLink.type] ?? hoverLink.type}</span>
              {hoverLink.type === "similar" && <span className="ml-1.5 text-white/50">{(hoverLink.weight ?? 0) >= 0.75 ? "high confidence" : (hoverLink.weight ?? 0) >= 0.6 ? "medium" : "weak"}</span>}
            </div>
          )}

          <div className="absolute top-3 left-3 w-64">
            <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/45 px-2.5 py-1.5 backdrop-blur">
              {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-white/50" /> : <Search className="h-3.5 w-3.5 text-white/40" />}
              <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onSearchSubmit()}
                placeholder="Ask the graph… e.g. multimodal explainability"
                className="w-full bg-transparent text-[11.5px] text-white/85 placeholder:text-white/35 outline-none" />
            </div>
          </div>

          {(trail.length > 0 || pathResult) && (
            <div className="absolute top-14 left-3 flex max-w-[70%] items-center gap-1 overflow-hidden rounded-lg border border-white/10 bg-black/45 px-2 py-1 backdrop-blur">
              <button onClick={() => { setTrail([]); setSelectedNode(null); }} className="shrink-0 text-[10.5px] text-indigo-300 hover:text-indigo-200">Galaxy</button>
              {trail.map((t, i) => (
                <span key={t.id} className="flex min-w-0 items-center gap-1">
                  <ChevronRight className="h-3 w-3 shrink-0 text-white/30" />
                  <button
                    onClick={() => { setTrail(trail.slice(0, i + 1)); setSelectedNode(t); }}
                    className={`truncate text-[10.5px] ${i === trail.length - 1 ? "text-white/90" : "text-white/50 hover:text-white/80"}`}>
                    {t.name}
                  </button>
                </span>
              ))}
              {pathResult && (
                <span className="ml-2 flex shrink-0 items-center gap-1 text-[10.5px] text-emerald-300">
                  path · {pathResult.hops} hops
                  <button onClick={() => setPathResult(null)} className="text-white/50 hover:text-white"><X className="h-3 w-3" /></button>
                </span>
              )}
            </div>
          )}

          <div className="absolute top-3 right-3 flex flex-col gap-0.5 rounded-lg border border-white/10 bg-black/45 p-1 backdrop-blur">
            <button className={ctrlBtn} title="Zoom in" onClick={() => zoomBy(1.5)}><ZoomIn className="h-3.5 w-3.5" /></button>
            <button className={ctrlBtn} title="Zoom out" onClick={() => zoomBy(1 / 1.5)}><ZoomOut className="h-3.5 w-3.5" /></button>
            <button className={ctrlBtn} title="Fit to view" onClick={fit}><Maximize2 className="h-3.5 w-3.5" /></button>
            <button className={`${ctrlBtn} ${pathMode || pathA ? "text-emerald-300 bg-white/10" : ""}`} title="Trace path: click two nodes"
              onClick={() => { setPathMode((v) => !v); setPathA(null); setPathResult(null); }}>
              <Route className="h-3.5 w-3.5" />
            </button>
            <button className={`${ctrlBtn} ${showStats ? "text-white bg-white/10" : ""}`} title="Graph analytics" onClick={() => setShowStats(v => !v)}>
              <BarChart3 className="h-3.5 w-3.5" />
            </button>
            <button className={ctrlBtn} title={physicsOn ? "Freeze layout" : "Re-run layout"}
              onClick={() => setPhysicsOn((on) => { if (!on) fgRef.current?.d3ReheatSimulation(); return !on; })}>
              {physicsOn ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </button>
            <button className={`${ctrlBtn} ${labelsAuto ? "" : "text-white bg-white/10"}`} title="Adaptive labels" onClick={() => setLabelsAuto(v => !v)}>
              <Type className="h-3.5 w-3.5" />
            </button>
            <button className={ctrlBtn} title="Rebuild graph" onClick={() => load(true)}><RefreshCw className="h-3.5 w-3.5" /></button>
          </div>

          {pathMode && (
            <div className="absolute top-16 right-3 rounded-md border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1.5 text-[10.5px] text-emerald-200 backdrop-blur">
              {pathA ? `Now click the target node (from “${pathA.name.slice(0, 24)}…”)` : "Click the start node"}
            </div>
          )}

          {/* stats panel */}
          {showStats && st && (
            <div className="absolute top-3 right-14 w-60 rounded-lg border border-white/10 bg-black/60 p-3 backdrop-blur">
              <p className="mb-2 text-[9.5px] font-semibold uppercase tracking-wider text-white/40">Graph analytics</p>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[10.5px] text-white/75">
                <span>Papers</span><span className="text-right text-white/90">{st.papers}</span>
                <span>Concepts</span><span className="text-right text-white/90">{st.concepts}</span>
                <span>Methods</span><span className="text-right text-white/90">{st.methods}</span>
                <span>Datasets</span><span className="text-right text-white/90">{st.datasets}</span>
                <span>Relationships</span><span className="text-right text-white/90">{st.links}</span>
                <span>Communities</span><span className="text-right text-white/90">{Math.max(st.concepts ? 1 : 0, 1) * visible!.legend.length}</span>
                <span>Density</span><span className="text-right text-white/90">{st.density.toFixed(3)}</span>
                <span>Avg degree</span><span className="text-right text-white/90">{st.avgDegree.toFixed(1)}</span>
              </div>
              <div className="mt-2 border-t border-white/10 pt-2 text-[10.5px] text-white/75 space-y-1">
                <p>Most central concept: <span className="text-white/95">{st.topConcept}</span></p>
                {st.topPaper && <p>Most cited paper: <span className="text-white/95">{String(st.topPaper.name).slice(0, 34)}… ({st.topPaper.citation_count ?? 0})</span></p>}
                {st.minYear != null && <p>Span: <span className="text-white/95">{st.minYear}–{st.maxYear}</span></p>}
              </div>
            </div>
          )}

          {visible && visible.legend.length > 0 && (
            <div className="absolute bottom-3 left-3 rounded-lg border border-white/10 bg-black/45 px-3 py-2 backdrop-blur">
              <p className="mb-1 text-[9.5px] font-semibold uppercase tracking-wider text-white/40">Node color = topic cluster · size = influence</p>
              <div className="flex flex-col gap-1">
                {visible.legend.map((c) => (
                  <span key={c.name} className="flex items-center gap-1.5 text-[10.5px] text-white/70">
                    <span className="h-2 w-2 rounded-full" style={{ background: c.color, boxShadow: `0 0 6px ${c.color}` }} />
                    {c.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {st?.minYear != null && st.maxYear != null && st.maxYear - st.minYear >= 1 && (
            <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-white/10 bg-black/45 px-3 py-1.5 backdrop-blur">
              <button className="text-white/70 hover:text-white"
                onClick={() => { if (playing) { setPlaying(false); } else { setYearCut(st.minYear); setPlaying(true); } }}>
                {playing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
              </button>
              <span className="w-10 text-center text-[10.5px] tabular-nums text-white/80">{yearCut ?? st.maxYear}</span>
              <input type="range" min={st.minYear} max={st.maxYear} value={yearCut ?? st.maxYear}
                onChange={(e) => { setPlaying(false); const v = parseInt(e.target.value, 10); setYearCut(v >= st.maxYear! ? null : v); }}
                className="w-40 accent-indigo-500" />
              <button className="text-[10px] text-white/50 hover:text-white/80" onClick={() => { setYearCut(null); setPlaying(false); }}>all</button>
            </div>
          )}

          {selectedNode && (
            <div className="absolute bottom-14 left-1/2 -translate-x-1/2 w-[460px] max-w-[92%] rounded-xl border border-white/15 bg-[#10141d]/95 p-4 shadow-xl backdrop-blur z-10">
              <div className="mb-2 flex items-center gap-2">
                <span className="inline-block rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold text-white"
                  style={{ background: selectedNode.color ?? "#64748b" }}>
                  {selectedNode.type[0].toUpperCase() + selectedNode.type.slice(1)}
                </span>
                {selectedNode.year != null && <span className="text-[10.5px] text-white/50">{selectedNode.year}</span>}
                {selectedNode.citation_count != null && selectedNode.citation_count > 0 && (
                  <span className="text-[10.5px] text-white/50">{selectedNode.citation_count.toLocaleString()} citations</span>
                )}
                <span className="ml-auto text-[10.5px] text-white/40">{selectedNode.degree ?? 0} connections</span>
                <button onClick={() => setSelectedNode(null)} className="text-white/50 hover:text-white text-[13px]">✕</button>
              </div>
              <p className="text-[14px] leading-snug text-white">{selectedNode.name}</p>
              {selectedNode.type === "paper" && (selectedNode.authors?.length ?? 0) > 0 && (
                <p className="mt-1 truncate text-[11px] text-white/55">{selectedNode.authors!.join(", ")}</p>
              )}
              {selectedNode.excerpt && <p className="mt-2 line-clamp-2 text-[11.5px] leading-relaxed text-white/65">{selectedNode.excerpt}</p>}
              {rel && (
                <div className="mt-2.5 space-y-1.5">
                  {rel.concepts.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="text-[9.5px] uppercase tracking-wide text-white/40">topics</span>
                      {rel.concepts.slice(0, 5).map((c) => <span key={c} className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/75">{c}</span>)}
                    </div>
                  )}
                  {rel.methods.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="text-[9.5px] uppercase tracking-wide text-white/40">methods</span>
                      {rel.methods.slice(0, 5).map((m) => <span key={m} className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-200">{m}</span>)}
                    </div>
                  )}
                  {rel.datasets.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="text-[9.5px] uppercase tracking-wide text-white/40">datasets</span>
                      {rel.datasets.slice(0, 5).map((d) => <span key={d} className="rounded-full bg-cyan-500/20 px-2 py-0.5 text-[10px] text-cyan-200">{d}</span>)}
                    </div>
                  )}
                  {rel.papers.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="text-[9.5px] uppercase tracking-wide text-white/40">related</span>
                      {rel.papers.slice(0, 3).map((p) => (
                        <button key={p.id} onClick={() => { const n = visible!.nodes.find((x) => x.id === p.id); if (n) onNodeClick(n); }}
                          className="max-w-[160px] truncate rounded-full bg-indigo-500/20 px-2 py-0.5 text-[10px] text-indigo-200 hover:bg-indigo-500/30">
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
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/30">
              <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
              <p className="text-[12px] text-white/60">Mapping your research galaxy…</p>
            </div>
          )}
          {!loading && error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
              <AlertTriangle className="h-5 w-5 text-red-400" />
              <p className="text-[12px] text-white/60">{error}</p>
              <button onClick={() => load(false)} className="rounded-md bg-indigo-500 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-indigo-400">Retry</button>
            </div>
          )}
          {!loading && !error && (!visible || visible.nodes.length === 0) && (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="text-[12.5px] text-white/50">
                {scope === "message" ? "No papers were surfaced in this message. Switch to Whole Conversation."
                  : "No graph yet. Ask a research question or upload a paper, then explore."}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}