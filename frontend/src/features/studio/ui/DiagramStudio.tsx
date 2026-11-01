"use client";

import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnEdgesChange,
  type OnNodesChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Download,
  FilePlus2,
  Minus,
  Plus,
  Redo2,
  Save,
  Search,
  Trash2,
  Undo2,
  Workflow,
} from "lucide-react";
import {
  createFlowchartDocument,
  type DiagramDocument,
  type DiagramNode,
  validateDiagramDocument,
} from "../core/document";
import { diagramApi } from "@/lib/diagram-api";

type EditorNode = Node<{ label: string; kind: DiagramNode["type"] }>;

const palette = [
  { type: "start" as const, label: "Start / End", color: "bg-forest text-white" },
  { type: "process" as const, label: "Process", color: "bg-indigo-tint text-ink" },
  { type: "decision" as const, label: "Decision", color: "bg-gold-tint text-ink" },
  { type: "data" as const, label: "Data", color: "bg-accent-tint text-ink" },
];

function StudioNode({ data, selected }: NodeProps<EditorNode>) {
  const shape = data.kind === "start" ? "rounded-full" : data.kind === "decision" ? "rotate-45" : "rounded-xl";
  const textShape = data.kind === "decision" ? "-rotate-45" : "";
  return (
    <div className={`min-w-32 border border-line px-5 py-3 text-center text-sm shadow-soft ${shape} ${selected ? "ring-2 ring-accent" : ""} ${data.kind === "start" ? "bg-forest text-white" : data.kind === "decision" ? "bg-gold-tint" : data.kind === "data" ? "bg-accent-tint" : "bg-white"}`}>
      <Handle type="target" position={Position.Top} className="!bg-indigo" />
      <span className={`block ${textShape}`}>{data.label}</span>
      <Handle type="source" position={Position.Bottom} className="!bg-indigo" />
    </div>
  );
}

const nodeTypes = { studio: StudioNode };

