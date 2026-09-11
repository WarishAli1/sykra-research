"use client";

import { useEffect, useMemo, useState } from "react";
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
  Sparkles,
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
type EdgeDraft = { id: string; source: string; target: string; label: string };

type StepKey = "family" | "description" | "source" | "chartType" | "manualChart" | "manualDiagram";

const FAMILIES: { id: VisualFamily; icon: React.ReactNode; label: string; desc: string }[] = [
  { id: "chart", icon: <BarChart3 className="h-4 w-4" />, label: "Chart", desc: "Bar, line, pie, or scatter" },
  { id: "flowchart", icon: <GitBranch className="h-4 w-4" />, label: "Flowchart", desc: "Steps and decision paths" },
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
  { id: "prompt", icon: <MessageSquareText className="h-4 w-4" />, title: "From prompt", desc: "Describe the visual in plain language" },
  { id: "manual", icon: <PenLine className="h-4 w-4" />, title: "Use my data", desc: "Enter values or nodes directly" },
  { id: "papers", icon: <BookOpen className="h-4 w-4" />, title: "From my papers", desc: "Use library evidence" },
  { id: "conversation", icon: <MessageCircle className="h-4 w-4" />, title: "From this conversation", desc: "Use recent chat context" },
  { id: "web_search", icon: <Globe className="h-4 w-4" />, title: "Find data", desc: "Search and ground from the web" },
];

const NODE_TYPES: Record<"flowchart" | "architecture" | "dfd", NodeType[]> = {
  flowchart: ["process", "terminal", "decision", "data"],
  architecture: ["external", "process", "store"],
  dfd: ["process", "external", "store"],
};

const STUDIO_FLOW_SCHEMA = {
  family: { label: "Visual Family", required: true },
  description: { label: "Describe the visual", required: true },
  source: { label: "Source", required: true },
  chartType: { label: "Chart type", required: true, when: (family: VisualFamily) => family === "chart" },
  manualChart: { label: "Manual chart data", when: (family: VisualFamily, source: StudioDraftSource) => family === "chart" && source === "manual" },
  manualDiagram: { label: "Diagram builder", when: (family: VisualFamily, source: StudioDraftSource) => family !== "chart" && source === "manual" },
} as const satisfies Record<StepKey, { label: string; required?: boolean; when?: (family: VisualFamily, source: StudioDraftSource) => boolean }>;

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
        { id: "e1", source: "n1", target: "n2", label: "" },
        { id: "e2", source: "n2", target: "n3", label: "" },
        { id: "e3", source: "n3", target: "n4", label: "" },
        { id: "e4", source: "n4", target: "n5", label: "yes" },
        { id: "e5", source: "n4", target: "n3", label: "no" },
        { id: "e6", source: "n5", target: "n6", label: "" },
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
        { id: "ae1", source: "a1", target: "a2", label: "requests" },
        { id: "ae2", source: "a2", target: "a3", label: "authn" },
        { id: "ae3", source: "a2", target: "a4", label: "route" },
        { id: "ae4", source: "a4", target: "a5", label: "read/write" },
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
        { id: "de1", source: "d1", target: "d2", label: "input" },
        { id: "de2", source: "d2", target: "d1", label: "output" },
        { id: "de3", source: "d2", target: "d3", label: "store" },
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
      { id: "de1", source: "d1", target: "d2", label: "request" },
      { id: "de2", source: "d2", target: "d4", label: "write" },
      { id: "de3", source: "d4", target: "d3", label: "read" },
      { id: "de4", source: "d3", target: "d1", label: "result" },
    ],
  };
}

let nextEntityId = 0;
const uniqueId = () => `n${Date.now().toString(36)}_${(++nextEntityId).toString(36)}`;

