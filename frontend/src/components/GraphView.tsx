"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { FullGraphData } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

export function GraphView({ sessionId }: { sessionId: string }) {
  const [graphData, setGraphData] = useState<FullGraphData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .getFullGraph(sessionId)
      .then(setGraphData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading)
    return (
      <div className="flex items-center gap-2 p-6 text-[12px] text-ink-soft animate-fade-up">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading visual graph...
      </div>
    );

  if (!graphData || graphData.nodes.length === 0)
    return (
      <div className="p-6 text-center text-[12.5px] text-ink-soft">
        No graph data yet. Ask a research question to populate the graph.
      </div>
    );

  return (
    <div className="w-full h-full min-h-[400px] bg-paper-dim/30">
      <ForceGraph2D
        graphData={graphData}
        nodeAutoColorBy="type"
        nodeLabel={(node: any) =>
          `<div class="text-xs bg-paper p-1 rounded shadow">${node.name}</div>`
        }
        linkDirectionalArrowLength={6}
        linkDirectionalArrowRelPos={0.9}
        linkColor={(link: any) => (link.type === "cites" ? "#6366f1" : "#94a3b8")}
        width={800}
        height={600}
      />
    </div>
  );
}