function DiagramStudioInner({ sessionId, initialDocument, onChange }: { sessionId?: string; initialDocument?: DiagramDocument; onChange?: (document: DiagramDocument) => void }) {
  const [document, setDocument] = useState<DiagramDocument>(() => initialDocument ?? createFlowchartDocument());
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const [nodes, setNodes, onNodesChange] = useNodesState<EditorNode>(toFlowNodes(page.nodes));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(page.edges);
  const [selectedId, setSelectedId] = useState<string>();
  const [query, setQuery] = useState("");
  const [openPalette, setOpenPalette] = useState(true);
  const [savedId, setSavedId] = useState<string>();
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [history, setHistory] = useState<DiagramDocument[]>([]);
  const [future, setFuture] = useState<DiagramDocument[]>([]);
  const handleNodesChange: OnNodesChange<EditorNode> = (changes) => {
    const nextNodes = applyNodeChanges(changes, nodes);
    onNodesChange(changes);
    commit(nextNodes, edges);
  };
  const handleEdgesChange: OnEdgesChange<Edge> = (changes) => {
    const nextEdges = applyEdgeChanges(changes, edges);
    onEdgesChange(changes);
    commit(nodes, nextEdges);
  };
  const handleNodeClick: NodeMouseHandler<EditorNode> = (_, node) => setSelectedId(node.id);

  const commit = useCallback((nextNodes: Node[], nextEdges: Edge[]) => {
    const nextPage = {
      ...page,
      nodes: nextNodes.map((node) => ({
        id: node.id,
        type: (node.data?.kind ?? "process") as DiagramNode["type"],
        position: node.position,
        label: String(node.data?.label ?? "Untitled"),
      })),
      edges: nextEdges.map(({ id, source, target, label }) => ({ id, source, target, ...(typeof label === "string" ? { label } : {}) })),
    };
    const nextDocument = { ...document, pages: document.pages.map((item) => item.id === page.id ? nextPage : item), updatedAt: new Date().toISOString() };
    setDocument(nextDocument);
    setHistory((items) => [...items.slice(-19), document]);
    setFuture([]);
    onChange?.(validateDiagramDocument(nextDocument));
    setSaveState("saving");
  }, [document, onChange, page]);

  useEffect(() => {
    if (saveState !== "saving") return;
    const timer = window.setTimeout(() => {
      if (!sessionId) {
        setSaveState("saved");
        return;
      }
      const save = savedId
        ? diagramApi.update(savedId, sessionId, document)
        : diagramApi.create(sessionId, document);
      void save.then((result) => {
        setSavedId(result.id);
        setSaveState("saved");
      }).catch(() => setSaveState("error"));
    }, 600);
    return () => window.clearTimeout(timer);
  }, [document, saveState, savedId, sessionId]);

  useEffect(() => {
    if (!sessionId || initialDocument) return;
    void diagramApi.list(sessionId).then((result) => {
      const latest = result.documents[0];
      if (!latest) return;
      const parsed = validateDiagramDocument(latest.document);
      setDocument(parsed);
      setSavedId(latest.id);
      setNodes(toFlowNodes(parsed.pages[0].nodes));
      setEdges(parsed.pages[0].edges);
    }).catch(() => setSaveState("error"));
  }, [initialDocument, sessionId, setEdges, setNodes]);

  const onConnect = useCallback((connection: Connection) => {
    const nextEdges = addEdge({ ...connection, type: "smoothstep" }, edges);
    setEdges(nextEdges);
    commit(nodes, nextEdges);
  }, [commit, edges, nodes, setEdges]);

  const addNode = (kind: DiagramNode["type"]) => {
    const id = crypto.randomUUID();
    const nextNode: EditorNode = {
      id,
      type: "studio",
      position: { x: 180 + nodes.length * 24, y: 120 + nodes.length * 24 },
      data: { kind, label: palette.find((item) => item.type === kind)?.label ?? "Untitled" },
    };
    const nextNodes = [...nodes, nextNode];
    setNodes(nextNodes);
    setSelectedId(id);
    commit(nextNodes, edges);
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    const nextNodes = nodes.filter((node) => node.id !== selectedId);
    const nextEdges = edges.filter((edge) => edge.source !== selectedId && edge.target !== selectedId);
    setNodes(nextNodes);
    setEdges(nextEdges);
    setSelectedId(undefined);
    commit(nextNodes, nextEdges);
  };

  const restore = (next: DiagramDocument, previous: DiagramDocument[], nextFuture: DiagramDocument[]) => {
    const nextPage = next.pages.find((item) => item.id === next.activePageId) ?? next.pages[0];
    setDocument(next);
    setNodes(toFlowNodes(nextPage.nodes));
    setEdges(nextPage.edges);
    setHistory(previous);
    setFuture(nextFuture);
    setSaveState("saving");
  };

  const undo = () => {
    const previous = history.at(-1);
    if (!previous) return;
    restore(previous, history.slice(0, -1), [document, ...future]);
  };

  const redo = () => {
    const next = future[0];
    if (!next) return;
    restore(next, [...history, document], future.slice(1));
  };

  const filteredPalette = useMemo(() => palette.filter((item) => item.label.toLowerCase().includes(query.toLowerCase())), [query]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper text-ink">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-white px-4 py-2">
        <div className="mr-3 flex items-center gap-2 font-serif text-lg"><Workflow className="h-5 w-5 text-indigo" /> Diagram Studio</div>
        <button className="studio-tool" aria-label="New document" onClick={() => { const next = createFlowchartDocument(); setDocument(next); setNodes([]); setEdges([]); }}><FilePlus2 className="h-4 w-4" /></button>
        <button className="studio-tool disabled:opacity-30" aria-label="Undo" disabled={!history.length} onClick={undo}><Undo2 className="h-4 w-4" /></button>
        <button className="studio-tool disabled:opacity-30" aria-label="Redo" disabled={!future.length} onClick={redo}><Redo2 className="h-4 w-4" /></button>
        <button className="studio-tool" aria-label="Delete selected" onClick={deleteSelected}><Trash2 className="h-4 w-4" /></button>
        <span className="mx-1 h-5 w-px bg-line" />
        <button className="studio-tool" aria-label="Zoom out"><Minus className="h-4 w-4" /></button>
        <button className="studio-tool" aria-label="Zoom in"><Plus className="h-4 w-4" /></button>
        <div className="ml-auto flex items-center gap-3 text-xs text-ink-soft"><span>{saveState === "saving" ? "Saving..." : saveState === "error" ? "Save failed" : "Saved"}</span><button className="studio-tool" aria-label="Export document" onClick={() => downloadJson(document)}><Download className="h-4 w-4" /></button><button className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white" onClick={() => setSaveState("saving")}><Save className="mr-1 inline h-3.5 w-3.5" /> Save</button></div>
      </div>
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-white">
          <label className="m-3 flex items-center gap-2 rounded-lg border border-line px-2.5 py-2"><Search className="h-4 w-4 text-ink-soft" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search shapes" className="min-w-0 bg-transparent text-xs outline-none" /></label>
          <button className="flex items-center gap-2 px-4 py-2 text-left text-xs font-semibold" onClick={() => setOpenPalette((value) => !value)}>{openPalette ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Flowchart</button>
          {openPalette && <div className="space-y-2 px-3">{filteredPalette.map((item) => <button key={item.type} onClick={() => addNode(item.type)} className={`flex w-full items-center gap-2 rounded-lg border border-line px-3 py-2 text-left text-xs hover:border-indigo ${item.color}`}><span className="h-5 w-5 rounded border border-current/30" />{item.label}</button>)}</div>}
          <div className="mt-auto border-t border-line p-3 text-xs text-ink-soft"><p className="font-semibold text-ink">Tip</p><p className="mt-1 leading-5">Click a shape to add it, then drag between handles to connect nodes.</p></div>
        </aside>
        <main className="min-w-0 flex-1">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange} onConnect={onConnect} onNodeClick={handleNodeClick} onPaneClick={() => setSelectedId(undefined)} fitView>
            <Background color="var(--line)" gap={20} size={1} />
            <Controls />
          </ReactFlow>
        </main>
        <aside className="hidden w-64 shrink-0 border-l border-line bg-white p-4 lg:block"><p className="text-label text-ink-soft">Format</p><h2 className="mt-2 font-serif text-xl">{selectedId ? "Selected shape" : "No selection"}</h2><p className="mt-2 text-xs leading-5 text-ink-soft">{selectedId ? "Use the handles to connect this shape or delete it from the toolbar." : "Select a shape to inspect and edit its properties."}</p></aside>
      </div>
      <div className="flex shrink-0 items-center gap-2 border-t border-line bg-white px-3 py-2 text-xs"><button className="rounded-md bg-indigo-tint px-3 py-1.5 font-medium">Page 1</button><button className="rounded-md p-1.5 text-ink-soft hover:bg-paper" aria-label="Add page"><Plus className="h-4 w-4" /></button></div>
    </div>
  );
}

export function DiagramStudio(props: { sessionId?: string; initialDocument?: DiagramDocument; onChange?: (document: DiagramDocument) => void }) {
  return <ReactFlowProvider><DiagramStudioInner {...props} /></ReactFlowProvider>;
}

function toFlowNodes(nodes: DiagramNode[]): EditorNode[] {
  return nodes.map((node) => ({ id: node.id, type: "studio", position: node.position, data: { kind: node.type, label: node.label } }));
}

function downloadJson(document: DiagramDocument) {
  const blob = new Blob([JSON.stringify(document, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = `${document.title.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "diagram"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