const emptyNode = (family: VisualFamily): NodeDraft => ({
  id: uniqueId(),
  label: "",
  node_type: NODE_TYPES[(family === "chart" ? "flowchart" : family) as "flowchart" | "architecture" | "dfd"][0] ?? "process",
  layer: null,
});

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
  const [chartType, setChartType] = useState<StudioChartType>("bar");
  const [title, setTitle] = useState("");
  const [categories, setCategories] = useState<string[]>(["A", "B", "C"]);
  const [values, setValues] = useState<string[]>(["12", "18", "15"]);
  const [nodes, setNodes] = useState<NodeDraft[]>([]);
  const [edges, setEdges] = useState<EdgeDraft[]>([]);
  const [dfdLevel, setDfdLevel] = useState<0 | 1>(0);
  const [warn, setWarn] = useState<string | null>(null);

  useEffect(() => {
    const allowedSources = family === "chart"
      ? DRAFT_SOURCES.map((source) => source.id)
      : DRAFT_SOURCES.filter((source) => source.id !== "web_search").map((source) => source.id);

    if (!allowedSources.includes(draftSource)) {
      setDraftSource(family === "chart" ? "manual" : "prompt");
    }

    if (family !== "chart" && draftSource === "manual" && nodes.length === 0 && edges.length === 0) {
      const template = templateFor(family, dfdLevel);
      setNodes(template.nodes);
      setEdges(template.edges);
    }
  }, [draftSource, family, dfdLevel, nodes.length, edges.length]);

  const visibleSources = useMemo(() => {
    const allowedSources = family === "chart"
      ? DRAFT_SOURCES.map((source) => source.id)
      : DRAFT_SOURCES.filter((source) => source.id !== "web_search").map((source) => source.id);
    return DRAFT_SOURCES.filter((source) => allowedSources.includes(source.id));
  }, [family]);

  const validation = useMemo(() => {
    const next: Record<string, string> = {};

    if (!prompt.trim() && draftSource !== "manual") {
      next.prompt = "Add a brief description so Sykra knows what to draft.";
    }

    if (draftSource === "conversation") {
      const context = getConversationContext?.();
      if (!context?.excerpt?.trim()) {
        next.conversation = "No conversation context is available yet.";
      }
    }

    if (family === "chart" && draftSource === "manual") {
      const cleanCats = categories.map((c) => c.trim()).filter(Boolean);
      const numbers = values.map((value) => Number(value));

      if (!cleanCats.length) {
        next.chartData = "Add at least one category and one value.";
      }

      if (cleanCats.length !== numbers.length) {
        next.chartData = "Categories and values must match one-to-one.";
      }

      if (numbers.some((value) => Number.isNaN(value))) {
        next.chartData = "Every value must be numeric.";
      }
    }

    if (family !== "chart" && draftSource === "manual") {
      const validNodes = nodes.filter((node) => node.label.trim());
      const nodeIds = new Set(validNodes.map((node) => node.id));

      if (validNodes.length < 2) {
        next.diagramNodes = "Add at least two labeled nodes to create a diagram.";
      }

      const seen = new Set<string>();
      for (const edge of edges) {
        if (!edge.source || !edge.target) {
          next.diagramEdges = "Every flow needs both a start and end node.";
          break;
        }
        if (edge.source === edge.target) {
          next.diagramEdges = "A flow cannot loop from a node to itself.";
          break;
        }
        if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
          next.diagramEdges = "Remove or fix flows that reference deleted nodes.";
          break;
        }
        const signature = `${edge.source}|${edge.target}|${edge.label.trim().toLowerCase()}`;
        if (seen.has(signature)) {
          next.diagramEdges = "Duplicate flows are detected; each source-target-label combination should be unique.";
          break;
        }
        seen.add(signature);
      }
    }

    return next;
  }, [categories, draftSource, edges, family, getConversationContext, nodes, prompt, values]);

  const canDraft = !isGenerating && draftSource !== "manual" && !!prompt.trim() && !validation.prompt && !validation.conversation;

  const patchNode = (id: string, patch: Partial<NodeDraft>) => {
    setNodes((prev) => prev.map((node) => (node.id === id ? { ...node, ...patch } : node)));
    setWarn(null);
  };

  const removeNode = (id: string) => {
    const connectedEdgeCount = edges.filter((edge) => edge.source === id || edge.target === id).length;
    const removed = nodes.filter((node) => node.id !== id);
    setNodes(removed);
    setEdges((prev) => prev.filter((edge) => edge.source !== id && edge.target !== id));
    setWarn(
      connectedEdgeCount > 0
        ? `Node removed. ${connectedEdgeCount} connected flow${connectedEdgeCount === 1 ? "" : "s"} were cleared automatically.`
        : "Node removed."
    );
  };

  const addNode = () => {
    setNodes((prev) => [...prev, emptyNode(family)]);
    setWarn(null);
  };

  const patchEdge = (index: number, patch: Partial<EdgeDraft>) => {
    setEdges((prev) => prev.map((edge, idx) => (idx === index ? { ...edge, ...patch } : edge)));
    setWarn(null);
  };

  const removeEdge = (index: number) => {
    setEdges((prev) => prev.filter((_, idx) => idx !== index));
    setWarn(null);
  };

  const addEdge = () => {
    setEdges((prev) => [...prev, { id: uniqueId(), source: "", target: "", label: "" }]);
    setWarn(null);
  };

  const handleDraft = () => {
    if (!canDraft) {
      setWarn(validation.prompt ?? validation.conversation ?? "Complete the required fields before drafting.");
      return;
    }

    let conversationContext: string | null = null;
    if (draftSource === "conversation") {
      const ctx = getConversationContext?.();
      if (!ctx?.excerpt?.trim()) {
        setWarn("No conversation context is available for this step.");
        return;
      }
      conversationContext = ctx.excerpt;
    }

    onDraft({
      family,
      prompt: prompt.trim(),
      source: draftSource,
      chart_type: chartType,
      dfd_level: family === "dfd" ? dfdLevel : null,
      conversation_context: conversationContext,
      selected_paper_links: null,
    });
  };

  const handleManualGenerate = () => {
    setWarn(null);

    if (family === "chart") {
      const cleanCats = categories.map((category) => category.trim()).filter(Boolean);
      const numbers = values.map((value) => Number(value));

      if (!cleanCats.length || cleanCats.length !== numbers.length || numbers.some((value) => Number.isNaN(value))) {
        setWarn("Fix the chart data before generating: categories must match the numeric values exactly.");
        return;
      }

      const series: StudioChartSeries[] = [{
        label: title.trim() || "Data",
        values: numbers,
        provenance: numbers.map(() => ({ kind: "user_provided" as const })),
      }];

      onGenerate({
        spec_version: 1,
        visual_id: crypto.randomUUID(),
        session_id: sessionId,
        revision: 1,
        title: title.trim() || "Untitled Chart",
        grounding: {
          level: "user_provided",
          grounded_count: 0,
          user_provided_count: numbers.length,
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

    const validNodes = nodes.filter((node) => node.label.trim());
    if (validNodes.length < 2) {
      setWarn("Add at least two labeled nodes before generating a diagram.");
      return;
    }

    const nodeIds = new Set(validNodes.map((node) => node.id));
    const flowErrors = edges.find((edge) => !edge.source || !edge.target || edge.source === edge.target || !nodeIds.has(edge.source) || !nodeIds.has(edge.target));

    if (flowErrors) {
      setWarn("Fix invalid flows so every edge connects two valid nodes.");
      return;
    }

    const duplicateSignature = new Set<string>();
    for (const edge of edges) {
      const signature = `${edge.source}|${edge.target}|${edge.label.trim().toLowerCase()}`;
      if (duplicateSignature.has(signature)) {
        setWarn("Duplicate edge values were detected. Each flow should be unique.");
        return;
      }
      duplicateSignature.add(signature);
    }

    onGenerate({
      spec_version: 1,
      visual_id: crypto.randomUUID(),
      session_id: sessionId,
      revision: 1,
      title: title.trim() || (family === "dfd" ? `DFD Level ${dfdLevel}` : family === "flowchart" ? "Process Flowchart" : "System Architecture"),
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
        nodes: validNodes.map((node) => ({ id: node.id, label: node.label.trim(), node_type: node.node_type, layer: node.layer })),
        edges: edges
          .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) && edge.source !== edge.target)
          .map((edge) => ({ source: edge.source, target: edge.target, label: edge.label.trim() || null })),
        dfd_level: family === "dfd" ? dfdLevel : null,
      },
      created_at: new Date().toISOString(),
    });
  };

  const inputCls = "w-full rounded-lg border border-line bg-paper px-3 py-2 text-[12.5px] text-ink placeholder:text-ink-soft/50 focus:border-indigo/50 focus:outline-none focus:ring-2 focus:ring-indigo/10";

  const showManualBuilder = draftSource === "manual";
  const diagramNodeTypes = family === "chart" ? NODE_TYPES.flowchart : NODE_TYPES[family as Exclude<VisualFamily, "chart">];

  const chartPreview = useMemo(() => {
    const safeCategories = categories.length ? categories : ["A", "B", "C"];
    const safeValues = values.length ? values.map((value) => Number(value) || 0) : [12, 18, 15];
    const maxValue = Math.max(...safeValues, 1);

    return {
      categories: safeCategories,
      values: safeValues,
      maxValue,
    };
  }, [categories, values]);

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <SectionLabel title="Visual Family" />
      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {FAMILIES.map((item) => (
          <motion.button
            key={item.id}
            onClick={() => setFamily(item.id)}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.98 }}
            className={`flex flex-col items-start gap-2 rounded-xl border p-3.5 text-left transition-all ${
              family === item.id ? "border-indigo/50 bg-indigo-tint/50 shadow-md shadow-indigo/10" : "border-line bg-paper hover:border-indigo/30 hover:shadow-sm"
            }`}
          >
            <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${family === item.id ? "bg-indigo text-white" : "bg-paper-dim text-ink-soft"}`}>
              {item.icon}
            </div>
            <div>
              <p className="text-[12.5px] font-semibold text-ink">{item.label}</p>
              <p className="text-[10.5px] text-ink-soft mt-0.5">{item.desc}</p>
            </div>
          </motion.button>
        ))}
      </div>

      <SectionLabel title="Describe the visual" />
      <div className="mb-6">
        <label className="mb-1.5 block text-[11.5px] font-medium text-ink-soft" htmlFor="visual-description">
          What should Sykra generate?
        </label>
        <textarea
          id="visual-description"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          placeholder={
            family === "chart"
              ? "e.g., Bar chart comparing accuracy across BERT, GPT-2, and T5"
              : family === "flowchart"
                ? "e.g., Login flow with MFA fallback and secure token validation"
                : family === "architecture"
                  ? "e.g., RAG architecture with retrieval, ranking, and generation layers"
                  : "e.g., Data flow for intake, validation, storage, and reporting"
          }
          aria-invalid={Boolean(validation.prompt)}
          className={`${inputCls} resize-none ${validation.prompt ? "border-danger/40 focus:border-danger/60" : ""}`}
        />
        <p className="mt-2 text-[11px] text-ink-soft leading-relaxed">
          Required for prompt-based drafting. If you already know the data, use “Use my data.”
        </p>
        {validation.prompt && <p className="mt-2 text-[11px] text-danger">{validation.prompt}</p>}
      </div>

      <SectionLabel title="Source" />
      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-5">
        {visibleSources.map((source) => (
          <button
            key={source.id}
            type="button"
            onClick={() => setDraftSource(source.id)}
            className={`flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all ${
              draftSource === source.id ? "border-indigo/50 bg-indigo-tint/50 shadow-md shadow-indigo/10" : "border-line bg-paper hover:border-indigo/30 hover:shadow-sm"
            }`}
          >
            <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${draftSource === source.id ? "bg-indigo text-white" : "bg-paper-dim text-ink-soft"}`}>
              {source.icon}
            </div>
            <div>
              <p className="text-[12.5px] font-semibold text-ink">{source.title}</p>
              <p className="text-[11px] text-ink-soft mt-0.5">{source.desc}</p>
            </div>
          </button>
        ))}
      </div>

      {family === "chart" && (
        <>
          <SectionLabel title="Chart Type" />
          <div className="mb-8 flex flex-wrap gap-2">
            {CHART_TYPES.map((chart) => (
              <button
                key={chart.id}
                type="button"
                onClick={() => setChartType(chart.id)}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-[12px] font-medium transition-all ${
                  chartType === chart.id ? "border-indigo/50 bg-indigo text-white shadow-md shadow-indigo/20" : "border-line bg-paper text-ink-soft hover:border-indigo/30 hover:text-ink"
                }`}
              >
                {chart.icon}
                {chart.label}
              </button>
            ))}
          </div>
        </>
      )}

      {family === "dfd" && (
        <>
          <SectionLabel title="DFD Level" />
          <div className="mb-8 flex items-center gap-1 rounded-lg bg-paper-dim p-1 w-fit">
            {[0, 1].map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setDfdLevel(level as 0 | 1)}
                className={`rounded-md px-3 py-1.5 text-[11.5px] font-medium transition-all ${
                  dfdLevel === level ? "bg-paper text-ink shadow-sm" : "text-ink-soft hover:text-ink"
                }`}
              >
                Level {level}
              </button>
            ))}
          </div>
        </>
      )}

      {showManualBuilder && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8 space-y-6 rounded-xl border border-line bg-paper p-4"
        >
          {family === "chart" ? (
            <>
              <SectionLabel title="Manual Chart Data" />

              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-[11.5px] font-medium text-ink-soft" htmlFor="chart-title">
                    Chart title <span className="text-ink-soft/60">(optional)</span>
                  </label>
                  <input
                    id="chart-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g., Model Accuracy Comparison"
                    className={inputCls}
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-[11.5px] font-medium text-ink-soft" htmlFor="chart-categories">
                    Categories <span className="text-ink-soft/60">1 per item</span>
                  </label>
                  <input
                    id="chart-categories"
                    value={categories.join(", ")}
                    onChange={(e) => setCategories(e.target.value.split(",").map((category) => category.trim()).filter(Boolean))}
                    placeholder="BERT, GPT-2, T5"
                    className={inputCls}
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-[11.5px] font-medium text-ink-soft" htmlFor="chart-values">
                    Values <span className="text-ink-soft/60">must match the category count</span>
                  </label>
                  <input
                    id="chart-values"
                    value={values.join(", ")}
                    onChange={(e) => setValues(e.target.value.split(",").map((value) => value.trim()))}
                    placeholder="88.5, 91.2, 94.7"
                    className={inputCls}
                  />
                </div>
              </div>

              <div className="rounded-xl border border-line bg-paper-dim/30 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-ink-soft">Live preview</p>
                  <span className="text-[10.5px] text-ink-soft">{chartType}</span>
                </div>
                <SimpleChartPreview categories={chartPreview.categories} values={chartPreview.values} maxValue={chartPreview.maxValue} />
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-[220px] flex-1">
                  <label className="mb-1.5 block text-[11.5px] font-medium text-ink-soft" htmlFor="diagram-title">
                    Diagram title <span className="text-ink-soft/60">(optional)</span>
                  </label>
                  <input
                    id="diagram-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={family === "dfd" ? `DFD Level ${dfdLevel} — title` : "Diagram title"}
                    className={inputCls}
                  />
                </div>

                {family === "dfd" && (
                  <div className="flex items-center gap-1 rounded-lg bg-paper-dim p-1">
                    {[0, 1].map((level) => (
                      <button
                        key={level}
                        type="button"
                        onClick={() => setDfdLevel(level as 0 | 1)}
                        className={`rounded-md px-3 py-1.5 text-[11.5px] font-medium transition-all ${
                          dfdLevel === level ? "bg-paper text-ink shadow-sm" : "text-ink-soft hover:text-ink"
                        }`}
                      >
                        Level {level}
                      </button>
                    ))}
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => {
                    const template = templateFor(family, dfdLevel);
                    setNodes(template.nodes);
                    setEdges(template.edges);
                  }}
                  className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[11.5px] font-medium text-ink-soft hover:text-ink"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset template
                </button>
              </div>

              <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
                <div className="space-y-4">
                  <SectionLabel title={`Nodes (${nodes.length})`} />
                  <div className="space-y-2">
                    {nodes.map((node) => (
                      <div key={node.id} className="flex items-center gap-2">
                        <div className="flex-1">
                          <label className="mb-1 block text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-soft">Label</label>
                          <input
                            value={node.label}
                            onChange={(event) => patchNode(node.id, { label: event.target.value })}
                            placeholder="e.g., Payment Service"
                            className={inputCls}
                          />
                        </div>

                        <div className="w-28 shrink-0">
                          <label className="mb-1 block text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-soft">Type</label>
                          <select
                            value={node.node_type}
                            onChange={(event) => patchNode(node.id, { node_type: event.target.value as NodeType })}
                            className="w-full rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                          >
                            {diagramNodeTypes.map((type) => (
                              <option key={type} value={type}>{type}</option>
                            ))}
                          </select>
                        </div>

                        <button
                          type="button"
                          onClick={() => removeNode(node.id)}
                          className="mt-5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-danger/10 hover:text-danger"
                          aria-label={`Delete node ${node.label || "unnamed"}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}

                    <button
                      type="button"
                      onClick={addNode}
                      className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Add node
                    </button>
                  </div>
                </div>

                <div className="rounded-xl border border-line bg-paper-dim/30 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-ink-soft">Live preview</p>
                    <span className="text-[10.5px] text-ink-soft">{nodes.length} nodes</span>
                  </div>
                  <SimpleDiagramPreview nodes={nodes} edges={edges} />
                </div>
              </div>

              <div className="mt-6 space-y-3">
                <SectionLabel title={`Flows / Edges (${edges.length})`} />
                <div className="space-y-2">
                  {edges.map((edge, index) => (
                    <div key={edge.id} className="flex items-center gap-2">
                      <div className="flex-1">
                        <label className="mb-1 block text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-soft">From</label>
                        <select
                          value={edge.source}
                          onChange={(event) => patchEdge(index, { source: event.target.value })}
                          className="w-full rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                        >
                          <option value="">Select source</option>
                          {nodes.map((node) => (
                            <option key={node.id} value={node.id}>{node.label || node.id}</option>
                          ))}
                        </select>
                      </div>

                      <div className="pt-5">
                        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                      </div>

                      <div className="flex-1">
                        <label className="mb-1 block text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-soft">To</label>
                        <select
                          value={edge.target}
                          onChange={(event) => patchEdge(index, { target: event.target.value })}
                          className="w-full rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                        >
                          <option value="">Select target</option>
                          {nodes.map((node) => (
                            <option key={node.id} value={node.id}>{node.label || node.id}</option>
                          ))}
                        </select>
                      </div>

                      <div className="w-28 shrink-0">
                        <label className="mb-1 block text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-soft">Label</label>
                        <input
                          value={edge.label}
                          onChange={(event) => patchEdge(index, { label: event.target.value })}
                          placeholder="optional"
                          className="w-full rounded-lg border border-line bg-paper px-2 py-2 text-[12px] text-ink focus:border-indigo/50 focus:outline-none"
                        />
                      </div>

                      <button
                        type="button"
                        onClick={() => removeEdge(index)}
                        className="mt-5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-danger/10 hover:text-danger"
                        aria-label={`Delete edge ${index + 1}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>

                <button
                  type="button"
                  onClick={addEdge}
                  className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add flow
                </button>
              </div>
            </>
          )}
        </motion.div>
      )}

      {validation.conversation && (
        <p className="mb-3 text-[11px] text-danger">{validation.conversation}</p>
      )}

      {warn && (
        <div
          role="status"
          aria-live="polite"
          className="mt-6 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger animate-fade-up"
        >
          {warn}
        </div>
      )}

      <div className="mt-8 flex items-center justify-between gap-4 rounded-2xl border border-line bg-paper-dim/40 px-4 py-3">
        <div className="text-[11px] text-ink-soft">
          {draftSource === "manual"
            ? "Manual mode uses a direct spec builder and live preview."
            : canDraft
              ? "Ready to draft a visual from your prompt."
              : "Add the required description before drafting."}
        </div>

        <div className="flex items-center gap-3">
          {draftSource === "manual" && (
            <motion.button
              type="button"
              onClick={handleManualGenerate}
              disabled={isGenerating}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="rounded-xl bg-indigo px-5 py-2.5 text-[12.5px] font-semibold text-white shadow-lg shadow-indigo/25 transition-all hover:bg-indigo-dark disabled:opacity-50"
            >
              {isGenerating ? "Generating..." : "Generate manual visual"}
            </motion.button>
          )}

          {draftSource !== "manual" && (
            <motion.button
              type="button"
              onClick={handleDraft}
              disabled={!canDraft}
              whileHover={{ scale: canDraft ? 1.02 : 1 }}
              whileTap={{ scale: canDraft ? 0.98 : 1 }}
              className="flex items-center gap-2 rounded-xl bg-indigo px-5 py-2.5 text-[12.5px] font-semibold text-white shadow-lg shadow-indigo/25 transition-all hover:bg-indigo-dark disabled:opacity-50"
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
          )}
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ title }: { title: string }) {
  return (
    <div className="mb-3">
      <span className="text-[12px] font-semibold uppercase tracking-[0.14em] text-ink-soft">{title}</span>
    </div>
  );
}

function SimpleChartPreview({ categories, values, maxValue }: { categories: string[]; values: number[]; maxValue: number }) {
  return (
    <div className="flex h-32 items-end gap-2 pt-4">
      {values.map((value, index) => (
        <div key={`${categories[index] ?? "cat"}-${index}`} className="flex flex-1 flex-col items-center gap-2">
          <div
            className="w-full rounded-t-lg bg-indigo/80 shadow-inner shadow-white/10"
            style={{ height: `${Math.max(18, (value / maxValue) * 100)}%` }}
            title={`${categories[index] ?? "Series"}: ${value}`}
          />
          <span className="text-[9px] text-ink-soft">{categories[index]?.slice(0, 6) ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

function SimpleDiagramPreview({ nodes, edges }: { nodes: NodeDraft[]; edges: EdgeDraft[] }) {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const canvas = { width: 280, height: 180 };
  const positions = new Map<string, { x: number; y: number }>();

  nodes.forEach((node, index) => {
    const column = Math.min(index % 3, 2);
    const row = Math.floor(index / 3);
    positions.set(node.id, {
      x: 36 + column * 90,
      y: 32 + row * 58,
    });
  });

  return (
    <svg width="100%" height="180" viewBox={`0 0 ${canvas.width} ${canvas.height}`} className="block rounded-lg bg-paper">
      {edges.map((edge) => {
        const source = positions.get(edge.source);
        const target = positions.get(edge.target);
        if (!source || !target) return null;

        return (
          <g key={edge.id}>
            <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="#7a9e8e" strokeWidth="1.5" strokeDasharray="6 4" />
            {edge.label && (
              <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 6} fontSize="8" fill="#3a3d3a" textAnchor="middle">
                {edge.label}
              </text>
            )}
          </g>
        );
      })}

      {nodes.map((node) => {
        const pos = positions.get(node.id) ?? { x: 40, y: 40 };
        return (
          <g key={node.id}>
            <circle cx={pos.x} cy={pos.y} r={18} fill={node.node_type === "decision" ? "#cd846b" : node.node_type === "store" ? "#a9b8aa" : "#7a9e8e"} opacity={0.85} />
            <text x={pos.x} y={pos.y + 2} textAnchor="middle" fontSize="7.5" fill="#ffffff">
              {node.label.slice(0, 10) || "Node"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}