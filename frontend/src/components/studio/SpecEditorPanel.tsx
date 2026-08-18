"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Save, RotateCcw, Loader2, Plus, Trash2, ArrowRight } from "lucide-react";
import type {
  StudioVisualSpec,
  StudioChartType,
  StudioDiagramNode,
  StudioDiagramEdge,
} from "@/lib/types";

export function SpecEditorPanel({
  spec,
  onRevise,
  isGenerating,
}: {
  spec: StudioVisualSpec;
  onRevise: (spec: StudioVisualSpec) => void;
  isGenerating: boolean;
}) {
  const [title, setTitle] = useState(spec.title);
  const [chartType, setChartType] = useState<StudioChartType>("bar");
  const [categories, setCategories] = useState<string[]>([]);
  const [values, setValues] = useState<string[]>([]);
  const [hasChanges, setHasChanges] = useState(false);
  const [nodes, setNodes] = useState<StudioDiagramNode[]>([]);
  const [edges, setEdges] = useState<StudioDiagramEdge[]>([]);
  useEffect(() => {
    setTitle(spec.title);

    if (spec.payload.kind === "chart") {
      setChartType(spec.payload.chart_type);
      setCategories(spec.payload.categories);
      setValues(spec.payload.series[0]?.values.map(String) ?? []);
    } else {
      setNodes(spec.payload.nodes ?? []);
      setEdges(spec.payload.edges ?? []);
    }
  }, [spec]);
  const diagramNodeTypes = [
    "process",
    "terminal",
    "data",
    "external",
    "store",
    "decision",
    ] as const;

    const patchNode = (id: string, patch: Partial<StudioDiagramNode>) => {
    setNodes((prev) =>
        prev.map((n) => (n.id === id ? { ...n, ...patch } : n))
    );
    setHasChanges(true);
    };

    const removeNode = (id: string) => {
    setNodes((prev) => prev.filter((n) => n.id !== id));
    setEdges((prev) => prev.filter((e) => e.source !== id && e.target !== id));
    setHasChanges(true);
    };

    const addNode = () => {
    const id = `node_${Date.now().toString(36)}_${Math.random()
        .toString(36)
        .slice(2, 6)}`;

    setNodes((prev) => [
        ...prev,
        {
        id,
        label: "",
        node_type: "process",
        layer: null,
        provenance: {
            kind: "user_provided",
        },
        },
    ]);

    setHasChanges(true);
    };

    const patchEdge = (index: number, patch: Partial<StudioDiagramEdge>) => {
    setEdges((prev) =>
        prev.map((e, i) => (i === index ? { ...e, ...patch } : e))
    );
    setHasChanges(true);
    };

    const removeEdge = (index: number) => {
    setEdges((prev) => prev.filter((_, i) => i !== index));
    setHasChanges(true);
    };

    const addEdge = () => {
    if (nodes.length < 2) return;

    setEdges((prev) => [
        ...prev,
        {
        source: nodes[0].id,
        target: nodes[1].id,
        label: "",
        },
    ]);

    setHasChanges(true);
    };

  const handleSave = () => {
    if (spec.payload.kind !== "chart") {
        const validNodes = nodes.filter((n) => n.label.trim());
        const nodeIds = new Set(validNodes.map((n) => n.id));

        const validEdges = edges.filter(
        (e) =>
            nodeIds.has(e.source) &&
            nodeIds.has(e.target) &&
            e.source !== e.target
        );

        const revised: StudioVisualSpec = {
        ...spec,
        title,
        payload: {
            ...spec.payload,
            nodes: validNodes,
            edges: validEdges,
        },
        };

        onRevise(revised);
        setHasChanges(false);
        return;
    }
    const revised: StudioVisualSpec = {
      ...spec,
      title,
      payload: {
        ...spec.payload,
        chart_type: chartType,
        categories,
        series: [{
          ...spec.payload.series[0],
          values: values.map((v) => parseFloat(v) || 0),
          provenance: values.map((v, i) => {
            const orig = spec.payload.kind === "chart" ? spec.payload.series[0]?.provenance[i] : undefined;
            const origVal = spec.payload.kind === "chart" ? spec.payload.series[0]?.values[i] : undefined;
            const newVal = parseFloat(v) || 0;
            if (origVal !== undefined && newVal !== origVal && orig?.kind === "grounded") {
              return { kind: "user_edited" as const, note: `Edited from ${origVal}` };
            }
            return orig ?? { kind: "user_provided" as const };
          }),
        }],
      },
    };
    onRevise(revised);
    setHasChanges(false);
  };

  return (
    <div className="flex h-full flex-col bg-paper">
      <div className="border-b border-line px-4 py-3">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ink-soft">
          Spec Editor
        </h3>
        <p className="text-[10.5px] text-ink-soft mt-0.5">
          Edit without re-prompting. Changes re-render instantly.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <div>
            <label className="block text-[11px] font-medium text-ink-soft mb-1">
            Title
            </label>
            <input
            value={title}
            onChange={(e) => {
                setTitle(e.target.value);
                setHasChanges(true);
            }}
            className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12.5px] text-ink focus:border-indigo/50 focus:outline-none"
            />
        </div>

        {spec.payload.kind === "chart" ? (
            <>
            <div>
                <label className="block text-[11px] font-medium text-ink-soft mb-1">
                Chart Type
                </label>
                <select
                value={chartType}
                onChange={(e) => {
                    setChartType(e.target.value as StudioChartType);
                    setHasChanges(true);
                }}
                className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12.5px] text-ink focus:border-indigo/50 focus:outline-none"
                >
                <option value="bar">Bar Chart</option>
                <option value="line">Line Chart</option>
                <option value="pie">Pie Chart</option>
                <option value="scatter">Scatter Plot</option>
                </select>
            </div>

            <div>
                <label className="block text-[11px] font-medium text-ink-soft mb-1">
                Categories
                </label>
                <textarea
                value={categories.join("\n")}
                onChange={(e) => {
                    setCategories(e.target.value.split("\n"));
                    setHasChanges(true);
                }}
                rows={4}
                className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12px] text-ink font-mono focus:border-indigo/50 focus:outline-none resize-none"
                />
            </div>

            <div>
                <label className="block text-[11px] font-medium text-ink-soft mb-1">
                Values
                </label>
                <textarea
                value={values.join("\n")}
                onChange={(e) => {
                    setValues(e.target.value.split("\n"));
                    setHasChanges(true);
                }}
                rows={4}
                className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12px] text-ink font-mono focus:border-indigo/50 focus:outline-none resize-none"
                />
            </div>
            </>
        ) : (
            <>
            <div>
                <div className="mb-2 flex items-center justify-between">
                <label className="block text-[11px] font-medium text-ink-soft">
                    Nodes ({nodes.length})
                </label>

                <button
                    onClick={addNode}
                    className="flex items-center gap-1 text-[11px] font-medium text-indigo hover:text-indigo-dark"
                >
                    <Plus className="h-3 w-3" />
                    Add node
                </button>
                </div>

                <div className="space-y-2">
                {nodes.map((node) => (
                    <div key={node.id} className="flex items-center gap-2">
                    <input
                        value={node.label}
                        onChange={(e) => patchNode(node.id, { label: e.target.value })}
                        placeholder="Node label"
                        className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                    />

                    <select
                        value={node.node_type ?? "process"}
                        onChange={(e) =>
                        patchNode(node.id, {
                            node_type: e.target.value as StudioDiagramNode["node_type"],
                        })
                        }
                        className="w-28 shrink-0 rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                    >
                        {diagramNodeTypes.map((t) => (
                        <option key={t} value={t}>
                            {t}
                        </option>
                        ))}
                    </select>

                    <button
                        onClick={() => removeNode(node.id)}
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-danger/10 hover:text-danger"
                    >
                        <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    </div>
                ))}
                </div>
            </div>

            <div>
                <div className="mb-2 flex items-center justify-between">
                <label className="block text-[11px] font-medium text-ink-soft">
                    Edges ({edges.length})
                </label>

                <button
                    onClick={addEdge}
                    className="flex items-center gap-1 text-[11px] font-medium text-indigo hover:text-indigo-dark"
                >
                    <Plus className="h-3 w-3" />
                    Add edge
                </button>
                </div>

                <div className="space-y-2">
                {edges.map((edge, i) => (
                    <div key={i} className="space-y-2 rounded-lg border border-line p-2">
                    <div className="flex items-center gap-2">
                        <select
                        value={edge.source}
                        onChange={(e) => patchEdge(i, { source: e.target.value })}
                        className="flex-1 rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                        >
                        {nodes.map((n) => (
                            <option key={n.id} value={n.id}>
                            {n.label || n.id}
                            </option>
                        ))}
                        </select>

                        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-soft" />

                        <select
                        value={edge.target}
                        onChange={(e) => patchEdge(i, { target: e.target.value })}
                        className="flex-1 rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                        >
                        {nodes.map((n) => (
                            <option key={n.id} value={n.id}>
                            {n.label || n.id}
                            </option>
                        ))}
                        </select>

                        <button
                        onClick={() => removeEdge(i)}
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-danger/10 hover:text-danger"
                        >
                        <Trash2 className="h-3.5 w-3.5" />
                        </button>
                    </div>

                    <input
                        value={edge.label ?? ""}
                        onChange={(e) => patchEdge(i, { label: e.target.value })}
                        placeholder="Edge label (optional)"
                        className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                    />
                    </div>
                ))}
                </div>
            </div>
                    </>
      )}
    </div>

    <div className="border-t border-line px-4 py-3">
      <motion.button
        onClick={handleSave}
        disabled={!hasChanges || isGenerating}
        whileTap={{ scale: 0.97 }}
        className={`flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-[12.5px] font-semibold transition-all ${
          hasChanges && !isGenerating
            ? "bg-indigo text-white shadow-md shadow-indigo/20 hover:bg-indigo-dark"
            : "bg-paper-dim text-ink-soft cursor-not-allowed"
        }`}
      >
        {isGenerating ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Save className="h-3.5 w-3.5" />
        )}
        {isGenerating ? "Rendering..." : "Apply Changes"}
      </motion.button>
    </div>
  </div>
);
}