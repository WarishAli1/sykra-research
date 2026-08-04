"use client";
import { useCallback, useRef, useState, useMemo } from "react";
import {
  ChevronsLeft,
  ChevronsRight,
  Library,
  Network,
  ArrowLeft,
  PanelLeftOpen,
  Plus,
} from "lucide-react";
import Image from "next/image";
import { RightRail } from "./RightRail";
import { ChatPanel } from "./ChatPanel";
import { GraphView } from "./GraphView";
import { api, ApiError } from "@/lib/api";
import type { ChatTurn, Paper, EvidenceMode } from "@/lib/types";
import dynamic from "next/dynamic";

const PdfViewer = dynamic(() => import("./PdfViewer").then((m) => m.PdfViewer), {
  ssr: false,
});
import { PdfViewerBoundary } from "./PdfViewerBoundary";

const isHttpUrl = (v?: string | null) =>
  !!v && /^https?:\/\//i.test(v.replace(/^user_upload:\/\//i, ""));

function mergePapers(existing: Paper[], incoming: Paper[]): Paper[] {
  const byTitle = new Map(existing.map((p) => [p.title, p]));
  for (const p of incoming) {
    const prev = byTitle.get(p.title);
    if (!prev) {
      byTitle.set(p.title, p);
      continue;
    }
    byTitle.set(p.title, {
      ...prev,
      ...p,
      file_url: isHttpUrl(p.file_url) ? p.file_url : prev.file_url,
      link: p.link || prev.link,
      is_uploaded: prev.is_uploaded || p.is_uploaded,
      source: p.source ?? prev.source,
    });
  }
  return Array.from(byTitle.values());
}

const RAIL_WIDTH = 340;
const STRIP_WIDTH = 44;
const SIDEBAR_WIDTH = 224;
const SIDEBAR_COLLAPSED_WIDTH = 48;
const PDF_WIDTH_DEFAULT = 50;
const PDF_WIDTH_MIN = 30;
const PDF_WIDTH_MAX = 70;

