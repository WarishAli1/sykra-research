"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Paperclip, Loader2, Sparkles, ChevronDown, Square, Network } from "lucide-react";
import { api, ApiError, ApiAbortError } from "@/lib/api";
import type { ChatTurn, Paper, ResponseMode, EvidenceMode, StreamEvent, UploadStreamEvent } from "@/lib/types";
import { ChatMessage } from "./ChatMessage";
import { UploadPreviewCard } from "./UploadPreviewCard";
import { Dropdown } from "@/components/Dropdown";

export function ChatPanel({ 
  onUploadComplete, 
  uploadedFilename,
  turns, 
  setTurns, 
  sessionId, 
  onNewPapers, 
  onOpenGraph,
  onOpenPdf,
  onDeletePaper,
  uploadState,
  setUploadState,
  hasUpload,
  setHasUpload,
  evidenceMode,
  setEvidenceMode,
}: { 
  onUploadComplete: (data: {
    filename: string;
    fileUrl: string;
    link: string;}) => void;
  uploadedFilename: string | null; 
  turns: ChatTurn[]; 
  setTurns: React.Dispatch<React.SetStateAction<ChatTurn[]>>;
  sessionId: string; 
  onNewPapers: (papers: Paper[]) => void; 
  onOpenGraph: () => void;
  onOpenPdf: (url: string) => void;
  onDeletePaper?: (link: string) => Promise<void>;
  uploadState: {
    status: "idle" | "uploading" | "processing" | "done" | "error";
    filename: string;
    progress: string;
    stage: string;
    fileUrl: string;
  };
  setUploadState: React.Dispatch<React.SetStateAction<{
    status: "idle" | "uploading" | "processing" | "done" | "error";
    filename: string;
    progress: string;
    stage: string;
    fileUrl: string;
  }>>;
  hasUpload: boolean;
  setHasUpload: React.Dispatch<React.SetStateAction<boolean>>;
  evidenceMode: EvidenceMode;
  setEvidenceMode: React.Dispatch<React.SetStateAction<EvidenceMode>>;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [responseMode, setResponseMode] = useState<ResponseMode>("normal");
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestIdRef = useRef<string | null>(null);
  const uploadAbortRef = useRef<AbortController | null>(null);
  const uploadRequestIdRef = useRef<string | null>(null);
  const turnsRef = useRef<ChatTurn[]>(turns);

  useEffect(() => { turnsRef.current = turns; }, [turns]);
  useEffect(() => { 
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); 
  }, [turns, loading]);
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  const hasConversation = turns.length > 0;

  function appendAssistantTurn(turn: ChatTurn) { setTurns((t) => [...t, turn]); }

  function updateTurn(id: string, patch: Partial<ChatTurn> | ((prev: ChatTurn) => Partial<ChatTurn>)) {
    setTurns((prev) => prev.map((turn) => 
      turn.id !== id ? turn : { ...turn, ...(typeof patch === "function" ? patch(turn) : patch) }
    ));
  }

  function applyStreamEvent(turnId: string, event: StreamEvent, opts: { isChat: boolean }) {
    switch (event.type) {
      case "progress": updateTurn(turnId, { statusLabel: event.label }); break;
      case "token": updateTurn(turnId, (prev) => ({ text: prev.text + event.text, statusLabel: undefined })); break;
      case "result": {
        if (opts.isChat) {
          const res = event.payload as import("@/lib/types").ChatResponse;
          onNewPapers(res.papers ?? []);
          updateTurn(turnId, { 
            papers: res.papers, 
            citations: res.citations, 
            coverageGaps: res.coverage_gaps, 
            domainCaveat: res.domain_caveat, 
            papersBelowThreshold: res.papers_below_threshold, 
            references: res.references, 
            responseMode: res.response_mode, 
            streaming: false, 
            statusLabel: undefined, 
            turnId: res.turn_id,
            chartUrl: res.chart_url ?? null,
            filename: res.filename ?? undefined
          });
        }
        break;
      }
      case "cancelled": updateTurn(turnId, { streaming: false, stopped: true, statusLabel: undefined }); break;
      case "error": updateTurn(turnId, { streaming: false, statusLabel: undefined }); setError(event.message); break;
    }
  }

  async function runChatTurn(
    query: string,
    mode: ResponseMode,
    evMode: EvidenceMode,
    history: { role: "user" | "assistant"; content: string }[]
  ) {
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = crypto.randomUUID();
    activeRequestIdRef.current = requestId;
    const assistantId = crypto.randomUUID();
    const kgTurnId = crypto.randomUUID();

    appendAssistantTurn({
      role: "assistant",
      id: assistantId,
      text: "",
      kind: "chat",
      sourceQuery: query,
      sourceEvidenceMode: evMode,
      responseMode: mode,
      streaming: true,
      requestId,
      statusLabel: "Starting...",
      turnId: kgTurnId,
    });

    await api.chatStream(
      {
        query,
        session_id: sessionId,
        turn_id: kgTurnId,
        evidence_mode: evMode,
        response_mode: mode,
        request_id: requestId,
        conversation_history: history,
      },
      (event) => applyStreamEvent(assistantId, event, { isChat: true }),
      controller.signal
    );
  }

  async function handleSend() {
    const query = input.trim();
    if (!query || loading) return;
    setError(null);
    setInput("");
    const userTurn: ChatTurn = { role: "user", id: crypto.randomUUID(), text: query };
    setTurns((t) => [...t, userTurn]);
    setLoading(true);
    const history = turns.map(t => ({ role: t.role as "user" | "assistant", content: t.text }));
    try {
      await runChatTurn(query, responseMode, evidenceMode, history);
    } catch (e) {
      if (e instanceof ApiAbortError) {
        const id = turnsRef.current[turnsRef.current.length - 1]?.id;
        if (id) updateTurn(id, { streaming: false, stopped: true, statusLabel: undefined });
      } else {
        const msg = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
        setError(msg);
        const id = turnsRef.current[turnsRef.current.length - 1]?.id;
        if (id) updateTurn(id, { streaming: false, statusLabel: undefined });
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
      activeRequestIdRef.current = null;
    }
  }

  function handlePause() {
    const requestId = activeRequestIdRef.current;
    if (requestId) api.cancelStream(requestId).catch(() => {});
    abortRef.current?.abort();
  }

  function handlePauseUpload() {
    // Cancelling an in-flight upload is destructive, not resumable — there's
    // no clean way to pick a half-parsed PDF back up mid-stream. Fire the
    // server-side cancel (so the backend stops wasted OCR/embedding/graph
    // work), then abort the client fetch. Abort tears the connection down
    // immediately, so a "cancelled" SSE event will never arrive to reset the
    // UI — that reset has to happen here, right away, not in the event
    // handler.
    const requestId = uploadRequestIdRef.current;
    if (requestId) api.cancelUploadStream(requestId).catch(() => {});
    uploadAbortRef.current?.abort();

    setUploadState({ status: "idle", filename: "", progress: "", stage: "", fileUrl: "" });
    setHasUpload(false);
    setEvidenceMode("literature");
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadState({
      status: "uploading",
      filename: file.name,
      progress: "Uploading file...",
      stage: "uploading",
      fileUrl: "",
  }); 
    setError(null);

    const requestId = crypto.randomUUID();
    uploadRequestIdRef.current = requestId;
    const controller = new AbortController();
    uploadAbortRef.current = controller;

    try {
      await api.uploadPdfStream(file, sessionId, (event) => {
        if (event.type === "cancelled") {
          setUploadState({ status: "idle", filename: "", progress: "", stage: "", fileUrl: "" });
          setHasUpload(false);
          setEvidenceMode("literature");
          return;
        }
        if (event.type === "progress") {
            setUploadState(prev => ({
                ...prev,
                status: "processing",
                progress: event.label,
                stage: event.stage ?? "",
            }));
        }
        if (event.type === "result") {
          setUploadState(prev => ({
              ...prev,
              status: "done",
              progress: "Ready",
              fileUrl: event.payload.file_url,
          }));

          setHasUpload(true);
          setEvidenceMode("uploaded");

          onUploadComplete({
            filename: event.payload.filename,
            fileUrl: event.payload.file_url,
            link: event.payload.link,
          });
        }
        if (event.type === "error") {
          setError(event.message);
          setUploadState(prev => ({
            ...prev,
            status: "error",
          }));
        }
      }, controller.signal, requestId);
    } catch (err) {
      if (!(err instanceof ApiAbortError)) {
        setError(err instanceof ApiError ? err.message : "Upload failed.");
        setUploadState(prev => ({
            ...prev,
            status: "error",
        }));
      }
    } finally {
      uploadRequestIdRef.current = null;
      uploadAbortRef.current = null;
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line bg-paper/70 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-indigo" />
          <span className="font-serif text-[15px] font-semibold text-ink">AI Chat</span>
        </div>
        <button 
          onClick={onOpenGraph} 
          className="flex items-center gap-1.5 rounded-full bg-paper-dim px-3 py-1 text-[11px] font-medium text-ink-soft transition-colors hover:bg-paper hover:text-indigo"
        >
          <Network className="h-3 w-3" /> Graph
        </button>
      </div>
      
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {!hasConversation && (
          <div className="flex h-full flex-col items-center justify-center text-center px-6">
            <Sparkles className="h-6 w-6 text-indigo/40 mb-3" />
            <p className="font-serif text-[15px] text-ink mb-1">Ask about the research</p>
            <p className="text-[12.5px] text-ink-soft max-w-[220px]">
              Search papers, ask follow-ups, or upload a PDF to ground answers in it. You can ask about new or old topics anytime.
            </p>
          </div>
        )}
        {turns.map((t) => (
          <ChatMessage 
            key={t.id} 
            turn={t} 
            sessionId={sessionId} 
            onRegenerate={async () => {
              if (loading) return;
              setError(null);
              setLoading(true);
              try {
                const controller = new AbortController();
                abortRef.current = controller;
                const mode = t.responseMode ?? "normal";
                const res = await api.chatRegenerate({
                  session_id: sessionId,
                  turn_id: t.turnId,
                  query: t.sourceQuery ?? "",
                  response_mode: mode,
                  is_followup: false,
                  evidence_mode: t.sourceEvidenceMode ?? "literature",
                }, controller.signal);
                setTurns((prev) => prev.map((turn) => 
                  turn.id === t.id ? { 
                    ...turn, 
                    text: res.answer, 
                    citations: res.citations, 
                    references: res.references, 
                    responseMode: res.response_mode, 
                    stopped: false, 
                    turnId: res.turn_id,
                    chartUrl: res.chart_url ?? null,
                    filename: res.filename ?? undefined
                  } : turn
                ));
              } catch (e) {
                if (!(e instanceof ApiAbortError)) 
                  setError(e instanceof ApiError ? e.message : "Could not regenerate this answer.");
              } finally {
                setLoading(false);
                abortRef.current = null;
              }
            }} 
          />
        ))}
        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger animate-fade-up">
            {error}
          </div>
        )}
      </div>
      
      <div className="border-t border-line p-3">
        {uploadState.status !== "idle" && (
            <UploadPreviewCard
                filename={uploadState.filename}
                status={uploadState.status}
                progress={uploadState.progress}
                fileUrl={uploadState.fileUrl}
                onOpen={() => {
                    if (uploadState.fileUrl) {
                        onOpenPdf(uploadState.fileUrl);
                    }
                }}
                onCancel={() => handlePauseUpload()}
                onClose={() => {
                    if (uploadState.status === "done") {
                        const link = uploadState.fileUrl;
                        setUploadState({ status: "idle", filename: "", progress: "", stage: "", fileUrl: "" });
                        setHasUpload(false);
                        setEvidenceMode("literature");
                        onDeletePaper?.(link);
                    } else {
                        // handlePauseUpload already resets uploadState/hasUpload/
                        // evidenceMode — no need to duplicate it here.
                        handlePauseUpload();
                    }
                }}
            />
        )}
        
        <div className="flex items-end gap-2 rounded-xl border border-line bg-paper-dim/70 px-2.5 py-2 shadow-inner shadow-black/5 focus-within:border-indigo/50">
          <button 
            onClick={() => fileInputRef.current?.click()} 
            disabled={
                uploadState.status === "uploading" ||
                uploadState.status === "processing"
            }
            aria-label="Attach PDF" 
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-indigo disabled:opacity-50"
          >
            {uploadState.status === "uploading" || uploadState.status === "processing" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
          </button>
          <input 
            ref={fileInputRef} 
            type="file" 
            accept="application/pdf" 
            className="hidden" 
            onChange={handleFileChange} 
          />
          <textarea 
            ref={textareaRef} 
            value={input} 
            onChange={(e) => setInput(e.target.value)} 
            onKeyDown={(e) => { 
              if (e.key === "Enter" && !e.shiftKey) { 
                e.preventDefault(); 
                handleSend(); 
              } 
            }} 
            rows={1} 
            placeholder="Ask AI about papers, or upload a PDF" 
            className="max-h-40 min-h-[22px] flex-1 resize-none overflow-y-auto bg-transparent text-[13px] leading-relaxed text-ink placeholder:text-ink-soft/60 focus:outline-none py-1" 
          />

          {hasUpload && (
            <Dropdown
              value={evidenceMode}
              onChange={setEvidenceMode}
              items={[
                {
                  value: "uploaded",
                  label: "Uploaded document",
                  hint: "Answer using only the uploaded document.",
                },
                {
                  value: "blended",
                  label: "Blend",
                  hint: "Combine the uploaded document with external literature.",
                },
              ]}
            />
          )}
          
          <Dropdown
            value={responseMode}
            onChange={setResponseMode}
            items={[
              {
                value: "normal",
                label: "Normal",
                hint: "Quick, concise answers.",
              },
              {
                value: "researched",
                label: "Researched",
                hint: "Full structured report with inline citations and references.",
              },
            ]}
          />
          
          {loading ? (
            <button 
              onClick={handlePause} 
              aria-label="Pause generation" 
              title="Stop generating this response" 
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-danger text-white transition-opacity hover:bg-danger/90"
            >
              <Square className="h-3 w-3 fill-current" />
            </button>
          ) : (
            <button 
              onClick={handleSend} 
              disabled={!input.trim()} 
              aria-label="Send message" 
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gold text-white transition-opacity hover:bg-gold/90 disabled:opacity-30"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}