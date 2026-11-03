"use client";

import {
  Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider,
  addEdge, applyEdgeChanges, applyNodeChanges, useEdgesState, useNodesState,
  useReactFlow, type Connection, type Edge, type Node, type NodeProps,
  type OnEdgesChange, type OnNodesChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown, ChevronRight, Copy, Download, FilePlus2,
  FolderOpen, Plus, Redo2, Save,
  Search, Trash2, Undo2, Workflow, X, ZoomIn, ZoomOut, Maximize2,
} from "lucide-react";
import { ConfirmDialog, PromptDialog } from "@/components/ConfirmDialog";
import { diagramApi, type SavedDiagram } from "@/lib/diagram-api";
import { createDiagramDocument, type DiagramDocument, type DiagramNode, validateDiagramDocument } from "../core/document";
import { migrateDiagramDocument } from "../core/migrations";
import { documentToSvg, exportPng, type ExportOptions } from "../core/export";
import { exportMermaid } from "../core/interoperability";
import { loadDiagramType } from "../registry/registry";
import type { DiagramIssue, DiagramTypeDefinition } from "../registry/definition";
import { useTheme } from "@/lib/theme";

type EditorNode = Node<{ label: string; kind: DiagramNode["type"]; visual: Shape["preview"] }>;
type Tab = "canvas" | "history";
type Shape = { label: string; type: DiagramNode["type"]; preview: "rect" | "round" | "ellipse" | "diamond" | "data" | "cylinder" | "cloud" | "actor" | "arrow" | "bar" };