export function AppShell() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [railOpen, setRailOpen] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [tab, setTab] = useState<"library" | "explore">("library");
  const [showGraphView, setShowGraphView] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const [pdfViewerUrl, setPdfViewerUrl] = useState<string | null>(null);
  const [pdfWidthPct, setPdfWidthPct] = useState(PDF_WIDTH_DEFAULT);
  const [draggingPdf, setDraggingPdf] = useState(false);

  const [uploadState, setUploadState] = useState({
    status: "idle" as "idle" | "uploading" | "processing" | "done" | "error",
    filename: "",
    progress: "",
    stage: "",
    fileUrl: "",
  });
  const [hasUpload, setHasUpload] = useState(false);
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>("literature");

  const lastAssistantTurnId =
    [...turns].reverse().find((t) => t.role === "assistant" && t.turnId)?.turnId ?? null;

  const handleNewPapers = useCallback((incoming: Paper[]) => {
    if (!incoming.length) return;
    setPapers((prev) => mergePapers(prev, incoming));
  }, []);

  const handleOpenGraph = () => {
    setShowGraphView(true);
    setRailOpen(true);
    setTab("explore");
  };
  const handleBackToChat = () => setShowGraphView(false);

  const handleOpenPdf = (url: string) => setPdfViewerUrl(url);
  const handleClosePdf = () => setPdfViewerUrl(null);
  const startPdfResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const container = containerRef.current;
    if (!container) return;
    setDraggingPdf(true);
    const onMove = (ev: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) return;
      const fromRight = rect.right - ev.clientX;
      const pct = Math.min(
        PDF_WIDTH_MAX,
        Math.max(PDF_WIDTH_MIN, (fromRight / rect.width) * 100)
      );
      setPdfWidthPct(pct);
    };
    const onUp = () => {
      setDraggingPdf(false);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, []);

  const handleNewChat = () => {
    setTurns([]);
    setPapers([]);
    setUploadedFilename(null);
    setUploadState({ status: "idle", filename: "", progress: "", stage: "", fileUrl: "" });
    setHasUpload(false);
    setEvidenceMode("literature");
    setSessionId(crypto.randomUUID());
    setShowGraphView(false);
  };
  const messagePaperLinks = useMemo(() => {
    const t = [...turns].reverse().find((x) => x.role === "assistant" && x.turnId === lastAssistantTurnId);
    return t?.papers?.map((p) => p.link).filter(Boolean) ?? [];
  }, [turns, lastAssistantTurnId]);
  const handleDeletePaper = async (paper: Paper) => {
    setPapers((prev) => prev.filter((p) => p.link !== paper.link));
    const wasActiveUpload =
      paper.link === uploadState.fileUrl ||
      (uploadState.filename && paper.title === uploadState.filename);
    if (wasActiveUpload) {
      setUploadState({ status: "idle", filename: "", progress: "", stage: "", fileUrl: "" });
      setHasUpload(false);
      setEvidenceMode("literature");
      setUploadedFilename(null);
    }
    try {
      await api.deleteUploadedPdf(sessionId, paper.link);
    } catch (e) {
      console.error("Failed to delete paper:", e);
      setPapers((prev) => (prev.some((p) => p.link === paper.link) ? prev : [...prev, paper]));
      if (wasActiveUpload) {
        setUploadedFilename(paper.title);
        setHasUpload(true);
        setEvidenceMode("uploaded");
        setUploadState({
          status: "done",
          filename: paper.title,
          progress: "Ready",
          stage: "",
          fileUrl: paper.link,
        });
      }
    }
  };

  const handleDownloadConversationPdf = useCallback(async () => {
    const assistantTurns = turns.filter((t) => t.role === "assistant");
    if (!assistantTurns.length) return;
    const combinedAnswer = assistantTurns
      .map((t, i) => `## Turn ${i + 1}\n\n${t.text}`)
      .join("\n\n---\n\n");
    const combinedReferences = Array.from(
      new Map(assistantTurns.flatMap((t) => t.references ?? []).map((r) => [r.id, r])).values()
    );
    try {
      const blob = await api.exportPdf({
        session_id: sessionId,
        format: "standard",
        answer: combinedAnswer,
        references: combinedReferences,
        title: "Research Assistant — Conversation",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "conversation.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e instanceof ApiError ? e.message : "Could not generate conversation PDF.");
    }
  }, [turns, sessionId]);

  function handleUploadComplete(data: { filename: string; fileUrl: string; link: string }) {
    setUploadedFilename(data.filename);
    handleNewPapers([
      {
        title: data.filename,
        authors: [],
        summary: "",
        link: data.link,
        published: null,
        relevance_score: null,
        source: "user_upload",
        is_uploaded: true,
        file_url: data.fileUrl,
      },
    ]);
  }

  return (
    <div className="flex h-screen bg-paper overflow-hidden">
      <div
        className="relative z-30 shrink-0 h-full overflow-hidden transition-[width] duration-200 ease-out border-r border-line bg-paper-dim"
        style={{ width: sidebarOpen ? SIDEBAR_WIDTH : SIDEBAR_COLLAPSED_WIDTH }}
      >
        {sidebarOpen ? (
          <div className="flex h-full flex-col" style={{ width: SIDEBAR_WIDTH }}>
            <div className="flex items-center gap-2.5 px-4 py-4 shrink-0">
              <Image
                src="/sykra-icon.png"
                alt="Sykra Research"
                width={789}
                height={146}
                className="w-[150px] h-auto shrink-0 -mt-3"
                priority
              />
              <button
                onClick={() => setSidebarOpen(false)}
                aria-label="Collapse sidebar"
                className="ml-auto flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-soft hover:bg-paper hover:text-ink transition-colors"
              >
                <ChevronsLeft className="h-3.5 w-3.5" />
              </button>
            </div>

            <div className="px-3">
              <button
                onClick={handleNewChat}
                className="flex w-full items-center gap-2 rounded-lg bg-gold-tint border border-gold/40 px-3 py-2 text-[12.5px] font-medium text-ink hover:bg-gold-tint/70 hover:border-gold/60 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                New Chat
              </button>
            </div>

            <div className="mt-5 px-3">
              <p className="px-1.5 pb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft/70">
                Workspace
              </p>

              <button
                onClick={() => {
                  setShowGraphView(false);
                  setTab("library");
                  setRailOpen(true);
                }}
                className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
                  !showGraphView && tab === "library" && railOpen
                    ? "bg-gold-tint text-ink font-medium"
                    : "text-ink-soft hover:bg-paper hover:text-ink"
                }`}
              >
                <Library className="h-3.5 w-3.5 shrink-0" />
                Library
                {papers.length > 0 && (
                  <span className="ml-auto rounded-full bg-paper px-1.5 py-0 text-[10px] text-ink-soft">
                    {papers.length}
                  </span>
                )}
              </button>

              <button
                onClick={handleOpenGraph}
                className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
                  showGraphView
                    ? "bg-gold-tint text-ink font-medium"
                    : "text-ink-soft hover:bg-paper hover:text-ink"
                }`}
              >
                <Network className="h-3.5 w-3.5 shrink-0" />
                Explore Graph
              </button>
            </div>

            <div className="mt-auto px-4 py-3 text-[10.5px] text-ink-soft/50 shrink-0">
              AI Research Assistant
            </div>
          </div>
        ) : (
          <div
            className="flex h-full flex-col items-center gap-2 py-3"
            style={{ width: SIDEBAR_COLLAPSED_WIDTH }}
          >
            <button
              onClick={() => setSidebarOpen(true)}
              aria-label="Expand sidebar"
              title="Expand sidebar"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink transition-colors"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>

            <div className="my-1 h-px w-6 bg-line" aria-hidden="true" />

            {/* New Chat */}
            <button
              onClick={handleNewChat}
              aria-label="New chat"
              title="New chat"
              className="relative flex h-9 w-9 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink transition-colors"
            >
              <Plus className="h-4 w-4" />
              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </button>

            {/* Library */}
            <button
              onClick={() => {
                setShowGraphView(false);
                setTab("library");
                setRailOpen(true);
              }}
              aria-label="Open library"
              title="Library"
              className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
                !showGraphView && tab === "library" && railOpen
                  ? "bg-gold-tint text-ink"
                  : "text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {!showGraphView && tab === "library" && railOpen && (
                <span
                  className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-gold"
                  aria-hidden="true"
                />
              )}

              <Library className="h-4 w-4" />

              {papers.length > 0 && (
                <span
                  className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-gold"
                  aria-hidden="true"
                />
              )}

              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </button>

            {/* Explore Graph */}
            <button
              onClick={handleOpenGraph}
              aria-label="Open explore graph"
              title="Explore Graph"
              className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
                showGraphView
                  ? "bg-gold-tint text-ink"
                  : "text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {showGraphView && (
                <span
                  className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-gold"
                  aria-hidden="true"
                />
              )}

              <Network className="h-4 w-4" />

              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </button>
          </div>
        )}
      </div>

      <div ref={containerRef} className="flex flex-1 min-h-0 min-w-0">
        <main className="flex-1 min-w-0">
          {showGraphView ? (
            <div className="h-full flex flex-col">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <button
                  onClick={handleBackToChat}
                  className="flex items-center gap-2 text-[13px] text-ink-soft hover:text-ink"
                >
                  <ArrowLeft className="h-4 w-4" /> Back to Chat
                </button>
                <span className="font-serif text-[15px] font-semibold text-ink">Knowledge Graph</span>
                <span className="w-[90px]" />
              </div>
              <div className="flex-1 min-h-0">
                <GraphView sessionId={sessionId} activeTurnId={lastAssistantTurnId} messagePaperLinks={messagePaperLinks} />
              </div>
            </div>
          ) : (
            <ChatPanel
              uploadedFilename={uploadedFilename}
              onUploadComplete={handleUploadComplete}
              onNewPapers={handleNewPapers}
              onOpenPdf={handleOpenPdf}
              turns={turns}
              setTurns={setTurns}
              sessionId={sessionId}
              onOpenGraph={handleOpenGraph}
              onDeletePaper={async (link) => {
                const paper =
                  papers.find((p) => p.link === link) ??
                  papers.find((p) => uploadState.filename && p.title === uploadState.filename) ?? {
                    title: uploadState.filename,
                    authors: [],
                    summary: "",
                    link,
                  };
                await handleDeletePaper(paper as Paper);
              }}
              uploadState={uploadState}
              setUploadState={setUploadState}
              hasUpload={hasUpload}
              setHasUpload={setHasUpload}
              evidenceMode={evidenceMode}
              setEvidenceMode={setEvidenceMode}
            />
          )}
        </main>

        {!pdfViewerUrl && (
          <div
            className="relative shrink-0 h-full border-l border-line overflow-hidden transition-[width] duration-200 ease-out"
            style={{ width: railOpen ? RAIL_WIDTH : STRIP_WIDTH }}
          >
            {railOpen ? (
              <div className="h-full flex flex-col" style={{ width: RAIL_WIDTH }}>
                <div className="flex items-center justify-end px-2 py-1.5 border-b border-line shrink-0">
                  <button
                    onClick={() => setRailOpen(false)}
                    aria-label="Collapse panel"
                    className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-ink"
                  >
                    <ChevronsRight className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="flex-1 min-h-0">
                  <RightRail
                    papers={papers}
                    sessionId={sessionId}
                    tab={tab}
                    setTab={setTab}
                    onOpenPdf={handleOpenPdf}
                    onDeletePaper={handleDeletePaper}
                  />
                </div>
              </div>
            ) : (
              <div
                className="h-full flex flex-col items-center gap-1 py-2"
                style={{ width: STRIP_WIDTH }}
              >
                <button
                  onClick={() => setRailOpen(true)}
                  aria-label="Expand panel"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-ink mb-1"
                >
                  <ChevronsLeft className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => {
                    setTab("library");
                    setRailOpen(true);
                  }}
                  aria-label="Open library"
                  className="relative flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-ink"
                >
                  <Library className="h-4 w-4" />
                  {papers.length > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-gold" />
                  )}
                </button>
                <button
                  onClick={() => {
                    setTab("explore");
                    setRailOpen(true);
                  }}
                  aria-label="Open explore"
                  className="relative flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-ink"
                >
                  <Network className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        )}

        {pdfViewerUrl && (
          <>
            <div
              onMouseDown={startPdfResize}
              title="Drag to resize"
              className="group relative z-10 flex w-3 shrink-0 cursor-col-resize items-center justify-center select-none hover:bg-paper-dim/60 transition-colors"
            >
              <span
                className={`rounded-full transition-all duration-150 ${
                  draggingPdf
                    ? "h-20 w-1.5 bg-ink"
                    : "h-12 w-1.5 bg-line group-hover:h-16 group-hover:bg-ink-soft"
                }`}
              />
            </div>
            <div
              className="h-full min-w-0 overflow-hidden"
              style={{ width: `${pdfWidthPct}%`, flexShrink: 0 }}
            >
              <PdfViewerBoundary onClose={handleClosePdf}>
                <PdfViewer url={pdfViewerUrl} onClose={handleClosePdf} />
              </PdfViewerBoundary>
            </div>
          </>
        )}
      </div>

      {draggingPdf && (
        <div className="fixed inset-0 z-[60] cursor-col-resize" aria-hidden="true" />
      )}
    </div>
  );
}