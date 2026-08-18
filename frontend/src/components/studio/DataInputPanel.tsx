"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  PenLine,
  BookOpen,
  Globe,
  BarChart3,
  LineChart,
  PieChart,
  ScatterChart,
  Loader2,
  ArrowRight,
  GitBranch,
  Layers,
  Network,
  Plus,
  Trash2,
  RotateCcw,
  MessageSquareText,
  MessageCircle,
  Settings2,
} from "lucide-react";
import type {
  StudioChartType,
  StudioVisualSpec,
  StudioChartSeries,
  StudioDraftRequest,
  StudioDraftSource,
  StudioConversationContext,
} from "@/lib/types";

type VisualFamily = "chart" | "flowchart" | "architecture" | "dfd";
type NodeType = "process" | "terminal" | "data" | "external" | "store" | "decision";
type NodeDraft = { id: string; label: string; node_type: NodeType; layer: number | null };
type EdgeDraft = { source: string; target: string; label: string };

const FAMILIES: { id: VisualFamily; icon: React.ReactNode; label: string; desc: string }[] = [
  { id: "chart", icon: <BarChart3 className="h-4 w-4" />, label: "Chart", desc: "Bar / line / pie from real data" },
  { id: "flowchart", icon: <GitBranch className="h-4 w-4" />, label: "Flowchart", desc: "Steps, decisions, terminals" },
  { id: "architecture", icon: <Layers className="h-4 w-4" />, label: "Architecture", desc: "Layered system blocks" },
  { id: "dfd", icon: <Network className="h-4 w-4" />, label: "DFD", desc: "Processes, stores, externals" },
];

const CHART_TYPES: { id: StudioChartType; icon: React.ReactNode; label: string }[] = [
  { id: "bar", icon: <BarChart3 className="h-4 w-4" />, label: "Bar" },
  { id: "line", icon: <LineChart className="h-4 w-4" />, label: "Line" },
  { id: "pie", icon: <PieChart className="h-4 w-4" />, label: "Pie" },
  { id: "scatter", icon: <ScatterChart className="h-4 w-4" />, label: "Scatter" },
];

const DRAFT_SOURCES: {
  id: StudioDraftSource;
  icon: React.ReactNode;
  title: string;
  desc: string;
}[] = [
  {
    id: "prompt",
    icon: <MessageSquareText className="h-4 w-4" />,
    title: "From prompt",
    desc: "Draft from the description alone",
  },
  {
    id: "manual",
    icon: <PenLine className="h-4 w-4" />,
    title: "Use my data",
    desc: "Values you provide directly",
  },
  {
    id: "papers",
    icon: <BookOpen className="h-4 w-4" />,
    title: "From my papers",
    desc: "Use session Library context",
  },
  {
    id: "conversation",
    icon: <MessageCircle className="h-4 w-4" />,
    title: "From this conversation",
    desc: "Use recent chat context explicitly",
  },
  {
    id: "web_search",
    icon: <Globe className="h-4 w-4" />,
    title: "Find data",
    desc: "Search and ground from the web",
  },
];

const NODE_TYPES: Record<"flowchart" | "architecture" | "dfd", NodeType[]> = {
  flowchart: ["process", "terminal", "decision", "data"],
  architecture: ["external", "process", "store"],
  dfd: ["process", "external", "store"],
};

