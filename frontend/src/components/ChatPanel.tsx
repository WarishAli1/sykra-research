"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Paperclip, Loader2, Sparkles, ChevronDown, Square, Network } from "lucide-react";
import { api, ApiError, ApiAbortError } from "@/lib/api";
import type { ChatTurn, Paper, ResponseMode, StreamEvent } from "@/lib/types";
import { ChatMessage } from "./ChatMessage";

const MODE_LABEL: Record<ResponseMode, string> = { normal: "Normal", researched: "Researched" };
const MODE_HINT: Record<ResponseMode, string> = { normal: "Quick, concise answers.", researched: "Full structured report with inline citations and references." };

export function ChatPanel({ onUpload, uploadedFilename, turns, setTurns, sessionId, onNewPapers, onOpenGraph }: {
  onUpload: (file: File) => Promise<void>; uploadedFilename: string | null; turns: ChatTurn[]; setTurns: React.Dispatch<React.SetStateAction<ChatTurn[]>>;
  sessionId: string; onNewPapers: (papers: Paper[]) => void; onOpenGraph: () => void;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadMode, setUploadMode] = useState<"none" | "blend" | "grounded_only">("none");
  const [responseMode, setResponseMode] = useState<ResponseMode>("normal");
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modeMenuRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestIdRef = useRef<string | null>(null);
  const turnsRef = useRef<ChatTurn[]>(turns);

  useEffect(() => { turnsRef.current = turns; }, [turns]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [turns, loading]);
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);
  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (modeMenuRef.current && !modeMenuRef.current.contains(e.target as Node)) setModeMenuOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const hasConversation = turns.length > 0;

  function appendAssistantTurn(turn: ChatTurn) { setTurns((t) => [...t, turn]); }
  function updateTurn(id: string, patch: Partial<ChatTurn> | ((prev: ChatTurn) => Partial<ChatTurn>)) {
    setTurns((prev) => prev.map((turn) => turn.id !== id ? turn : { ...turn, ...(typeof patch === "function" ? patch(turn) : patch) }));
  }

  function applyStreamEvent(turnId: string, event: StreamEvent, opts: { isChat: boolean }) {
    switch (event.type) {
      case "progress": updateTurn(turnId, { statusLabel: event.label }); break;
      case "token": updateTurn(turnId, (prev) => ({ text: prev.text + event.text, statusLabel: undefined })); break;
      case "result": {
        if (opts.isChat) {
          const res = event.payload as import("@/lib/types").ChatResponse;
          onNewPapers(res.papers ?? []);
          updateTurn(turnId, { papers: res.papers, citations: res.citations, coverageGaps: res.coverage_gaps, domainCaveat: res.domain_caveat, papersBelowThreshold: res.papers_below_threshold, references: res.references, responseMode: res.response_mode, streaming: false, statusLabel: undefined });
        }
        break;
      }
      case "cancelled": updateTurn(turnId, { streaming: false, stopped: true, statusLabel: undefined }); break;
      case "error": updateTurn(turnId, { streaming: false, statusLabel: undefined }); setError(event.message); break;
    }
  }

  async function runChatTurn(query: string, mode: ResponseMode, mode_: typeof uploadMode, history: {role: "user" | "assistant", content: string}[]) {
    const controller = new AbortController();
    abortRef.current = controller;

    const requestId = crypto.randomUUID();
    activeRequestIdRef.current = requestId;
    const turnId = crypto.randomUUID();

    appendAssistantTurn({
      role: "assistant", id: turnId, text: "", kind: "chat", sourceQuery: query, sourceUploadMode: mode_,
      responseMode: mode, streaming: true, requestId, statusLabel: "Starting...",
    });

    if (mode_ === "grounded_only") {
      const res = await api.chat(
        { query, session_id: sessionId, upload_mode: mode_, include_uploaded: true, response_mode: mode, conversation_history: history },
        controller.signal
      );
      onNewPapers(res.papers ?? []);
      updateTurn(turnId, { text: res.answer, papers: res.papers, citations: res.citations, coverageGaps: res.coverage_gaps, domainCaveat: res.domain_caveat, papersBelowThreshold: res.papers_below_threshold, references: res.references, responseMode: res.response_mode, streaming: false, statusLabel: undefined });
      return;
    }

    await api.chatStream(
      { query, session_id: sessionId, upload_mode: mode_, include_uploaded: mode_ !== "none", response_mode: mode, request_id: requestId, conversation_history: history },
      (event) => applyStreamEvent(turnId, event, { isChat: true }),
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
      await runChatTurn(query, responseMode, uploadMode, history);
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

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await onUpload(file);
      setUploadMode("grounded_only");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
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
        <div className="flex items-center gap-3">
          {uploadedFilename && (
            <div className="flex items-center gap-1.5 text-[11px]">
              <Paperclip className="h-3 w-3 text-ink-soft shrink-0" />
              <span className="text-ink-soft truncate max-w-[100px]">{uploadedFilename}</span>
              <select value={uploadMode} onChange={(e) => setUploadMode(e.target.value as "none" | "blend" | "grounded_only")} className="bg-paper-dim text-ink rounded px-1.5 py-0.5 border border-line text-[10px]">
                <option value="blend">Blend (Online + PDF)</option>
                <option value="grounded_only">PDF Only</option>
                <option value="none">Online Only</option>
              </select>
            </div>
          )}
          <button onClick={onOpenGraph} className="flex items-center gap-1.5 rounded-full bg-paper-dim px-3 py-1 text-[11px] font-medium text-ink-soft transition-colors hover:bg-paper hover:text-indigo">
            <Network className="h-3 w-3" /> Graph
          </button>
        </div>
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
          <ChatMessage key={t.id} turn={t} sessionId={sessionId} onRegenerate={async () => {
            if (loading) return;
            setError(null);
            setLoading(true);
            try {
              const controller = new AbortController();
              abortRef.current = controller;
              const mode = t.responseMode ?? "normal";
              const res = await api.chatRegenerate({
                session_id: sessionId, query: t.sourceQuery ?? "", response_mode: mode, is_followup: false,
                upload_mode: t.sourceUploadMode ?? "none", include_uploaded: (t.sourceUploadMode ?? "none") !== "none",
              }, controller.signal);
              setTurns((prev) => prev.map((turn) => turn.id === t.id ? { ...turn, text: res.answer, citations: res.citations, references: res.references, responseMode: res.response_mode, stopped: false } : turn));
            } catch (e) {
              if (!(e instanceof ApiAbortError)) setError(e instanceof ApiError ? e.message : "Could not regenerate this answer.");
            } finally {
              setLoading(false);
              abortRef.current = null;
            }
          }} />
        ))}
        {error && <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger animate-fade-up">{error}</div>}
      </div>

      <div className="border-t border-line p-3">
        <div className="flex items-end gap-2 rounded-xl border border-line bg-paper-dim/70 px-2.5 py-2 shadow-inner shadow-black/5 focus-within:border-indigo/50">
          <button onClick={() => fileInputRef.current?.click()} disabled={uploading} aria-label="Attach PDF" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-indigo disabled:opacity-50">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
          </button>
          <input ref={fileInputRef} type="file" accept="application/pdf" className="hidden" onChange={handleFileChange} />
          <textarea ref={textareaRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }} rows={1} placeholder="Ask AI about papers, or upload a PDF" className="max-h-40 min-h-[22px] flex-1 resize-none overflow-y-auto bg-transparent text-[13px] leading-relaxed text-ink placeholder:text-ink-soft/60 focus:outline-none py-1" />

          <div className="relative shrink-0" ref={modeMenuRef}>
            <button onClick={() => setModeMenuOpen((o) => !o)} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-medium text-ink-soft hover:text-ink hover:bg-paper/60 transition-colors" aria-haspopup="listbox" aria-expanded={modeMenuOpen}>
              {MODE_LABEL[responseMode]} <ChevronDown className="h-3 w-3" />
            </button>
            {modeMenuOpen && (
              <div role="listbox" className="absolute right-0 bottom-full z-20 mb-1.5 w-56 rounded-lg border border-line bg-paper shadow-lg shadow-black/10 py-1">
                {(Object.keys(MODE_LABEL) as ResponseMode[]).map((mode) => (
                  <button key={mode} role="option" aria-selected={responseMode === mode} onClick={() => { setResponseMode(mode); setModeMenuOpen(false); }} className={`flex w-full flex-col items-start gap-0.5 px-3 py-1.5 text-left text-[11.5px] hover:bg-paper-dim ${responseMode === mode ? "text-indigo font-medium" : "text-ink"}`}>
                    <span>{MODE_LABEL[mode]}</span>
                    <span className="text-[10.5px] font-normal text-ink-soft">{MODE_HINT[mode]}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {loading ? (
            <button onClick={handlePause} aria-label="Pause generation" title="Stop generating this response" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-danger text-white transition-opacity hover:bg-danger/90">
              <Square className="h-3 w-3 fill-current" />
            </button>
          ) : (
            <button onClick={handleSend} disabled={!input.trim()} aria-label="Send message" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gold text-white transition-opacity hover:bg-gold/90 disabled:opacity-30">
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
