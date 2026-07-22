"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Loader2, MessageSquare, Network } from "lucide-react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { FullGraphData, GraphScope } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const NODE_COLORS: Record<string, string> = {
  paper: "#6366f1",
  concept: "#10b981",
  method: "#f59e0b",
};

export function GraphView({
  sessionId,
  activeTurnId,
}: {
  sessionId: string;
  activeTurnId?: string | null;
}) {
  const [scope, setScope] = useState<GraphScope>(activeTurnId ? "message" : "conversation");
  const [graphData, setGraphData] = useState<FullGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (!activeTurnId && scope === "message") {
      setScope("conversation");
    }
  }, [activeTurnId, scope]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const fetchGraph =
      scope === "message" && activeTurnId
        ? api.getTurnGraph(sessionId, activeTurnId)
        : api.getFullGraph(sessionId);

    fetchGraph
      .then((data) => {
        if (!cancelled) setGraphData(data);
      })
      .catch(console.error)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, scope, activeTurnId]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDims({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [graphData]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDims({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [graphData]);

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const radius = node.type === "paper" ? 6 : 4;
    const color = NODE_COLORS[node.type] ?? "#94a3b8";

    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.15)";
    ctx.lineWidth = 0.5;
    ctx.stroke();

    const fontSize = Math.max(3.2, 11 / globalScale);
    const rawLabel: string = node.name ?? "";
    const maxChars = node.type === "paper" ? 28 : 18;
    const label = rawLabel.length > maxChars ? rawLabel.slice(0, maxChars - 1) + "\u2026" : rawLabel;

    ctx.font = `${node.type === "paper" ? "600" : "400"} ${fontSize}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";

    const textWidth = ctx.measureText(label).width;
    const padX = 2, padY = 1;
    ctx.fillStyle = "rgba(255,255,255,0.82)";
    ctx.fillRect(
      node.x - textWidth / 2 - padX,
      node.y + radius + 1,
      textWidth + padX * 2,
      fontSize + padY * 2
    );

    ctx.fillStyle = "#1e1e2e";
    ctx.fillText(label, node.x, node.y + radius + 1 + padY);

    node.__bckgDimensions = [textWidth + padX * 2, fontSize + padY * 2];
  }, []);

  const paintNodePointerArea = useCallback((node: any, color: string, ctx: CanvasRenderingContext2D) => {
    const radius = node.type === "paper" ? 6 : 4;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 2, 0, 2 * Math.PI, false);
    ctx.fill();
  }, []);

  const paintLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const start = link.source;
    const end = link.target;
    if (typeof start !== "object" || typeof end !== "object") return;

    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;

    const fontSize = Math.max(2.6, 8 / globalScale);
    const label = link.type ?? "";
    if (!label) return;

    ctx.font = `${fontSize}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    const textWidth = ctx.measureText(label).width;
    const padX = 1.5, padY = 0.5;
    ctx.fillStyle = "rgba(255,255,255,0.75)";
    ctx.fillRect(midX - textWidth / 2 - padX, midY - fontSize / 2 - padY, textWidth + padX * 2, fontSize + padY * 2);

    ctx.fillStyle = link.type === "cites" ? "#4f46e5" : "#64748b";
    ctx.fillText(label, midX, midY);
  }, []);

  const LEGEND_HEIGHT = 33;
  const TOGGLE_HEIGHT = 40;

  const ScopeToggle = (
    <div className="flex items-center gap-1 border-b border-line px-3 py-1.5 shrink-0">
      <button
        onClick={() => activeTurnId && setScope("message")}
        disabled={!activeTurnId}
        title={activeTurnId ? "This message only" : "No active message to scope to"}
        className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
          scope === "message"
            ? "bg-indigo text-white"
            : "text-ink-soft hover:bg-paper-dim disabled:opacity-40 disabled:hover:bg-transparent"
        }`}
      >
        <MessageSquare className="h-3 w-3" />
        This Message
      </button>
      <button
        onClick={() => setScope("conversation")}
        className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
          scope === "conversation" ? "bg-indigo text-white" : "text-ink-soft hover:bg-paper-dim"
        }`}
      >
        <Network className="h-3 w-3" />
        Whole Conversation
      </button>
    </div>
  );

  if (loading)
    return (
      <div className="w-full h-full flex flex-col">
        {ScopeToggle}
        <div className="flex items-center gap-2 p-6 text-[12px] text-ink-soft animate-fade-up">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading {scope === "message" ? "message" : "conversation"} graph...
        </div>
      </div>
    );

  if (!graphData || graphData.nodes.length === 0)
    return (
      <div className="w-full h-full flex flex-col">
        {ScopeToggle}
        <div className="p-6 text-center text-[12.5px] text-ink-soft">
          {scope === "message"
            ? "No graph data for this message yet. Ask a research question to populate it."
            : "No graph data yet. Ask a research question to populate the graph."}
        </div>
      </div>
    );


  return (
    <div className="w-full h-full min-h-[400px] bg-paper-dim/30 flex flex-col">
      {ScopeToggle}
      <div ref={containerRef} className="flex-1 min-h-0">
        <ForceGraph2D
          graphData={graphData}
          nodeAutoColorBy="type"
          nodeCanvasObject={paintNode}
          nodePointerAreaPaint={paintNodePointerArea}
          linkCanvasObject={paintLink}
          linkCanvasObjectMode={() => "after"}
          linkDirectionalArrowLength={6}
          linkDirectionalArrowRelPos={0.9}
          linkColor={(link: any) => (link.type === "cites" ? "#6366f1" : "#94a3b8")}
          width={dims.width}
          height={Math.max(dims.height - LEGEND_HEIGHT - TOGGLE_HEIGHT, 200)}
        />
      </div>
      <div className="flex items-center gap-4 px-3 py-2 text-[10.5px] text-ink-soft border-t border-line shrink-0">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ background: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}