function templateFor(family: "flowchart" | "architecture" | "dfd", dfdLevel: 0 | 1): { nodes: NodeDraft[]; edges: EdgeDraft[] } {
  if (family === "flowchart") {
    return {
      nodes: [
        { id: "n1", label: "Start", node_type: "terminal", layer: null },
        { id: "n2", label: "Collect Input", node_type: "data", layer: null },
        { id: "n3", label: "Process", node_type: "process", layer: null },
        { id: "n4", label: "Valid?", node_type: "decision", layer: null },
        { id: "n5", label: "Output Result", node_type: "data", layer: null },
        { id: "n6", label: "End", node_type: "terminal", layer: null },
      ],
      edges: [
        { source: "n1", target: "n2", label: "" },
        { source: "n2", target: "n3", label: "" },
        { source: "n3", target: "n4", label: "" },
        { source: "n4", target: "n5", label: "yes" },
        { source: "n4", target: "n3", label: "no" },
        { source: "n5", target: "n6", label: "" },
      ],
    };
  }
  if (family === "architecture") {
    return {
      nodes: [
        { id: "a1", label: "Client / UI", node_type: "external", layer: 0 },
        { id: "a2", label: "API Gateway", node_type: "process", layer: 1 },
        { id: "a3", label: "Auth Service", node_type: "process", layer: 2 },
        { id: "a4", label: "Core Service", node_type: "process", layer: 2 },
        { id: "a5", label: "Database", node_type: "store", layer: 3 },
      ],
      edges: [
        { source: "a1", target: "a2", label: "requests" },
        { source: "a2", target: "a3", label: "authn" },
        { source: "a2", target: "a4", label: "route" },
        { source: "a4", target: "a5", label: "read/write" },
      ],
    };
  }
  if (dfdLevel === 0) {
    return {
      nodes: [
        { id: "d1", label: "User", node_type: "external", layer: null },
        { id: "d2", label: "0. System", node_type: "process", layer: null },
        { id: "d3", label: "Records", node_type: "store", layer: null },
      ],
      edges: [
        { source: "d1", target: "d2", label: "input" },
        { source: "d2", target: "d1", label: "output" },
        { source: "d2", target: "d3", label: "store" },
      ],
    };
  }
  return {
    nodes: [
      { id: "d1", label: "User", node_type: "external", layer: null },
      { id: "d2", label: "1. Intake", node_type: "process", layer: null },
      { id: "d3", label: "2. Process", node_type: "process", layer: null },
      { id: "d4", label: "Records", node_type: "store", layer: null },
    ],
    edges: [
      { source: "d1", target: "d2", label: "request" },
      { source: "d2", target: "d4", label: "write" },
      { source: "d4", target: "d3", label: "read" },
      { source: "d3", target: "d1", label: "result" },
    ],
  };
}

let _uid = 0;
const nextId = () => `n${++_uid}${Date.now().toString(36).slice(-3)}`;