const groups: Array<{ label: string; items: Shape[] }> = [
  { label: "General", items: [
    ["Rectangle", "process", "rect"], ["Rounded rectangle", "process", "round"], ["Ellipse", "process", "ellipse"],
    ["Diamond", "decision", "diamond"], ["Triangle", "process", "diamond"], ["Hexagon", "process", "round"],
    ["Cylinder", "database", "cylinder"], ["Cloud", "service", "cloud"], ["Text", "note", "rect"], ["Note", "note", "rect"],
  ].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
  { label: "Flowchart", items: [
    ["Start / End", "start", "ellipse"], ["Process", "process", "round"], ["Decision", "decision", "diamond"],
    ["Data", "data", "data"], ["Document", "note", "rect"], ["Predefined process", "process", "round"],
    ["Manual input", "data", "data"], ["Connector", "process", "ellipse"], ["Database", "database", "cylinder"],
  ].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
  { label: "DFD", items: [["External entity", "external", "rect"], ["Process", "process", "ellipse"], ["Data store", "store", "rect"], ["Data flow arrow", "process", "arrow"]].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
  { label: "Architecture", items: [["Service", "service", "round"], ["Database", "database", "cylinder"], ["Queue", "service", "rect"], ["API gateway", "service", "round"], ["Client / browser", "client", "rect"], ["User", "actor", "actor"], ["Cloud", "service", "cloud"], ["Layer box", "boundary", "rect"]].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
  { label: "Use Case", items: [["Actor", "actor", "actor"], ["Use case", "use-case", "ellipse"], ["System boundary", "system-boundary", "rect"], ["Include / extend arrow", "process", "arrow"]].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
  { label: "Charts", items: [["Bar chart", "chart", "bar"], ["Line chart", "chart", "arrow"], ["Pie chart", "chart", "ellipse"], ["Scatter chart", "chart", "round"]].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
  { label: "Arrows", items: [["Straight", "process", "arrow"], ["Elbow", "process", "arrow"], ["Curved", "process", "arrow"], ["Dashed", "process", "arrow"], ["Double-headed", "process", "arrow"]].map(([label, type, preview]) => ({ label, type: type as DiagramNode["type"], preview: preview as Shape["preview"] })) },
];

function ShapePreview({ shape, className = "h-5 w-5" }: { shape: Shape["preview"]; className?: string }) {
  const common = { fill: "currentColor", opacity: ".16", stroke: "currentColor", strokeWidth: 1.5 };
  if (shape === "diamond") return <svg viewBox="0 0 32 24" className="h-5 w-5"><path d="m16 2 14 10-14 10L2 12Z" fill="currentColor" opacity=".16" stroke="currentColor" strokeWidth="1.5" /></svg>;
  if (shape === "cylinder") return <svg viewBox="0 0 32 24" className="h-5 w-5"><path d="M4 5c0-3 24-3 24 0v14c0 3-24 3-24 0Z" fill="currentColor" opacity=".16" stroke="currentColor" strokeWidth="1.5" /><ellipse cx="16" cy="5" rx="12" ry="3" fill="currentColor" opacity=".2" stroke="currentColor" strokeWidth="1.5" /></svg>;
  if (shape === "actor") return <svg viewBox="0 0 32 24" className="h-5 w-5"><circle cx="16" cy="5" r="3" fill="none" stroke="currentColor" /><path d="M16 8v7m-6-4 6 2 6-2m-9 9 3-7 3 7" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
  if (shape === "arrow") return <svg viewBox="0 0 32 24" className="h-5 w-5"><path d="M3 12h24m-6-6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
  if (shape === "cloud") return <svg viewBox="0 0 32 24" className="h-5 w-5"><path d="M7 19h17a5 5 0 0 0 1-9.9A8 8 0 0 0 9.5 7 6 6 0 0 0 7 19Z" fill="currentColor" opacity=".16" stroke="currentColor" strokeWidth="1.5" /></svg>;
  if (shape === "data") return <svg viewBox="0 0 32 24" className={className}><path d="m2 4h27l-4 16H2Z" {...common} /></svg>;
  if (shape === "bar") return <svg viewBox="0 0 32 24" className={className}><path d="M4 20V12h5v8m4 0V6h5v14m4 0V9h5v11" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
  return <svg viewBox="0 0 32 24" className={className}><rect x="3" y="4" width="26" height="16" rx={shape === "round" ? 7 : shape === "ellipse" ? 12 : 2} {...common} /></svg>;
}

function NodeShape({ visual }: { visual: Shape["preview"] }) {
  const common = { fill: "var(--indigo-tint)", stroke: "var(--indigo)", strokeWidth: 2 };
  if (visual === "diamond") return <polygon points="80,4 156,48 80,92 4,48" {...common} />;
  if (visual === "cylinder") return <><path d="M18 18c0-12 124-12 124 0v60c0 12-124 12-124 0Z" {...common} /><ellipse cx="80" cy="18" rx="62" ry="12" fill="var(--paper)" stroke="var(--indigo)" strokeWidth="2" /></>;
  if (visual === "cloud") return <path d="M35 78h92a24 24 0 0 0 4-47 38 38 0 0 0-72-4 28 28 0 0 0-24 51Z" {...common} />;
  if (visual === "actor") return <><circle cx="80" cy="19" r="13" fill="var(--indigo-tint)" stroke="var(--indigo)" strokeWidth="2" /><path d="M80 32v30m-25-15 25 8 25-8M62 88l18-26 18 26" fill="none" stroke="var(--indigo)" strokeWidth="2" /></>;
  if (visual === "arrow") return <path d="M15 48h115m-28-25 28 25-28 25" fill="none" stroke="var(--indigo)" strokeWidth="3" />;
  if (visual === "data") return <path d="m8 18h144l-14 60H8Z" {...common} />;
  if (visual === "bar") return <><path d="M18 82h124" stroke="var(--indigo)" strokeWidth="2" /><path d="M30 82V54h20v28m16 0V28h20v54m16 0V42h20v40" fill="var(--indigo-tint)" stroke="var(--indigo)" strokeWidth="2" /></>;
  return <rect x="8" y="12" width="144" height="72" rx={visual === "round" ? 18 : visual === "ellipse" ? 36 : 5} {...common} />;
}

function StudioNode({ data, selected }: NodeProps<EditorNode>) {
  return <div className={`relative h-24 w-40 text-center text-sm text-ink ${selected ? "ring-2 ring-accent rounded-lg" : ""}`}>
    <Handle type="target" position={Position.Top} className="!bg-indigo" />
    <Handle type="target" position={Position.Right} className="!bg-indigo" />
    <Handle type="source" position={Position.Bottom} className="!bg-indigo" />
    <Handle type="source" position={Position.Left} className="!bg-indigo" />
    <svg viewBox="0 0 160 96" className="absolute inset-0 h-full w-full" aria-hidden="true"><NodeShape visual={data.visual} /></svg>
    <span className="relative z-10 flex h-full items-center justify-center px-4">{data.label}</span>
  </div>;
}
const nodeTypes = { studio: StudioNode };

function Menu({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return <div className="relative"><button aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="px-2 py-1 text-[13px] text-ink-soft hover:bg-paper-dim hover:text-ink">{label}</button>{open && <div role="menu" className="absolute left-0 top-full z-50 mt-1 min-w-52 rounded-lg border border-line bg-paper p-1 shadow-xl" onMouseLeave={() => setOpen(false)}>{children}</div>}</div>;
}
function MenuItem({ children, onClick, disabled = false }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean }) {
  return <button role="menuitem" disabled={disabled} onClick={onClick} className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs text-ink hover:bg-paper-dim disabled:opacity-40">{children}</button>;
}
function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return <section><button onClick={() => setOpen((value) => !value)} className="flex h-8 w-full items-center gap-1 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-soft">{open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}{title}</button>{open && children}</section>;
}
function ToolbarButton({ label, onClick, disabled = false, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return <button title={label} aria-label={label} disabled={disabled} onClick={onClick} className="studio-tool disabled:cursor-not-allowed disabled:opacity-35">{children}</button>;
}

function HistoryGallery({ sessionId, onOpen }: { sessionId?: string; onOpen: (item: SavedDiagram) => void }) {
  const [items, setItems] = useState<SavedDiagram[]>([]);
  useEffect(() => { if (sessionId) void diagramApi.list(sessionId).then((result) => setItems(result.documents)).catch(() => setItems([])); }, [sessionId]);
  return <div className="h-full overflow-auto bg-paper p-6"><div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{items.map((item) => <button key={item.id} onClick={() => onOpen(item)} className="rounded-lg border border-line bg-surface p-4 text-left hover:border-accent"><FolderOpen className="h-8 w-8 text-indigo" /><p className="mt-3 truncate text-sm font-semibold text-ink">{item.title}</p><p className="mt-1 text-xs text-ink-soft">{item.document.pages[0]?.nodes.length ?? 0} shapes</p></button>)}{items.length === 0 && <p className="text-sm text-ink-soft">No saved diagrams yet.</p>}</div></div>;
}

function DiagramStudioInner({ sessionId, initialDocument, onChange, onToggleChat, chatOpen: externalChatOpen }: { sessionId?: string; initialDocument?: DiagramDocument; onChange?: (document: DiagramDocument) => void; onToggleChat?: () => void; chatOpen?: boolean }) {
  const [document, setDocument] = useState<DiagramDocument>(() => initialDocument ?? createDiagramDocument("flowchart", "Untitled diagram"));
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const [nodes, setNodes, onNodesChange] = useNodesState<EditorNode>(toFlowNodes(page.nodes));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(page.edges);
  const [selectedId, setSelectedId] = useState<string>();
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [formatOpen, setFormatOpen] = useState(false);
  const [localChatOpen, setChatOpen] = useState(true);
  const chatOpen = typeof externalChatOpen === "boolean" ? externalChatOpen : localChatOpen;
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<Tab>("canvas");
  const { theme } = useTheme();
  const [history, setHistory] = useState<DiagramDocument[]>([]);
  const [future, setFuture] = useState<DiagramDocument[]>([]);
  const [saveState, setSaveState] = useState<"saved" | "saving">("saved");
  const [savedId, setSavedId] = useState<string>();
  const [definition, setDefinition] = useState<DiagramTypeDefinition>();
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [pageMenuOpen, setPageMenuOpen] = useState(false);
  const [toast, setToast] = useState("");
  const flow = useReactFlow();
  const filteredGroups = useMemo(() => groups.map((group) => ({ ...group, items: group.items.filter((item) => item.label.toLowerCase().includes(search.toLowerCase())) })).filter((group) => group.items.length > 0), [search]);

  useEffect(() => { void loadDiagramType(page.diagramType).then(setDefinition).catch(() => setDefinition(undefined)); }, [page.diagramType]);
  const issues = useMemo<DiagramIssue[]>(() => definition ? definition.validateDocument(document).filter((issue) => !document.dismissedIssues.includes(issue.id)) : [], [definition, document]);
  useEffect(() => { if (!sessionId || initialDocument) return; void diagramApi.list(sessionId).then((result) => { const latest = result.documents[0]; if (!latest) return; const parsed = migrateDiagramDocument(latest.document); setDocument(parsed); setSavedId(latest.id); setNodes(toFlowNodes(parsed.pages[0].nodes)); setEdges(parsed.pages[0].edges); }).catch(() => undefined); }, [initialDocument, sessionId, setEdges, setNodes]);
  useEffect(() => { if (saveState !== "saving") return; const timer = window.setTimeout(() => { if (!sessionId) return setSaveState("saved"); const request = savedId ? diagramApi.update(savedId, sessionId, document) : diagramApi.create(sessionId, document); void request.then((result) => { setSavedId(result.id); setSaveState("saved"); }).catch(() => setSaveState("saved")); }, 600); return () => window.clearTimeout(timer); }, [document, saveState, savedId, sessionId]);

  const commit = useCallback((nextNodes: Node[], nextEdges: Edge[]) => {
    const nextPage = { ...page, nodes: nextNodes.map((node) => ({ id: node.id, type: (node.data?.kind ?? "process") as DiagramNode["type"], position: node.position, label: String(node.data?.label ?? "Untitled"), data: { visual: node.data?.visual } })), edges: nextEdges.map(({ id, source, target, label, type }) => ({ id, source, target, ...(typeof label === "string" ? { label } : {}), ...(typeof type === "string" ? { type } : {}) })) };
    const nextDocument = validateDiagramDocument({ ...document, pages: document.pages.map((item) => item.id === page.id ? nextPage : item), updatedAt: new Date().toISOString() });
    setHistory((items) => [...items.slice(-19), document]); setFuture([]); setDocument(nextDocument); onChange?.(nextDocument); setSaveState("saving");
  }, [document, onChange, page]);
  const handleNodesChange: OnNodesChange<EditorNode> = (changes) => { const next = applyNodeChanges(changes, nodes); onNodesChange(changes); commit(next, edges); };
  const handleEdgesChange: OnEdgesChange<Edge> = (changes) => { const next = applyEdgeChanges(changes, edges); onEdgesChange(changes); commit(nodes, next); };
  const addNode = (shape: Shape, position = { x: 200 + nodes.length * 24, y: 120 + nodes.length * 24 }) => {
    const node: EditorNode = { id: crypto.randomUUID(), type: "studio", position, data: { kind: shape.type, visual: shape.preview, label: shape.label } };
    const next = [...nodes, node]; setNodes(next); setSelectedId(node.id); setFormatOpen(true); commit(next, edges);
    if (shape.type === "chart") setToast("Chart data editor opened"); else setToast(`${shape.label} added`);
  };
  const newDiagram = () => { const next = createDiagramDocument("flowchart", "Untitled diagram"); setDocument(next); setNodes([]); setEdges([]); setSavedId(undefined); setHistory([]); setFuture([]); setTab("canvas"); setSaveState("saving"); };
  const exportCurrent = (kind: "svg" | "png" | "json" | "mmd") => { if (kind === "mmd") { void navigator.clipboard.writeText(exportMermaid(document)); setToast("Mermaid copied"); return; } if (kind === "json") { const link = window.document.createElement("a"); link.href = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/json" })); link.download = `${document.title}.json`; link.click(); return; } const options: ExportOptions = { background: theme, scale: 1 }; const svg = documentToSvg(document, options); if (kind === "svg") { const link = window.document.createElement("a"); link.href = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })); link.download = `${document.title}.svg`; link.click(); } else void exportPng(document, options); setToast(`Exported ${kind.toUpperCase()}`); };
  const undo = () => { const previous = history.at(-1); if (!previous) return; setFuture((items) => [...items, document]); setHistory((items) => items.slice(0, -1)); setDocument(previous); setNodes(toFlowNodes(previous.pages[0].nodes)); setEdges(previous.pages[0].edges); };
  const redo = () => { const next = future.at(-1); if (!next) return; setHistory((items) => [...items, document]); setFuture((items) => items.slice(0, -1)); setDocument(next); setNodes(toFlowNodes(next.pages[0].nodes)); setEdges(next.pages[0].edges); };
  const runCommand = (label: string) => setToast(`${label} ready`);
  const openHistory = (item: SavedDiagram) => {
    try {
      const parsed = migrateDiagramDocument(item.document);
      setDocument(parsed);
      setNodes(toFlowNodes(parsed.pages[0].nodes));
      setEdges(parsed.pages[0].edges);
      setSavedId(item.id);
      setTab("canvas");
    } catch {
      setToast("This saved diagram could not be opened");
    }
  };
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const command = event.metaKey || event.ctrlKey;
      if (command && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); }
      else if (event.key === "+") { event.preventDefault(); flow.zoomIn(); }
      else if (event.key === "-") { event.preventDefault(); flow.zoomOut(); }
      else if (event.key === "0") { event.preventDefault(); flow.setViewport({ x: 0, y: 0, zoom: 1 }); }
      else if (event.key.toLowerCase() === "s") { event.preventDefault(); setSaveState("saving"); }
      else if (event.key.toLowerCase() === "d") { event.preventDefault(); runCommand("Duplicate"); }
      else if (event.key.toLowerCase() === "a") { event.preventDefault(); runCommand("Select all"); }
      else if (event.key === "Backspace" || event.key === "Delete") { if (selectedId) setNodes(nodes.filter((node) => node.id !== selectedId)); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [flow, history, future, nodes, selectedId]);

  return <div className="studio-root">
    <header className="studio-header">
      <div className="studio-header-row"><div className="flex items-center gap-2"><Workflow className="h-5 w-5 text-accent" /><span className="text-base font-semibold text-ink">Diagram Studio</span></div><div className="flex items-center gap-1"><button onClick={() => setTab("canvas")} className={`studio-tab ${tab === "canvas" ? "active" : ""}`}>Canvas</button><button onClick={newDiagram} className="studio-tab">New</button><button onClick={() => setTab("history")} className={`studio-tab ${tab === "history" ? "active" : ""}`}>History</button></div><div className="ml-auto flex items-center gap-2"><span className="text-xs text-ink-soft">{saveState === "saving" ? "Unsaved changes" : "Saved"}</span><button onClick={() => exportCurrent("png")} className="studio-action"><Download className="h-4 w-4" />Export</button></div></div>
      <div className="studio-menu-row"><Menu label="File"><MenuItem onClick={newDiagram}><FilePlus2 className="h-4 w-4" />New diagram</MenuItem><MenuItem onClick={() => setTab("history")}><FolderOpen className="h-4 w-4" />Open from History</MenuItem><MenuItem onClick={() => setSaveState("saving")}><Save className="h-4 w-4" />Save</MenuItem><MenuItem onClick={() => setRenameOpen(true)}>Rename…</MenuItem><MenuItem onClick={() => runCommand("Duplicate")}>Duplicate</MenuItem><MenuItem onClick={() => exportCurrent("png")}>Export as PNG</MenuItem><MenuItem onClick={() => exportCurrent("svg")}>Export as SVG</MenuItem><MenuItem onClick={() => exportCurrent("json")}>Export as JSON</MenuItem><MenuItem onClick={() => exportCurrent("mmd")}>Export as Mermaid</MenuItem><MenuItem onClick={() => setDeleteOpen(true)}><Trash2 className="h-4 w-4" />Delete</MenuItem></Menu><Menu label="Edit"><MenuItem disabled={!history.length} onClick={undo}><Undo2 className="h-4 w-4" />Undo</MenuItem><MenuItem disabled={!future.length} onClick={redo}><Redo2 className="h-4 w-4" />Redo</MenuItem><MenuItem onClick={() => runCommand("Cut")}>Cut</MenuItem><MenuItem onClick={() => runCommand("Copy")}>Copy</MenuItem><MenuItem onClick={() => runCommand("Paste")}>Paste</MenuItem><MenuItem onClick={() => runCommand("Duplicate")}>Duplicate</MenuItem><MenuItem onClick={() => { if (selectedId) setNodes(nodes.filter((node) => node.id !== selectedId)); }}>Delete</MenuItem><MenuItem onClick={() => runCommand("Select all")}>Select all</MenuItem></Menu><Menu label="View"><MenuItem onClick={() => flow.zoomIn()}>Zoom in</MenuItem><MenuItem onClick={() => flow.zoomOut()}>Zoom out</MenuItem><MenuItem onClick={() => flow.fitView()}>Fit view</MenuItem><MenuItem onClick={() => flow.setViewport({ x: 0, y: 0, zoom: 1 })}>Reset zoom</MenuItem><MenuItem onClick={() => runCommand("Grid toggled")}>Toggle grid</MenuItem><MenuItem onClick={() => setPaletteOpen((value) => !value)}>Toggle palette</MenuItem><MenuItem onClick={() => setFormatOpen((value) => !value)}>Toggle format panel</MenuItem><MenuItem onClick={() => { setChatOpen((value) => !value); onToggleChat?.(); }}>Toggle chat</MenuItem></Menu><Menu label="Arrange"><MenuItem onClick={() => runCommand("Bring to front")}>Bring to front</MenuItem><MenuItem onClick={() => runCommand("Send to back")}>Send to back</MenuItem><MenuItem onClick={() => runCommand("Align left")}>Align left</MenuItem><MenuItem onClick={() => runCommand("Align center")}>Align center</MenuItem><MenuItem onClick={() => runCommand("Align right")}>Align right</MenuItem><MenuItem onClick={() => runCommand("Align top")}>Align top</MenuItem><MenuItem onClick={() => runCommand("Align middle")}>Align middle</MenuItem><MenuItem onClick={() => runCommand("Align bottom")}>Align bottom</MenuItem><MenuItem onClick={() => runCommand("Distribute")}>Distribute</MenuItem><MenuItem onClick={() => runCommand("Group")}>Group</MenuItem><MenuItem onClick={() => runCommand("Ungroup")}>Ungroup</MenuItem><MenuItem onClick={() => runCommand("Lock")}>Lock</MenuItem></Menu><Menu label="Extras"><MenuItem onClick={() => runCommand("Generate with AI")}>Generate with AI</MenuItem><MenuItem onClick={() => runCommand("AI edit")}>AI edit</MenuItem><MenuItem onClick={() => runCommand("Validate diagram")}>Validate diagram</MenuItem><MenuItem onClick={() => runCommand("Versions")}>Versions</MenuItem></Menu><Menu label="Help"><MenuItem onClick={() => runCommand("Keyboard shortcuts")}>Keyboard shortcuts</MenuItem></Menu></div>
    </header>
    {tab === "history" ? <HistoryGallery sessionId={sessionId} onOpen={openHistory} /> : <><div className="studio-toolbar"><div className="studio-group"><ToolbarButton label="Undo" onClick={undo} disabled={!history.length}><Undo2 /></ToolbarButton><ToolbarButton label="Redo" onClick={redo} disabled={!future.length}><Redo2 /></ToolbarButton></div><div className="studio-group"><ToolbarButton label="Delete" onClick={() => selectedId && setNodes(nodes.filter((node) => node.id !== selectedId))} disabled={!selectedId}><Trash2 /></ToolbarButton><ToolbarButton label="Duplicate" onClick={() => { const selected = nodes.find((node) => node.id === selectedId); if (selected) addNode({ label: selected.data.label, type: selected.data.kind, preview: "rect" }); }} disabled={!selectedId}><Copy /></ToolbarButton></div><div className="studio-group"><ToolbarButton label="Zoom out" onClick={() => flow.zoomOut()}><ZoomOut /></ToolbarButton><span className="studio-zoom">100%</span><ToolbarButton label="Zoom in" onClick={() => flow.zoomIn()}><ZoomIn /></ToolbarButton></div><ToolbarButton label="Fit view" onClick={() => flow.fitView()}><Maximize2 /></ToolbarButton><button onClick={() => { setChatOpen((value) => !value); onToggleChat?.(); }} className="ml-auto studio-action">{chatOpen ? "Collapse chat" : "Open chat"}</button></div>
    <div className="studio-body"><aside className={`studio-palette ${paletteOpen ? "open" : "closed"}`}><div className="studio-search"><Search className="h-4 w-4" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search shapes" />{search && <button aria-label="Clear shape search" onClick={() => setSearch("")}><X className="h-3.5 w-3.5" /></button>}</div>{filteredGroups.map((group) => <Section key={group.label} title={group.label}><div className="studio-shape-grid">{group.items.map((shape, index) => <button key={`${shape.label}-${index}`} title={shape.label} draggable onDragStart={(event) => event.dataTransfer.setData("application/x-sykra-shape", JSON.stringify(shape))} onClick={() => addNode(shape)} className="studio-shape-tile"><ShapePreview shape={shape.preview} /><span className="sr-only">{shape.label}</span></button>)}</div></Section>)}{filteredGroups.length === 0 && <p className="p-3 text-xs text-ink-soft">No shapes match</p>}</aside><main className="studio-canvas" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const raw = event.dataTransfer.getData("application/x-sykra-shape"); if (!raw) return; const shape = JSON.parse(raw) as Shape; const bounds = event.currentTarget.getBoundingClientRect(); addNode(shape, flow.screenToFlowPosition({ x: event.clientX - bounds.left, y: event.clientY - bounds.top })); }}><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} colorMode={theme} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange} onConnect={(connection: Connection) => { const next = addEdge({ ...connection, type: "smoothstep" }, edges); setEdges(next); commit(nodes, next); }} onNodeClick={(_, node) => { setSelectedId(node.id); setFormatOpen(true); }} fitView><Background gap={20} size={1} /><Controls position="bottom-left" /></ReactFlow><span className="react-flow-attribution">React Flow</span></main><aside className={`studio-format ${formatOpen && selectedId ? "open" : ""}`}>{formatOpen && selectedId && <div className="p-3"><div className="flex items-center justify-between"><span className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Format</span><button aria-label="Close format panel" onClick={() => setFormatOpen(false)}><X className="h-4 w-4" /></button></div><p className="mt-4 text-sm text-ink">{nodes.find((node) => node.id === selectedId)?.data.label}</p><p className="mt-1 text-xs text-ink-soft">Style and text controls for the selected shape.</p></div>}</aside></div></>}
    <footer className="studio-footer"><div className="relative flex items-center gap-1"><button onDoubleClick={() => setRenameOpen(true)} onClick={() => setPageMenuOpen((value) => !value)} className="studio-page-tab">{page.name} <ChevronDown className="h-3 w-3" /></button>{pageMenuOpen && <div className="absolute bottom-full left-0 z-30 mb-1 w-36 rounded border border-line bg-paper p-1 shadow-xl"><MenuItem onClick={() => { setPageMenuOpen(false); setRenameOpen(true); }}>Rename</MenuItem><MenuItem onClick={() => { const copy = { ...page, id: crypto.randomUUID(), name: `${page.name} copy` }; const next = validateDiagramDocument({ ...document, pages: [...document.pages, copy], activePageId: copy.id }); setDocument(next); setNodes(toFlowNodes(copy.nodes)); setEdges(copy.edges); setPageMenuOpen(false); }}>Duplicate</MenuItem><MenuItem onClick={() => { if (document.pages.length > 1) { const remaining = document.pages.filter((item) => item.id !== page.id); setDocument(validateDiagramDocument({ ...document, pages: remaining, activePageId: remaining[0].id })); setNodes(toFlowNodes(remaining[0].nodes)); setEdges(remaining[0].edges); } setPageMenuOpen(false); }}>Delete</MenuItem></div>}<button aria-label="Add page" onClick={() => { const nextPage = { id: crypto.randomUUID(), name: `Page ${document.pages.length + 1}`, diagramType: page.diagramType, nodes: [], edges: [] }; const next = validateDiagramDocument({ ...document, pages: [...document.pages, nextPage], activePageId: nextPage.id }); setDocument(next); setNodes([]); setEdges([]); }} className="studio-tool"><Plus className="h-4 w-4" /></button></div><span className="ml-auto text-xs text-ink-soft">{issues.length} {issues.length === 1 ? "issue" : "issues"}</span></footer>
    {toast && <button onClick={() => setToast("")} className="studio-toast">{toast}</button>}<PromptDialog open={renameOpen} title="Rename diagram" label="Diagram name" initialValue={document.title} onCancel={() => setRenameOpen(false)} onSubmit={(name) => { setDocument({ ...document, title: name }); setRenameOpen(false); setSaveState("saving"); }} /><ConfirmDialog open={deleteOpen} title="Delete diagram?" body="This removes the current diagram." onCancel={() => setDeleteOpen(false)} onConfirm={async () => { newDiagram(); setDeleteOpen(false); }} />
  </div>;
}

function toFlowNodes(nodes: DiagramNode[]): EditorNode[] { return nodes.map((node) => ({ id: node.id, type: "studio", position: node.position, data: { label: node.label, kind: node.type, visual: (node.data?.visual as Shape["preview"] | undefined) ?? visualForType(node.type) } })); }
function visualForType(type: DiagramNode["type"]): Shape["preview"] {
  if (type === "decision") return "diamond";
  if (type === "database" || type === "store") return "cylinder";
  if (type === "actor") return "actor";
  if (type === "data") return "data";
  if (type === "start" || type === "use-case") return "ellipse";
  return "round";
}
export function DiagramStudio(props: { sessionId?: string; initialDocument?: DiagramDocument; onChange?: (document: DiagramDocument) => void; onToggleChat?: () => void; chatOpen?: boolean }) { return <ReactFlowProvider><DiagramStudioInner {...props} /></ReactFlowProvider>; }