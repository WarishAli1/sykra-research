"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Paperclip, Loader2, Sparkles, Network } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ChatTurn, Paper } from "@/lib/types";
import { ChatMessage } from "./ChatMessage";

export function ChatPanel({
  onUpload,
  uploadedFilename,
  turns,
  setTurns,
  sessionId,
  onNewPapers,
  onOpenGraph,
}: {
  onUpload: (file: File) => Promise<void>;
  uploadedFilename: string | null;
  turns: ChatTurn[];
  setTurns: React.Dispatch<React.SetStateAction<ChatTurn[]>>;
  sessionId: string;
  onNewPapers: (papers: Paper[]) => void;
  onOpenGraph: () => void;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadMode, setUploadMode] = useState<"none" | "blend" | "grounded_only">("none");
  const [researchMode, setResearchMode] = useState(false);
  const [uploading, setUploading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  async function handleSend() {
    const query = input.trim();
    if (!query || loading) return;
    setError(null);
    setInput("");

    const userTurn: ChatTurn = { role: "user", id: crypto.randomUUID(), text: query };
    setTurns((t) => [...t, userTurn]);
    setLoading(true);

    try {
      if (!hasConversation) {
        if (researchMode) {
          onOpenGraph();
          const res = await api.research({ query, session_id: sessionId });

          let papers: Paper[] = [];
          try {
            const sessionPapers = await api.getSessionPapers(res.session_id);
            papers = sessionPapers.papers
              .filter((p) => p.title && p.link)
              .map((p) => ({
                title: p.title as string,
                authors: [],
                summary: (p.text_excerpt as string) ?? "",
                link: p.link as string,
                published: (p.published as string) ?? null,
                relevance_score: null,
              }));
            onNewPapers(papers);
          } catch {
            // graph read failure shouldn't block showing the answer
          }

          setTurns((t) => [
            ...t,
            {
              role: "assistant",
              id: crypto.randomUUID(),
              text: res.answer,
              papers,
              kind: "chat",
            },
          ]);
          onOpenGraph();
        } else {
          const res = await api.chat({
            query,
            session_id: sessionId,
            upload_mode: uploadMode,
            include_uploaded: uploadMode !== "none",
          });
          onNewPapers(res.papers ?? []);
          setTurns((t) => [
            ...t,
            {
              role: "assistant",
              id: crypto.randomUUID(),
              text: res.answer,
              papers: res.papers,
              citations: res.citations,
              coverageGaps: res.coverage_gaps,
              domainCaveat: res.domain_caveat,
              papersBelowThreshold: res.papers_below_threshold,
              kind: "chat",
            },
          ]);
        }
      } else {
        const res = await api.followup({ session_id: sessionId, question: query });
        setTurns((t) => [
          ...t,
          {
            role: "assistant",
            id: crypto.randomUUID(),
            text: res.answer,
            sources: res.sources,
            kind: "followup",
          },
        ]);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
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
              <select
                value={uploadMode}
                onChange={(e) => setUploadMode(e.target.value as "none" | "blend" | "grounded_only")}
                disabled={hasConversation || researchMode}
                className="bg-paper-dim text-ink rounded px-1.5 py-0.5 border border-line text-[10px]"
              >
                <option value="blend">Blend (Online + PDF)</option>
                <option value="grounded_only">PDF Only</option>
                <option value="none">Online Only</option>
              </select>
            </div>
          )}
          <button
            onClick={() => {
              setResearchMode((prev) => !prev);
              if (!researchMode) onOpenGraph();
            }}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition-colors ${
              researchMode
                ? "bg-indigo text-white"
                : "bg-paper-dim text-ink-soft hover:text-ink hover:bg-paper"
            }`}
            aria-label="Toggle research graph mode"
          >
            <Network className="h-3 w-3" />
            {researchMode ? "Graph" : "Chat"}
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {!hasConversation && (
          <div className="flex h-full flex-col items-center justify-center text-center px-6">
            <Sparkles className="h-6 w-6 text-indigo/40 mb-3" />
            <p className="font-serif text-[15px] text-ink mb-1">Ask about the research</p>
            <p className="text-[12.5px] text-ink-soft max-w-[220px]">
              Search papers, ask follow-ups, or upload a PDF to ground answers in it.
            </p>
          </div>
        )}

        {turns.map((t) => (
          <ChatMessage key={t.id} turn={t} />
        ))}

        {loading && (
          <div className="flex items-center gap-2 text-[12.5px] text-ink-soft animate-fade-up">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {hasConversation
              ? "Finding an answer in this session\u2026"
              : researchMode
                ? "Running the research pipeline and building the graph\u2026"
                : "Searching papers\u2026"}
          </div>
        )}

        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger animate-fade-up">
            {error}
          </div>
        )}
      </div>

      <div className="border-t border-line p-3">
        <div className="flex items-end gap-2 rounded-xl border border-line bg-paper-dim/70 px-2.5 py-2 shadow-inner shadow-black/5 focus-within:border-indigo/50">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            aria-label="Attach PDF"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-indigo disabled:opacity-50"
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Paperclip className="h-4 w-4" />
            )}
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
            placeholder="Ask AI about papers, or upload a PDF\u2026"
            className="max-h-40 min-h-[22px] flex-1 resize-none overflow-y-auto bg-transparent text-[13px] leading-relaxed text-ink placeholder:text-ink-soft/60 focus:outline-none py-1"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            aria-label="Send message"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gold text-white transition-opacity hover:bg-gold/90 disabled:opacity-30"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
