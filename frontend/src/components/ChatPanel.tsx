"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { ArrowUp, Paperclip, Loader2, Square, MoreHorizontal, Pin, Share2, Check } from "lucide-react";
import Image from "next/image";
import { api, ApiError, ApiAbortError } from "@/lib/api";
import type {
  ChatTurn,
  Paper,
  ResponseMode,
  EvidenceMode,
  StreamEvent,
  ChatResponse,
} from "@/lib/types";
import { ChatMessage } from "./ChatMessage";
import { UploadPreviewCard } from "./UploadPreviewCard";
import { Dropdown } from "@/components/Dropdown";

function getGreeting(): { title: string; subtitle: string } {
  const h = new Date().getHours();
  if (h >= 0 && h < 5)
    return { title: "Late-night research", subtitle: "Search papers, ask follow-ups, or upload a PDF to ground answers in it." };
  if (h < 12)
    return { title: "Good morning", subtitle: "Search papers, ask follow-ups, or upload a PDF to ground answers in it." };
  if (h < 18)
    return { title: "Good afternoon", subtitle: "Search papers, ask follow-ups, or upload a PDF to ground answers in it." };
  if (h < 23)
    return { title: "Good evening", subtitle: "Search papers, ask follow-ups, or upload a PDF to ground answers in it." };
  return { title: "Still thinking?", subtitle: "Search papers, ask follow-ups, or upload a PDF to ground answers in it." };
}

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
  onUploadComplete: (data: { filename: string; fileUrl: string; link: string }) => void;
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
  setUploadState: React.Dispatch<
    React.SetStateAction<{
      status: "idle" | "uploading" | "processing" | "done" | "error";
      filename: string;
      progress: string;
      stage: string;
      fileUrl: string;
    }>
  >;
  hasUpload: boolean;
  setHasUpload: React.Dispatch<React.SetStateAction<boolean>>;
  evidenceMode: EvidenceMode;
  setEvidenceMode: React.Dispatch<React.SetStateAction<EvidenceMode>>;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [responseMode, setResponseMode] = useState<ResponseMode>("normal");
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestIdRef = useRef<string | null>(null);
  const turnsRef = useRef<ChatTurn[]>(turns);
  const menuRef = useRef<HTMLDivElement>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const MAX_FILES_PER_MESSAGE = 3;
  const MAX_CONCURRENT_UPLOADS = 1;

  type UploadItem = {
    id: string;
    status: "queued" | "uploading" | "processing" | "done" | "error";
    filename: string;
    progress: string;
    stage: string;
    fileUrl: string;
    link: string;
    requestId: string | null;
  };

  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const uploadControllersRef = useRef<Map<string, AbortController>>(new Map());
  const uploadQueueRef = useRef<{ id: string; file: File }[]>([]);
  const activeUploadCountRef = useRef(0);
  const isAnyStreaming = turns.some(t => t.streaming);
  const isGenerating = loading || isAnyStreaming;
  function patchUpload(id: string, patch: Partial<UploadItem> | ((prev: UploadItem) => Partial<UploadItem>)) {
    setUploads((prev) =>
      prev.map((u) => (u.id !== id ? u : { ...u, ...(typeof patch === "function" ? patch(u) : patch) }))
    );
  }

  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, loading]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  useEffect(() => {
    try {
      setPinned(localStorage.getItem(`sykra:pinned:${sessionId}`) === "1");
    } catch {
      setPinned(false);
    }
  }, [sessionId]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  const hasConversation = turns.length > 0;

  function flashToast(msg: string) {
    setToast(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(null), 1800);
  }

  function handleTogglePin() {
    setMenuOpen(false);
    setPinned((prev) => {
      const next = !prev;
      try {
        if (next) localStorage.setItem(`sykra:pinned:${sessionId}`, "1");
        else localStorage.removeItem(`sykra:pinned:${sessionId}`);
      } catch {
      }
      flashToast(next ? "Conversation pinned" : "Conversation unpinned");
      return next;
    });
  }

  async function handleShareConversation() {
    setMenuOpen(false);
    const body = turns.map((t) => `${t.role === "user" ? "You" : "Sykra"}: ${t.text}`).join("\n\n");
    if (!body.trim()) {
      flashToast("Nothing to share yet.");
      return;
    }
    try {
      if (navigator.share) {
        await navigator.share({ title: "Sykra Research", text: body });
        return;
      }
    } catch {}
    try {
      await navigator.clipboard.writeText(body);
      flashToast("Conversation copied to clipboard");
    } catch {
      flashToast("Couldn't copy — try again");
    }
  }

  function handleChatScroll() {
    const el = scrollRef.current;
    if (el) setScrolled(el.scrollTop > 6);
  }

  function appendAssistantTurn(turn: ChatTurn) {
    setTurns((t) => [...t, turn]);
  }

  function updateTurn(id: string, patch: Partial<ChatTurn> | ((prev: ChatTurn) => Partial<ChatTurn>)) {
    setTurns((prev) =>
      prev.map((turn) =>
        turn.id !== id ? turn : { ...turn, ...(typeof patch === "function" ? patch(turn) : patch) }
      )
    );
  }

  function applyStreamEvent(turnId: string, event: StreamEvent, opts: { isChat: boolean }) {
    switch (event.type) {
      case "progress":
        updateTurn(turnId, (prev) => ({
          statusLabel: event.label,
          statusSteps: [
            ...(prev.statusSteps ?? []),
            { stage: event.stage ?? "default", label: event.label, detail: event.detail, items: event.items },
          ],
        }));
        break;

      case "notice":
        updateTurn(turnId, { reportNotice: event.message });
        break;

      case "token":
        if (event.kind === "preview") {
          updateTurn(turnId, (prev) => ({
            previewText: (prev.previewText ?? "") + event.text,
            statusLabel: undefined,
          }));
        } else {
          updateTurn(turnId, (prev) => ({
            text: prev.text + event.text,
            statusLabel: undefined,
          }));
        }
        break;

      case "artifact":
        updateTurn(turnId, (prev) => {
          const artifacts = { ...(prev.artifacts ?? {}) };

          if (event.artifact_type === "chart") {
            artifacts.chartUrl = event.url;
            artifacts.chartSpecRaw = event.raw_spec ?? null;
          } else if (event.artifact_type === "comparison_table") {
            artifacts.comparisonTableMarkdown = event.markdown;
            artifacts.comparisonTableCaption = event.caption ?? null;
          } else if (event.artifact_type === "graph_entities") {
            artifacts.graphEntities = event.entities;
          }

          return {
            artifacts,
            chartUrl: artifacts.chartUrl ?? prev.chartUrl,
          };
        });
        break;

      case "filename":
        updateTurn(turnId, { filename: event.filename });
        break;

      case "done": {
        updateTurn(turnId, { streaming: false, statusLabel: undefined });

        const current = turnsRef.current.find((t) => t.id === turnId);
        if (current && !current.filename && current.turnId) {
          const tid = current.turnId;
          api.pollFilename(tid).then((fn) => {
            if (fn) updateTurn(turnId, { filename: fn });
          });
        }
        break;
      }

      case "result": {
        if (opts.isChat) {
          const res = event.payload as ChatResponse;
          onNewPapers(res.papers ?? []);
          updateTurn(turnId, (prev) => {
            const finalAnswer = (res.answer ?? "").trim();
            const nextText =
              finalAnswer && finalAnswer !== (prev.text ?? "").trim()
                ? res.answer
                : prev.text;
            return {
              text: nextText,
              papers: res.papers,
              citations: res.citations,
              papersBelowThreshold: res.papers_below_threshold,
              references: res.references,
              responseMode: res.response_mode,
              streaming: false,
              statusLabel: undefined,
              turnId: res.turn_id,
              chartUrl: res.chart_url ?? null,
              filename: res.filename || undefined,
              reportPlan: res.report_plan ?? null,
              sections: res.sections ?? [],
              informationNeeds: res.information_needs ?? [],
              complexityScore: res.complexity_score ?? 0,
              reportNotice: res.report_notice ?? undefined,
              disclaimer: res.disclaimer ?? null,
            };
          });
        }
        break;
      }

      case "cancelled":
        updateTurn(turnId, { streaming: false, stopped: true, statusLabel: undefined });
        break;

      case "error":
        updateTurn(turnId, { streaming: false, statusLabel: undefined });
        setError(event.message);
        break;
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

    try {
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
    } finally {
      const current = turnsRef.current.find((t) => t.id === assistantId);
      if (current && current.streaming) {
        updateTurn(assistantId, { streaming: false, statusLabel: undefined });
      }
    }
  }

  async function handleSend() {
    const query = input.trim();
    if (!query || isGenerating) return;

    setError(null);
    setInput("");

    const userTurn: ChatTurn = { role: "user", id: crypto.randomUUID(), text: query };
    setTurns((t) => [...t, userTurn]);
    setUploads((prev) => prev.filter((u) => u.status !== "done"));
    setLoading(true);

    const history = turns.map((t) => ({ role: t.role as "user" | "assistant", content: t.text }));

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

  function handlePauseUpload(id: string) {
    const item = uploads.find((u) => u.id === id);
    if (item?.requestId) api.cancelUploadStream(item.requestId).catch(() => {});
    uploadControllersRef.current.get(id)?.abort();
    uploadControllersRef.current.delete(id);
    setUploads((prev) => prev.filter((u) => u.id !== id));
    activeUploadCountRef.current = Math.max(0, activeUploadCountRef.current - 1);
    pumpUploadQueue();
  }

  const pumpUploadQueue = useCallback(() => {
    while (activeUploadCountRef.current < MAX_CONCURRENT_UPLOADS && uploadQueueRef.current.length > 0) {
      const next = uploadQueueRef.current.shift();
      if (!next) break;
      activeUploadCountRef.current += 1;
      runSingleUpload(next.id, next.file);
    }
  }, []);

  async function runSingleUpload(id: string, file: File) {
    patchUpload(id, { status: "uploading", progress: "Uploading file...", stage: "uploading" });

    const requestId = crypto.randomUUID();
    const controller = new AbortController();
    uploadControllersRef.current.set(id, controller);
    patchUpload(id, { requestId });

    try {
      await api.uploadPdfStream(
        file,
        sessionId,
        (event) => {
          if (event.type === "cancelled") {
            setUploads((prev) => prev.filter((u) => u.id !== id));
            return;
          }
          if (event.type === "progress") {
            patchUpload(id, { status: "processing", progress: event.label, stage: event.stage ?? "" });
          }
          if (event.type === "result") {
            patchUpload(id, {
              status: "done",
              progress: "Ready",
              fileUrl: event.payload.file_url,
              link: event.payload.link,
              filename: event.payload.filename,
            });
            setHasUpload(true);
            setEvidenceMode((prevMode) => (prevMode === "literature" ? "blended" : prevMode));
            onUploadComplete({
              filename: event.payload.filename,
              fileUrl: event.payload.file_url,
              link: event.payload.link,
            });
          }
          if (event.type === "error") {
            setError(event.message);
            patchUpload(id, { status: "error" });
          }
        },
        controller.signal,
        requestId
      );
    } catch (err) {
      if (!(err instanceof ApiAbortError)) {
        setError(err instanceof ApiError ? err.message : "Upload failed.");
        patchUpload(id, { status: "error" });
      }
    } finally {
      uploadControllersRef.current.delete(id);
      activeUploadCountRef.current = Math.max(0, activeUploadCountRef.current - 1);
      pumpUploadQueue();
    }
  }

  function handleFilesChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (selected.length === 0) return;

    setUploads((prev) => {
      const currentCount = prev.filter((u) => u.status !== "error").length;
      const room = MAX_FILES_PER_MESSAGE - currentCount;
      const accepted = selected.slice(0, Math.max(room, 0));
      const rejected = selected.slice(Math.max(room, 0));

      if (accepted.length === 0) {
        setError(`You can attach up to ${MAX_FILES_PER_MESSAGE} files per message. Send this message first, then attach more.`);
      } else if (rejected.length > 0) {
        setError(`Only ${accepted.length} of ${selected.length} files were added — max ${MAX_FILES_PER_MESSAGE} per message. Send this message, then attach the rest.`);
      } else {
        setError(null);
      }

      const acceptedItems: UploadItem[] = accepted.map((file) => ({
        id: crypto.randomUUID(),
        status: "queued",
        filename: file.name,
        progress: "Queued...",
        stage: "queued",
        fileUrl: "",
        link: "",
        requestId: null,
      }));

      const rejectedItems: UploadItem[] = rejected.map((file) => ({
        id: crypto.randomUUID(),
        status: "error",
        filename: file.name,
        progress: `Not uploaded — limit of ${MAX_FILES_PER_MESSAGE} files reached`,
        stage: "rejected",
        fileUrl: "",
        link: "",
        requestId: null,
      }));

      acceptedItems.forEach((item, i) => uploadQueueRef.current.push({ id: item.id, file: accepted[i] }));
      queueMicrotask(pumpUploadQueue);

      return [...prev, ...acceptedItems, ...rejectedItems];
    });
  }

  const composer = (
    <div className="w-full">
      {uploads.length > 0 && (
        <div className="mb-2 flex flex-col gap-1.5">
          {uploads.map((u) => (
            <UploadPreviewCard
              key={u.id}
              filename={u.filename}
              status={u.status === "queued" ? "uploading" : u.status}
              progress={u.progress}
              fileUrl={u.fileUrl}
              onOpen={() => {
                if (u.fileUrl) onOpenPdf(u.fileUrl);
              }}
              onCancel={() => handlePauseUpload(u.id)}
              onClose={() => {
                if (u.status === "done") {
                  const link = u.fileUrl;
                  setUploads((prev) => prev.filter((x) => x.id !== u.id));
                  if (uploads.length <= 1) {
                    setHasUpload(false);
                    setEvidenceMode("literature");
                  }
                  onDeletePaper?.(link);
                } else {
                  handlePauseUpload(u.id);
                }
              }}
            />
          ))}
        </div>
      )}

      <div className="flex items-end gap-2 rounded-2xl border border-line bg-paper-dim/70 px-2.5 py-1.5 shadow-sm shadow-black/5 transition-colors focus-within:border-indigo/50">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploads.filter((u) => u.status !== "error").length >= MAX_FILES_PER_MESSAGE}
          aria-label="Attach PDF (up to 3 files)"
          title={`Attach up to ${MAX_FILES_PER_MESSAGE} PDFs`}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-paper hover:text-ink disabled:opacity-50"
        >
          {uploads.some((u) => u.status === "uploading" || u.status === "processing" || u.status === "queued") ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Paperclip className="h-4 w-4" />
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={handleFilesChange}
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
          disabled={isGenerating}
          rows={1}
          placeholder="Ask a question, or drop a PDF to ground it"
          className="min-h-[24px] max-h-28 flex-1 resize-none overflow-y-auto bg-transparent py-1.5 text-body leading-6 text-ink placeholder:text-ink-soft/60 focus:outline-none"
        />

        {hasUpload && (
          <Dropdown
            value={evidenceMode}
            onChange={setEvidenceMode}
            items={[
              { value: "uploaded", label: "Uploaded document", hint: "Answer using only the uploaded document." },
              { value: "blended", label: "Blend", hint: "Combine the uploaded document with external literature." },
            ]}
          />
        )}

        <Dropdown
          value={responseMode}
          onChange={setResponseMode}
          items={[
            { value: "normal", label: "Normal", hint: "Quick, concise answers." },
            { value: "researched", label: "Researched", hint: "Full structured report with inline citations and references." },
          ]}
        />

        {isGenerating ? (
          <button
            onClick={handlePause}
            aria-label="Pause generation"
            title="Stop generating this response"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger text-white transition hover:bg-danger/90 active:scale-95"
          >
            <Square className="h-3 w-3 fill-current" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            aria-label="Send message"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-white transition hover:bg-accent-dark active:scale-95 disabled:opacity-30"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );

  if (!hasConversation) {
    const greeting = getGreeting();
    return (
      <div className="relative flex h-full flex-col overflow-hidden">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="relative h-[640px] w-[640px] origin-center text-ink opacity-[0.08] animate-[spin_120s_linear_infinite]">
            <svg width="640" height="640" viewBox="0 0 640 640" className="absolute inset-0">
              <circle cx="320" cy="320" r="90" fill="none" stroke="currentColor" strokeWidth="1" />
              <circle cx="320" cy="320" r="170" fill="none" stroke="currentColor" strokeWidth="1" />
              <circle cx="320" cy="320" r="250" fill="none" stroke="currentColor" strokeWidth="1" />
            </svg>
            <span className="absolute left-1/2 top-[70px] h-2 w-2 -translate-x-1/2 rounded-full bg-ink" />
            <span className="absolute left-[150px] top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-ink" />
            <span className="absolute left-1/2 top-[570px] h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-ink" />
          </div>
          <div className="relative h-[340px] w-[340px] origin-center opacity-[0.07] animate-[spin_80s_linear_infinite_reverse]">
            <span className="absolute left-1/2 top-0 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-indigo" />
          </div>
        </div>

        <div className="relative flex-1 flex flex-col items-center justify-center px-6">
          <div className="w-full max-w-[600px] flex flex-col items-center">
            <Image src="/sykra-logo.svg" alt="Sykra" width={64} height={64} className="mb-3 object-contain" />
            <h1 className="font-serif text-[30px] font-semibold tracking-tight text-ink mb-2.5 text-center">
              {greeting.title}
            </h1>
            <p className="text-body text-ink-soft mb-8 text-center max-w-[440px] leading-relaxed">
              Ask anything across your papers and the open literature. Every answer arrives cited, sourced, and ready to
              export.
            </p>
            {composer}
          </div>
        </div>

        {error && (
          <div className="relative px-6 pb-4">
            <div className="mx-auto max-w-[560px] rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-caption text-danger">
              {error}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex-1 min-h-0 flex flex-col">
        <div
          className={`pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-end px-4 transition-all duration-300 ${
            scrolled ? "h-12 bg-paper/70 backdrop-blur-md border-b border-line/70 shadow-[0_1px_0_rgba(0,0,0,0.02)]" : "h-14 bg-transparent border-b border-transparent"
          }`}
        >
          <div className="relative pointer-events-auto" ref={menuRef}>
            <button
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Conversation options"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              className={`flex h-8 w-8 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-paper-dim hover:text-ink ${
                menuOpen ? "bg-paper-dim text-ink" : ""
              }`}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 top-full z-30 mt-1.5 w-52 overflow-hidden rounded-xl border border-line bg-paper/95 py-1 shadow-lg shadow-black/10 backdrop-blur-md animate-fade-up"
              >
                <button
                  role="menuitem"
                  onClick={handleTogglePin}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-caption transition-colors hover:bg-paper-dim ${
                    pinned ? "text-indigo" : "text-ink"
                  }`}
                >
                  <Pin className={`h-3.5 w-3.5 ${pinned ? "text-indigo" : "text-ink-soft"}`} />
                  <span className="flex-1">{pinned ? "Unpin conversation" : "Pin conversation"}</span>
                  {pinned && <Check className="h-3.5 w-3.5 text-indigo" />}
                </button>
                <button
                  role="menuitem"
                  onClick={handleShareConversation}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-caption text-ink transition-colors hover:bg-paper-dim"
                >
                  <Share2 className="h-3.5 w-3.5 text-ink-soft" />
                  <span className="flex-1">Share conversation</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {toast && (
          <div className="pointer-events-none absolute bottom-3 left-1/2 z-30 -translate-x-1/2 animate-fade-up">
            <div className="rounded-full border border-white/10 bg-ink/90 px-3.5 py-1.5 text-caption font-medium text-white shadow-lg shadow-black/20 backdrop-blur-sm">
              {toast}
            </div>
          </div>
        )}

        <div
          ref={scrollRef}
          onScroll={handleChatScroll}
          className="h-full overflow-y-auto px-4 space-y-4"
          style={{ paddingTop: 56, paddingBottom: 16 }}
        >
          {turns.map((t) => (
            <ChatMessage
              key={t.id}
              turn={t}
              sessionId={sessionId}
              onOpenGraph={onOpenGraph}
              onRegenerate={async () => {
                if (isGenerating) return;
                setError(null);
                setLoading(true);
                try {
                  const controller = new AbortController();
                  abortRef.current = controller;
                  const mode = t.responseMode ?? "normal";
                  const res = await api.chatRegenerate(
                    {
                      session_id: sessionId,
                      turn_id: t.turnId,
                      query: t.sourceQuery ?? "",
                      response_mode: mode,
                      is_followup: false,
                      evidence_mode: t.sourceEvidenceMode ?? "literature",
                    },
                    controller.signal
                  );
                  setTurns((prev) =>
                    prev.map((turn) =>
                      turn.id === t.id
                        ? {
                            ...turn,
                            text: res.answer,
                            citations: res.citations,
                            references: res.references,
                            responseMode: res.response_mode,
                            stopped: false,
                            turnId: res.turn_id,
                            chartUrl: res.chart_url ?? null,
                            filename: res.filename || turn.filename,
                            reportPlan: res.report_plan ?? null,
                            sections: res.sections ?? [],
                            disclaimer: res.disclaimer ?? null,
                            informationNeeds: res.information_needs ?? [],
                            complexityScore: res.complexity_score ?? 0,
                          }
                        : turn
                    )
                  );
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
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-caption text-danger animate-fade-up">
              {error}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-line p-3">{composer}</div>
    </div>
  );
}