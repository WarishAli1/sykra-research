"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronsLeft, ChevronsRight, FlaskConical, Library, Network } from "lucide-react";
import { RightRail } from "./RightRail";
import { ChatPanel } from "./ChatPanel";
import { api } from "@/lib/api";
import type { ChatTurn, Paper } from "@/lib/types";

function mergePapers(existing: Paper[], incoming: Paper[]): Paper[] {
  const byTitle = new Map(existing.map((p) => [p.title, p]));
  for (const p of incoming) byTitle.set(p.title, p);
  return Array.from(byTitle.values());
}

const RAIL_MIN = 280;
const RAIL_MAX = 560;
const RAIL_DEFAULT = 340;
const STRIP_WIDTH = 44;

export function AppShell() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [railOpen, setRailOpen] = useState(true);
  const [railWidth, setRailWidth] = useState(RAIL_DEFAULT);
  const [tab, setTab] = useState<"library" | "explore">("library");
  const draggingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleNewPapers = useCallback((incoming: Paper[]) => {
    if (!incoming.length) return;
    setPapers((prev) => mergePapers(prev, incoming));
  }, []);

  const handleOpenGraph = () => {
    setRailOpen(true);
    setTab("explore");
  };

  const handleNewChat = () => {
    setTurns([]);
    setPapers([]);
    setUploadedFilename(null);
    setSessionId(crypto.randomUUID());
  };

  async function handleUpload(file: File) {
    const res = await api.uploadPdf(file, sessionId);
    setUploadedFilename(res.filename);

    handleNewPapers([
      {
        title: res.filename,
        authors: [],
        summary: "",
        link: res.link,
        published: null,
        relevance_score: null,
        source: "user_upload",
        is_uploaded: true,
        file_url: res.file_url,
      },
    ]);
  }

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = rect.right - e.clientX;
      setRailWidth(Math.min(RAIL_MAX, Math.max(RAIL_MIN, next)));
    }
    function onUp() {
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div className="flex h-screen flex-col bg-paper">
      <header className="flex items-center gap-2 border-b border-line px-4 py-2.5 shrink-0">
        <FlaskConical className="h-4 w-4 text-indigo" />
        <span className="font-serif text-[14px] font-semibold text-ink">
          AI Research Assistant
        </span>
        <button
          onClick={handleNewChat}
          className="ml-auto text-[11px] px-2 py-1 rounded bg-paper-dim text-ink-soft hover:text-indigo hover:bg-paper"
        >
          New Chat
        </button>
      </header>

      <div ref={containerRef} className="flex flex-1 min-h-0">
        <main className="flex-1 min-w-0">
          <ChatPanel
            uploadedFilename={uploadedFilename}
            onUpload={handleUpload}
            onNewPapers={handleNewPapers}
            turns={turns}
            setTurns={setTurns}
            sessionId={sessionId}
            onOpenGraph={handleOpenGraph}
          />
        </main>

        <div
          className="relative shrink-0 h-full border-l border-line"
          style={{ width: railOpen ? railWidth : STRIP_WIDTH }}
        >
          {railOpen && (
            <div
              onMouseDown={startDrag}
              className="absolute left-0 top-0 z-10 h-full w-1.5 -translate-x-1/2 cursor-col-resize group"
            >
              <div className="mx-auto h-full w-px bg-line group-hover:bg-indigo/40 group-hover:w-0.5 transition-colors" />
            </div>
          )}

          {railOpen ? (
            <div className="h-full flex flex-col">
              <div className="flex items-center justify-end px-2 py-1.5 border-b border-line">
                <button
                  onClick={() => setRailOpen(false)}
                  aria-label="Collapse panel"
                  className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
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
                />
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center gap-1 py-2">
              <button
                onClick={() => setRailOpen(true)}
                aria-label="Expand panel"
                className="flex h-7 w-7 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo mb-1"
              >
                <ChevronsLeft className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => {
                  setTab("library");
                  setRailOpen(true);
                }}
                aria-label="Open library"
                className="relative flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
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
                className="relative flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
              >
                <Network className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