export function DataInputPanel({
  sessionId,
  onGenerate,
  onDraft,
  getConversationContext,
  isGenerating,
}: {
  sessionId: string;
  onGenerate: (spec: StudioVisualSpec) => void;
  onDraft: (req: Omit<StudioDraftRequest, "session_id">) => void;
  getConversationContext?: () => StudioConversationContext | null;
  isGenerating: boolean;
}) {
    const [family, setFamily] = useState<VisualFamily>("chart");
    const [prompt, setPrompt] = useState("");
    const [draftSource, setDraftSource] = useState<StudioDraftSource>("manual");
    const [showManualBuilder, setShowManualBuilder] = useState(false);
    const [chartType, setChartType] = useState<StudioChartType>("bar");
  const [title, setTitle] = useState("");
  const [categories, setCategories] = useState<string[]>(["Category A", "Category B", "Category C"]);
  const [values, setValues] = useState<string[]>(["10", "25", "18"]);
  const [nodes, setNodes] = useState<NodeDraft[]>([]);
  const [edges, setEdges] = useState<EdgeDraft[]>([]);
  const [dfdLevel, setDfdLevel] = useState<0 | 1>(0);
  const [warn, setWarn] = useState<string | null>(null);

    useEffect(() => {
    setDraftSource(family === "chart" ? "manual" : "prompt");
    }, [family]);

    useEffect(() => {
    if (family === "chart") return;
    if (!showManualBuilder) return;

    const t = templateFor(family, family === "dfd" ? dfdLevel : 0);
    setNodes(t.nodes);
    setEdges(t.edges);
    }, [family, dfdLevel, showManualBuilder]);

  const patchNode = (id: string, patch: Partial<NodeDraft>) =>
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));
  const removeNode = (id: string) => {
    setNodes((prev) => prev.filter((n) => n.id !== id));
    setEdges((prev) => prev.filter((e) => e.source !== id && e.target !== id));
  };
  const addNode = () =>
    setNodes((prev) => [...prev, { id: nextId(), label: "", node_type: NODE_TYPES[family as "flowchart" | "architecture" | "dfd"]?.[0] ?? "process", layer: null }]);
  const patchEdge = (i: number, patch: Partial<EdgeDraft>) =>
    setEdges((prev) => prev.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  const removeEdge = (i: number) => setEdges((prev) => prev.filter((_, idx) => idx !== i));
  const addEdge = () => {
    if (nodes.length < 2) { setWarn("Add at least two nodes before connecting flows."); return; }
    setWarn(null);
    setEdges((prev) => [...prev, { source: nodes[0].id, target: nodes[1].id, label: "" }]);
  };

const visibleSources =
  family === "chart"
    ? DRAFT_SOURCES
    : DRAFT_SOURCES.filter((s) =>
        ["prompt", "papers", "conversation"].includes(s.id)
      );

const handleDraft = () => {
  setWarn(null);

  if (!prompt.trim()) {
    setWarn("Describe what you want first.");
    return;
  }

  let conversation_context: string | null = null;

  if (draftSource === "conversation") {
    const ctx = getConversationContext?.();

    if (!ctx?.excerpt?.trim()) {
      setWarn("No conversation context available yet.");
      return;
    }

    conversation_context = ctx.excerpt;
  }

  onDraft({
    family,
    prompt: prompt.trim(),
    source: draftSource,
    chart_type: chartType,
    dfd_level: family === "dfd" ? dfdLevel : null,
    conversation_context,
    selected_paper_links: null,
  });
};

const handleManualGenerate = () => {
  setWarn(null);

  if (family === "chart") {
    const parsedValues = values.map((v) => parseFloat(v) || 0);
    const cleanCats = categories.map((c) => c.trim()).filter(Boolean);

    if (cleanCats.length !== parsedValues.length) {
      setWarn("Categories and values must have the same count.");
      return;
    }

    const series: StudioChartSeries[] = [
      {
        label: title || "Data",
        values: parsedValues,
        provenance: parsedValues.map(() => ({ kind: "user_provided" as const })),
      },
    ];

    onGenerate({
      spec_version: 1,
      visual_id: crypto.randomUUID(),
      session_id: sessionId,
      revision: 1,
      title: title || "Untitled Chart",
      grounding: {
        level: "user_provided",
        grounded_count: 0,
        user_provided_count: parsedValues.length,
        illustrative_count: 0,
        citations: [],
      },
      payload: {
        kind: "chart",
        chart_type: chartType,
        categories: cleanCats,
        series,
      },
      created_at: new Date().toISOString(),
    });

    return;
  }

  const validNodes = nodes.filter((n) => n.label.trim());

  if (validNodes.length < 2) {
    setWarn("Add at least two labeled nodes.");
    return;
  }

  const ids = new Set(validNodes.map((n) => n.id));

  const validEdges = edges.filter(
    (e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target
  );

  onGenerate({
    spec_version: 1,
    visual_id: crypto.randomUUID(),
    session_id: sessionId,
    revision: 1,
    title:
      title ||
      (family === "dfd"
        ? `DFD Level ${dfdLevel}`
        : family === "flowchart"
        ? "Process Flowchart"
        : "System Architecture"),
    grounding: {
      level: "user_provided",
      grounded_count: 0,
      user_provided_count: validNodes.length,
      illustrative_count: 0,
      citations: [],
    },
    payload: {
      kind: family,
      layout: family === "architecture" ? "layered" : "top_down",
      nodes: validNodes.map((n) => ({
        id: n.id,
        label: n.label.trim(),
        node_type: n.node_type,
        layer: n.layer,
      })),
      edges: validEdges.map((e) => ({
        source: e.source,
        target: e.target,
        label: e.label.trim() || null,
      })),
      dfd_level: family === "dfd" ? dfdLevel : null,
    },
    created_at: new Date().toISOString(),
  });
};

  const inputCls = "w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12.5px] text-ink placeholder:text-ink-soft/50 focus:border-indigo/50 focus:outline-none focus:ring-2 focus:ring-indigo/10";

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <SectionLabel step={1} title="Visual Family" />
      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {FAMILIES.map((f) => (
          <motion.button
            key={f.id}
            onClick={() => setFamily(f.id)}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.98 }}
            className={`relative flex flex-col items-start gap-2 rounded-xl border p-3.5 text-left transition-all ${
              family === f.id
                ? "border-indigo/50 bg-indigo-tint/50 shadow-md shadow-indigo/10"
                : "border-line bg-paper hover:border-indigo/30 hover:shadow-sm"
            }`}
          >
            <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${family === f.id ? "bg-indigo text-white" : "bg-paper-dim text-ink-soft"}`}>
              {f.icon}
            </div>
            <div>
              <p className="text-[12.5px] font-semibold text-ink">{f.label}</p>
              <p className="text-[10.5px] text-ink-soft mt-0.5">{f.desc}</p>
            </div>
          </motion.button>
        ))}
      </div>

        <SectionLabel step={2} title="Describe the visual" />

        <div className="mb-6">
        <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
            placeholder={
            family === "chart"
                ? "e.g., Bar chart comparing accuracy across BERT, GPT-2, and T5"
                : family === "flowchart"
                ? "e.g., Flowchart for user login with 2FA fallback"
                : family === "architecture"
                ? "e.g., Architecture diagram for a RAG pipeline with retrieval and generation"
                : "e.g., DFD level 0 for the paper's proposed system"
            }
            className={`${inputCls} resize-none`}
        />

        <p className="mt-2 text-[11px] text-ink-soft leading-relaxed">
            Sykra will draft the structure first. You can refine it after generation.
        </p>
        </div>

        <SectionLabel step={3} title="Source" />

        <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {visibleSources.map((source) => (
            <button
            key={source.id}
            onClick={() => setDraftSource(source.id)}
            className={`flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all ${
                draftSource === source.id
                ? "border-indigo/50 bg-indigo-tint/50 shadow-md shadow-indigo/10"
                : "border-line bg-paper hover:border-indigo/30 hover:shadow-sm"
            }`}
            >
            <div
                className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                draftSource === source.id
                    ? "bg-indigo text-white"
                    : "bg-paper-dim text-ink-soft"
                }`}
            >
                {source.icon}
            </div>

            <div>
                <p className="text-[12.5px] font-semibold text-ink">
                {source.title}
                </p>
                <p className="text-[11px] text-ink-soft mt-0.5">
                {source.desc}
                </p>
            </div>
            </button>
        ))}
        </div>

        {family === "chart" && (
        <>
            <SectionLabel step={4} title="Chart Type" />

            <div className="flex gap-2 mb-8">
            {CHART_TYPES.map((ct) => (
                <button
                key={ct.id}
                onClick={() => setChartType(ct.id)}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-[12px] font-medium transition-all ${
                    chartType === ct.id
                    ? "border-indigo/50 bg-indigo text-white shadow-md shadow-indigo/20"
                    : "border-line bg-paper text-ink-soft hover:border-indigo/30 hover:text-ink"
                }`}
                >
                {ct.icon}
                {ct.label}
                </button>
            ))}
            </div>
        </>
        )}

        {family === "dfd" && (
        <>
            <SectionLabel step={4} title="DFD Level" />

            <div className="flex items-center gap-1 rounded-lg bg-paper-dim p-1 mb-8 w-fit">
            {([0, 1] as const).map((lv) => (
                <button
                key={lv}
                onClick={() => setDfdLevel(lv)}
                className={`rounded-md px-3 py-1.5 text-[11.5px] font-medium transition-all ${
                    dfdLevel === lv
                    ? "bg-paper text-ink shadow-sm"
                    : "text-ink-soft hover:text-ink"
                }`}
                >
                Level {lv}
                </button>
            ))}
            </div>
        </>
        )}

        <div className="mb-6">
        <button
            onClick={() => setShowManualBuilder((v) => !v)}
            className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[12px] font-medium text-ink-soft hover:text-ink"
        >
            <Settings2 className="h-3.5 w-3.5" />
            {showManualBuilder ? "Hide manual builder" : "Manual builder / advanced"}
        </button>
        </div>

        {showManualBuilder && (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-8 space-y-6 rounded-xl border border-line bg-paper p-4"
        >
            {family === "chart" ? (
            <>
                <SectionLabel step={5} title="Manual Chart Data" />

                <div className="space-y-4">
                <div>
                    <label className="block text-[11.5px] font-medium text-ink-soft mb-1.5">
                    Chart Title
                    </label>
                    <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g., Model Accuracy Comparison"
                    className={inputCls}
                    />
                </div>

                <div>
                    <label className="block text-[11.5px] font-medium text-ink-soft mb-1.5">
                    Categories (comma-separated)
                    </label>
                    <input
                    value={categories.join(", ")}
                    onChange={(e) =>
                        setCategories(e.target.value.split(",").map((s) => s.trim()))
                    }
                    placeholder="e.g., BERT, GPT-2, T5"
                    className={inputCls}
                    />
                </div>

                <div>
                    <label className="block text-[11.5px] font-medium text-ink-soft mb-1.5">
                    Values (comma-separated, matching categories)
                    </label>
                    <input
                    value={values.join(", ")}
                    onChange={(e) =>
                        setValues(e.target.value.split(",").map((s) => s.trim()))
                    }
                    placeholder="e.g., 88.5, 91.2, 94.7"
                    className={inputCls}
                    />
                </div>
                </div>
            </>
            ) : (
            <>
                <div className="flex flex-wrap items-center gap-2">
                <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={
                    family === "dfd"
                        ? `DFD Level ${dfdLevel} — title`
                        : "Diagram title"
                    }
                    className={`${inputCls} min-w-[220px] flex-1`}
                />

                {family === "dfd" && (
                    <div className="flex items-center gap-1 rounded-lg bg-paper-dim p-1">
                    {([0, 1] as const).map((lv) => (
                        <button
                        key={lv}
                        onClick={() => setDfdLevel(lv)}
                        className={`rounded-md px-3 py-1.5 text-[11.5px] font-medium transition-all ${
                            dfdLevel === lv
                            ? "bg-paper text-ink shadow-sm"
                            : "text-ink-soft hover:text-ink"
                        }`}
                        >
                        Level {lv}
                        </button>
                    ))}
                    </div>
                )}

                <button
                    onClick={() => {
                    const t = templateFor(family, dfdLevel);
                    setNodes(t.nodes);
                    setEdges(t.edges);
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[11.5px] font-medium text-ink-soft hover:text-ink"
                >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Reset template
                </button>
                </div>

                <SectionLabel step={6} title={`Nodes (${nodes.length})`} />

                <div className="space-y-1.5">
                {nodes.map((n) => (
                    <div key={n.id} className="flex items-center gap-2">
                    <input
                        value={n.label}
                        onChange={(e) => patchNode(n.id, { label: e.target.value })}
                        placeholder="Label (e.g., Payment Service)"
                        className={inputCls}
                    />

                    <select
                        value={n.node_type}
                        onChange={(e) =>
                        patchNode(n.id, { node_type: e.target.value as NodeType })
                        }
                        className="w-28 shrink-0 rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                    >
                        {NODE_TYPES[family as "flowchart" | "architecture" | "dfd"].map((t) => (
                        <option key={t} value={t}>
                            {t}
                        </option>
                        ))}
                    </select>

                    <button
                        onClick={() => removeNode(n.id)}
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-danger/10 hover:text-danger"
                    >
                        <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    </div>
                ))}

                <button
                    onClick={addNode}
                    className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
                >
                    <Plus className="h-3.5 w-3.5" />
                    Add node
                </button>
                </div>

                <SectionLabel step={7} title={`Flows / Edges (${edges.length})`} />

                <div className="space-y-1.5">
                {edges.map((e, i) => (
                    <div key={i} className="flex items-center gap-2">
                    <select
                        value={e.source}
                        onChange={(ev) => patchEdge(i, { source: ev.target.value })}
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
                        value={e.target}
                        onChange={(ev) => patchEdge(i, { target: ev.target.value })}
                        className="flex-1 rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                    >
                        {nodes.map((n) => (
                        <option key={n.id} value={n.id}>
                            {n.label || n.id}
                        </option>
                        ))}
                    </select>

                    <input
                        value={e.label}
                        onChange={(ev) => patchEdge(i, { label: ev.target.value })}
                        placeholder="label"
                        className="w-24 shrink-0 rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                    />

                    <button
                        onClick={() => removeEdge(i)}
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-danger/10 hover:text-danger"
                    >
                        <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    </div>
                ))}

                <button
                    onClick={addEdge}
                    className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
                >
                    <Plus className="h-3.5 w-3.5" />
                    Add flow
                </button>
                </div>
            </>
            )}

            <div className="flex justify-end pt-2">
            <button
                onClick={handleManualGenerate}
                disabled={isGenerating}
                className="rounded-lg border border-line bg-paper px-4 py-2.5 text-[12.5px] font-medium text-ink hover:bg-paper-dim disabled:opacity-50"
            >
                Generate manual visual
            </button>
            </div>
        </motion.div>
        )}

      {warn && (
        <div className="mt-6 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger animate-fade-up">
          {warn}
        </div>
      )}
      <div className="mt-8 flex justify-end">
        <motion.button
          onClick={handleDraft}
          disabled={isGenerating || !prompt.trim()}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="flex items-center gap-2 rounded-xl bg-indigo px-6 py-3 text-[13px] font-semibold text-white shadow-lg shadow-indigo/25 transition-all hover:bg-indigo-dark disabled:opacity-50"
        >
          {isGenerating ? (
            <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Drafting...
            </>
            ) : (
            <>
                Draft visual
                <ArrowRight className="h-4 w-4" />
            </>
            )}
        </motion.button>
      </div>
    </div>
  );
}

function SectionLabel({ step, title }: { step: number; title: string }) {
  return (
    <div className="flex items-center gap-2.5 mb-3">
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo/10 text-[10px] font-bold text-indigo">{step}</span>
      <span className="text-[12px] font-semibold uppercase tracking-wide text-ink-soft">{title}</span>
    </div>
  );
}