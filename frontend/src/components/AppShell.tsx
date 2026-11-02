"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter, usePathname } from "next/navigation";
import {
  PanelLeft,
  FolderOpen,
  ArrowLeft,
  SquarePen,
  Shapes,
  LogOut,
  Trash2,
  Pencil,
  Pin,
  FileText,
  PanelRight,
  Sun, Moon,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { RightRail } from "./RightRail";
import { ChatPanel } from "./ChatPanel";
import { GraphView } from "./GraphView";
import { api, ApiError } from "@/lib/api";
import { StudioView } from "./studio/StudioView";
import { ReportView } from "./report/ReportView";
import { FilesPage } from "./FilesPage";

import type { ChatTurn, Paper, EvidenceMode, StatusStep, ReportType, ReportRecord } from "@/lib/types";
import dynamic from "next/dynamic";

const PdfViewer = dynamic(() => import("./PdfViewer").then((m) => m.PdfViewer), {
  ssr: false,
});
import { PdfViewerBoundary } from "./PdfViewerBoundary";
import { ConfirmDialog, NameDialog } from "./ConfirmDialog";
import { SessionDashboard, type DashboardSession } from "./SessionDashboard";
import { Avatar } from "./Avatar";
import { ThemeProvider, useTheme, useLocalStorageFlag } from "@/lib/theme";
import { watchGeneration } from "@/lib/chatGenerationStore";

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
const SIDEBAR_WIDTH = 260;
const SIDEBAR_COLLAPSED_WIDTH = 48;
const PDF_WIDTH_DEFAULT = 50;
const PDF_WIDTH_MIN = 30;
const PDF_WIDTH_MAX = 70;

type ChatSummary = { id: string; title: string; session_id?: string; session_name?: string | null; created_at: string; updated_at: string; pinned_at?: string | null; generation_status?: string | null };

function groupChats(chats: ChatSummary[]): [string, ChatSummary[]][] {
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups: Record<string, ChatSummary[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    Older: [],
  };
  for (const chat of chats) {
    const days = Math.floor((startToday - new Date(new Date(chat.updated_at).getFullYear(), new Date(chat.updated_at).getMonth(), new Date(chat.updated_at).getDate()).getTime()) / 86400000);
    if (days <= 0) groups.Today.push(chat);
    else if (days === 1) groups.Yesterday.push(chat);
    else if (days < 7) groups["Previous 7 days"].push(chat);
    else groups.Older.push(chat);
  }

  return Object.entries(groups).filter(([, items]) => items.length > 0);
}

function SessionMenu({ onRename, onDelete }: { onRename: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const W = 128, H = 96;
      const top = r.bottom + H + 8 > window.innerHeight ? r.top - H - 4 : r.bottom + 4;
      setPos({ top, left: Math.max(8, r.right - W) });
    }
    setOpen((v) => !v);
  };

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const dismiss = () => setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    window.addEventListener("scroll", dismiss, true);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("scroll", dismiss, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [open]);

  return (
    <div className="relative shrink-0">
      <button ref={btnRef} onClick={toggle} aria-label="Open menu" aria-expanded={open} className="rounded-md p-1.5 text-ink-soft hover:bg-paper">
        <span className="text-lg leading-none">…</span>
      </button>
      {open && createPortal(
        <div ref={menuRef} style={{ position: "fixed", top: pos.top, left: pos.left }} className="z-[100] w-32 rounded-xl border border-line bg-white p-1.5 shadow-xl">
          <button onClick={() => { setOpen(false); onRename(); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-paper"><Pencil className="h-3.5 w-3.5" />Rename</button>
          <button onClick={() => { setOpen(false); onDelete(); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-danger hover:bg-danger/5"><Trash2 className="h-3.5 w-3.5" />Delete</button>
        </div>,
        document.body
      )}
    </div>
  );
}

function ChatHistory({ chats, activeChatId, sessionId, onRename, onDelete, onPin, onNavigate }: { chats: ChatSummary[]; activeChatId?: string; sessionId: string; onRename: (chat: ChatSummary) => void; onDelete: (chat: ChatSummary) => void; onPin: (chat: ChatSummary) => void; onNavigate?: () => void }) {
  const pinned = chats.filter((chat) => chat.pinned_at);
  const groups = groupChats(chats.filter((chat) => !chat.pinned_at));
  const renderRow = (chat: ChatSummary) => <div key={chat.id} className={`group/chat flex min-w-0 items-center gap-1 rounded-md ${activeChatId === chat.id ? "app-sidebar-selected text-ink font-medium" : "text-ink-soft"}`}><Link href={`/app/s/${sessionId}/chat/${chat.id}`} onClick={onNavigate} className="flex min-w-0 flex-1 items-center gap-2 truncate px-2.5 py-1.5 text-caption hover:text-ink">{chat.generation_status === "generating" || chat.generation_status === "streaming" ? <span className="h-2.5 w-2.5 shrink-0 animate-pulse rounded-full border-2 border-indigo border-t-transparent" aria-label="Generating" /> : chat.generation_status === "complete" && activeChatId !== chat.id ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-gold" aria-label="Completed" /> : null}<span className="truncate">{chat.title}</span></Link><div className={`mr-1 flex shrink-0 gap-0.5 ${activeChatId === chat.id ? "" : "opacity-0 group-hover/chat:opacity-100"}`}><button onClick={() => onPin(chat)} aria-label={chat.pinned_at ? "Unpin chat" : "Pin chat"} className="rounded p-1 hover:bg-paper"><Pin className={`h-3 w-3 ${chat.pinned_at ? "fill-current" : ""}`} /></button><SessionMenu onRename={() => onRename(chat)} onDelete={() => onDelete(chat)} /></div></div>;
  return <>{pinned.length > 0 && <div className="mb-3"><p className="px-1.5 pb-1 text-micro font-semibold uppercase tracking-wide text-ink-soft/60">PINNED</p>{pinned.map(renderRow)}</div>}{groups.map(([group, items]) => <div key={group} className="mb-3"><p className="px-1.5 pb-1 text-micro font-semibold uppercase tracking-wide text-ink-soft/60">{group}</p>{items.map(renderRow)}</div>)}</>;
}

function AppShellInner({ initialSessionId, initialChatId, dashboard = false, initialGraphView = false, initialFiles = false, initialStudio = false, initialReport = false }: { initialSessionId?: string; initialChatId?: string; dashboard?: boolean; initialGraphView?: boolean; initialFiles?: boolean; initialStudio?: boolean; initialReport?: boolean }) {
  const { theme, toggleTheme } = useTheme();
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<{ name: string | null; email: string; image: string | null } | null>(null);
  const [recentChats, setRecentChats] = useState<ChatSummary[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [sessionId, setSessionId] = useState(
    () => initialSessionId || crypto.randomUUID()
  );
  const [sessionName, setSessionName] = useState("Session");
  const [sessions, setSessions] = useState<DashboardSession[]>([]);
  const [dialog, setDialog] = useState<{ kind: "create-session" | "rename-session" | "rename-chat"; item?: DashboardSession | ChatSummary } | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "session" | "chat"; item: DashboardSession | ChatSummary } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [studioTurns, setStudioTurns] = useState<ChatTurn[]>([]);
  const [railOpen, setRailOpen] = useState(true);
  const [studioChatOpen, setStudioChatOpen] = useLocalStorageFlag("sykra:studio-chat-open", true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [tab, setTab] = useState<"library" | "explore">(initialGraphView ? "explore" : "library");
  const [localGraph, setLocalGraph] = useState(false);
  const showGraphView = initialGraphView || localGraph;
  const [seenGraphView, setSeenGraphView] = useState(initialGraphView);
  if (seenGraphView !== initialGraphView) {
    setSeenGraphView(initialGraphView);
    setTab(initialGraphView ? "explore" : "library");
  }
  const containerRef = useRef<HTMLDivElement>(null);

  const [pdfViewerUrl, setPdfViewerUrl] = useState<string | null>(null);
  const [pdfWidthPct, setPdfWidthPct] = useState(PDF_WIDTH_DEFAULT);
  const [draggingPdf, setDraggingPdf] = useState(false);

  const showFiles = initialFiles;
  const showStudio = initialStudio;
  const showReport = initialReport;
  const [hasUpload, setHasUpload] = useState(false);
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>("literature");
  const refreshLibrary = useCallback(() => {
    if (!initialSessionId || !initialChatId) return;
    api.listLibraryPapers(initialSessionId, initialChatId).then(setPapers).catch(() => {});
  }, [initialSessionId, initialChatId]);

  useEffect(() => {
    api.listSessions().then(setSessions).catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    if (initialSessionId) api.getSession(initialSessionId).then((session) => setSessionName(session.name)).catch(() => setSessionName("Session"));
  }, [initialSessionId]);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api"}/auth/me`, { credentials: "include" })
      .then((response) => (response.ok ? response.json() : null))
      .then((user: { name: string | null; email: string; image: string | null } | null) => {
        setCurrentUser(user);
      })
      .catch(() => setCurrentUser(null));
  }, []);

  useEffect(() => {
    if (!currentUser) return;
    api.listChats(undefined, initialSessionId).then(setRecentChats).catch(() => setRecentChats([]));
  }, [currentUser, initialSessionId, initialChatId]);

  const [seenChatId, setSeenChatId] = useState(initialChatId);
  if (seenChatId !== initialChatId) {
    setSeenChatId(initialChatId);
    if (initialChatId) setTurns([]);
  }
  useEffect(() => {
    if (!initialChatId) return;
    api.getChat(initialChatId).then((messages) => {
      setTurns(messages.map((message) => {
        const c = (message.citations ?? {}) as Record<string, unknown>;
        const isA = message.role === "assistant";
        return {
          id: message.id,
          role: message.role as ChatTurn["role"],
          text: message.content,
          streaming: isA && message.status === "streaming",
          stopped: isA && message.status === "interrupted",
          references: Array.isArray(c.references) ? c.references as ChatTurn["references"] : [],
          statusSteps: Array.isArray(c.status_steps) ? c.status_steps as StatusStep[] : undefined,
          responseMode: isA ? ((c.response_mode as ChatTurn["responseMode"]) ?? (/^## /m.test(message.content) ? "researched" : "normal")) : undefined,
          sourceEvidenceMode: c.evidence_mode as ChatTurn["sourceEvidenceMode"],
          sourceQuery: c.source_query as string | undefined,
          sourceReport: c.report_mode
            ? {
                reportType: ((c.report_type as ReportType | undefined) ?? "general"),
                records: Array.isArray(c.confirmed_source_records)
                  ? (c.confirmed_source_records as ReportRecord[])
                  : [],
              }
            : undefined,
          paperLinks: Array.isArray(c.paper_links) ? c.paper_links as string[] : undefined,
        };
      }));
      const cleanups = messages
        .filter((message) => message.status === "generating" || message.status === "streaming")
        .map((message) => watchGeneration(initialChatId, message.id, (snapshot) => {
          setTurns((current) => current.map((turn) => turn.id === snapshot.id ? {
            ...turn,
            text: snapshot.content,
            streaming: snapshot.status === "generating" || snapshot.status === "streaming",
            stopped: snapshot.status === "interrupted" || snapshot.status === "stopped",
          } : turn));
        }));
      (window as Window & { __sykraGenerationCleanups?: (() => void)[] }).__sykraGenerationCleanups?.forEach((cleanup) => cleanup());
      (window as Window & { __sykraGenerationCleanups?: (() => void)[] }).__sykraGenerationCleanups = cleanups;
    }).catch(() => setTurns([]));
    return () => {
      const state = window as Window & { __sykraGenerationCleanups?: (() => void)[] };
      state.__sykraGenerationCleanups?.forEach((cleanup) => cleanup());
      state.__sykraGenerationCleanups = [];
    };
  }, [initialChatId]);

  const prevChatId = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!initialSessionId) return;
    if (!initialChatId || (prevChatId.current && prevChatId.current !== initialChatId)) {
      setPapers([]);
      setHasUpload(false);
      setUploadedFilename(null);
    }
    prevChatId.current = initialChatId;
    if (!initialChatId) return;
    api.listLibraryPapers(initialSessionId, initialChatId)
      .then((saved) => {
        setPapers((prev) => mergePapers(saved, prev));
        const up = saved.find((p) => p.is_uploaded);
        if (up) { setHasUpload(true); setUploadedFilename(up.title); }
      })
      .catch(() => {});
  }, [initialSessionId, initialChatId]);

  const handleLogout = async () => {
    await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api"}/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    window.location.href = "/login";
  };

  const [uploadState, setUploadState] = useState({
    status: "idle" as "idle" | "uploading" | "processing" | "done" | "error",
    filename: "",
    progress: "",
    stage: "",
    fileUrl: "",
  });

  const lastAssistantTurn = [...turns]
    .reverse()
    .find((t) => t.role === "assistant" && !t.streaming && t.text?.trim());
  const lastAssistantTurnId = lastAssistantTurn?.turnId ?? lastAssistantTurn?.id ?? null;

  const lastAssistantPaperLinks = (
    lastAssistantTurn?.papers?.length ? lastAssistantTurn.papers.map((p) => p.link)
    : lastAssistantTurn?.paperLinks?.length ? lastAssistantTurn.paperLinks
    : lastAssistantTurn?.references?.map((r) => r.link) ?? []
  ).filter(Boolean);

  const getConversationContext = useCallback(() => {
    const reversed = [...turns].reverse();

    const lastAssistant = reversed.find(
      (t) => t.role === "assistant" && t.text?.trim()
    );

    const lastUser = reversed.find(
      (t) => t.role === "user" && t.text?.trim()
    );

    const excerpt = [
      lastAssistant?.text?.trim(),
      lastUser?.text?.trim(),
    ]
      .filter(Boolean)
      .join("\n\n")
      .slice(0, 3000);

    const paperLinks = papers
      .map((p) => p.link)
      .filter(Boolean) as string[];

    return {
      excerpt,
      papers: paperLinks,
    };
  }, [turns, papers]);

  const handleNewPapers = useCallback((incoming: Paper[]) => {
    if (!incoming.length) return;
    setPapers((prev) => mergePapers(prev, incoming));
  }, []);

  const handleOpenGraph = () => {
    if (initialSessionId && initialChatId) {
      router.push(`/app/s/${initialSessionId}/chat/${initialChatId}/graph`);
      return;
    }
    setLocalGraph(true);
    setRailOpen(true);
    setTab("explore");
  };
  const handleBackToChat = () => {
    if (initialSessionId && initialChatId && initialGraphView) {
      router.push(`/app/s/${initialSessionId}/chat/${initialChatId}`);
      return;
    }
    setLocalGraph(false);
  };

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

  const handleNewChat = async () => {
    setLocalGraph(false);
    setTurns([]);
    setUploadedFilename(null);
    setUploadState({ status: "idle", filename: "", progress: "", stage: "", fileUrl: "" });
    setHasUpload(false);
    setEvidenceMode("literature");
    const onPlainSession = !initialChatId && !initialFiles && !initialStudio && !initialReport;
    if (sessionId && !onPlainSession) router.push(`/app/s/${sessionId}`);
  };
  const handleRenameChat = async (chat: ChatSummary) => {
    setDialog({ kind: "rename-chat", item: chat });
  };
  const handleDeleteChat = async (chat: ChatSummary) => {
    setConfirm({ kind: "chat", item: chat });
  };
  const handlePinChat = async (chat: ChatSummary) => {
    const updated = await api.pinChat(chat.id);
    setRecentChats((items) => items.map((item) => item.id === chat.id ? { ...item, pinned_at: updated.pinned_at } : item));
  };
  const handleCreateSession = () => setDialog({ kind: "create-session" });
  const handleRenameSession = (session: DashboardSession) => setDialog({ kind: "rename-session", item: session });
  const handleDeleteSession = (session: DashboardSession) => setConfirm({ kind: "session", item: session });
  const submitDialog = async (name: string) => {
    if (!dialog) return;
    if (dialog.kind === "create-session") {
      const created = await api.createSession(name);
      setSessions((items) => [created as DashboardSession, ...items]);
      setDialog(null);
      router.push(`/app/s/${created.id}`);
      return;
    }
    if (dialog.kind === "rename-session") {
      const session = dialog.item as DashboardSession;
      const updated = await api.renameSession(session.id, name);
      setSessions((items) => items.map((item) => item.id === session.id ? { ...item, name: updated.name, updated_at: updated.updated_at } : item));
      if (session.id === initialSessionId) setSessionName(updated.name);
    } else {
      const chat = dialog.item as ChatSummary;
      const updated = await api.renameChat(chat.id, name);
      setRecentChats((items) => items.map((item) => item.id === chat.id ? { ...item, title: updated.title, updated_at: updated.updated_at } : item));
    }
    setDialog(null);
  };
  const confirmDelete = async () => {
    if (!confirm) return;
    if (confirm.kind === "chat") {
      const chat = confirm.item as ChatSummary;
      await api.deleteChat(chat.id);
      setRecentChats((items) => items.filter((item) => item.id !== chat.id));
      if (initialChatId === chat.id) router.push(`/app/s/${sessionId}`);
      setToast("Chat deleted");
    } else {
      const session = confirm.item as DashboardSession;
      await api.deleteSession(session.id);
      setSessions((items) => items.filter((item) => item.id !== session.id));
      if (session.id === initialSessionId) router.push("/app/dashboard");
      setToast("Session deleted");
    }
    setConfirm(null);
    window.setTimeout(() => setToast(null), 2200);
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

  const chatPanel = (
    <ChatPanel
      context={showStudio ? "studio" : "research"}
      uploadedFilename={uploadedFilename}
      onUploadComplete={handleUploadComplete}
      onNewPapers={handleNewPapers}
      onOpenPdf={handleOpenPdf}
      turns={showStudio ? studioTurns : turns}
      setTurns={showStudio ? setStudioTurns : setTurns}
      sessionId={sessionId}
      chatId={showStudio ? undefined : initialChatId}
      onOpenGraph={handleOpenGraph}
      onRegenerated={refreshLibrary}
      uploadState={uploadState}
      setUploadState={setUploadState}
      hasUpload={hasUpload}
      setHasUpload={setHasUpload}
      evidenceMode={evidenceMode}
      setEvidenceMode={setEvidenceMode}
      wide={!sidebarOpen && !railOpen}
    />
  );

  return (
    <div className="flex h-screen bg-paper overflow-hidden">
      <div
        className="relative z-30 shrink-0 h-full overflow-hidden transition-[width] duration-200 ease-out border-r border-line bg-paper-dim"
        style={{ width: sidebarOpen ? SIDEBAR_WIDTH : SIDEBAR_COLLAPSED_WIDTH }}
      >
        {sidebarOpen ? (
          <div className="flex h-full flex-col" style={{ width: SIDEBAR_WIDTH }}>
            <div className="flex h-16 items-center gap-2.5 px-4 shrink-0">
              <Link href="/" aria-label="Back to Sykra Research home" className="min-w-0 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo">
                <span className="block truncate font-serif text-[20px] font-medium text-ink">Sykra Research</span>
              </Link>
              <button
                onClick={() => setSidebarOpen(false)}
                aria-label="Collapse sidebar"
                className="ml-auto flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-soft hover:bg-paper hover:text-ink transition-colors"
              >
                <PanelLeft className="h-3.5 w-3.5" />
              </button>
            </div>

            {dashboard ? <div className="flex min-h-0 flex-1 flex-col px-3">
              <button onClick={handleCreateSession} className="flex w-full items-center gap-2 rounded-lg bg-[var(--selected)] border border-line px-3 py-2 text-caption font-medium text-ink hover:bg-[var(--hover)] transition-colors"><SquarePen className="h-3.5 w-3.5" />New Session</button>
              <p className="mt-6 px-1.5 pb-2 text-label text-ink-soft/70">SESSIONS</p>
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">{sessions.slice(0, 5).map((session) => <div key={session.id} className={`group/session flex items-center gap-1 rounded-md ${session.id === initialSessionId ? "app-sidebar-selected text-ink font-medium" : "text-ink-soft"}`}><button onClick={() => router.push(`/app/s/${session.id}`)} className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-2 text-left text-caption hover:text-ink"><span className="h-2 w-2 shrink-0 rounded-full bg-sage" /><span className="truncate">{session.name}</span></button><SessionMenu onRename={() => handleRenameSession(session)} onDelete={() => handleDeleteSession(session)} /></div>)}</div>
            </div> : <div className="flex min-h-0 flex-1 flex-col px-3">
              <Link href="/app/dashboard" className="mb-4 flex items-center gap-2 px-2 text-caption text-ink-soft hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" /> Dashboard</Link>
              <div className="flex items-center justify-between px-2"><div className="min-w-0"><p className="text-label text-ink-soft/70">SESSION</p><p className="truncate text-sm font-medium text-ink">{sessionName}</p></div><SessionMenu onRename={() => { const item = sessions.find((session) => session.id === initialSessionId); if (item) handleRenameSession(item); }} onDelete={() => { const item = sessions.find((session) => session.id === initialSessionId); if (item) handleDeleteSession(item); }} /></div>
              <div className="mt-4 space-y-1">
                <Link
                  href={`/app/s/${sessionId}/files`}
                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-caption transition-colors ${
                    showFiles
                      ? "app-sidebar-selected text-ink font-medium"
                      : "text-ink-soft hover:bg-paper hover:text-ink"
                  }`}
                >
                  <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                  Files
                </Link>
                <Link
                  href={`/app/s/${sessionId}/studio`}
                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-caption transition-colors ${
                    showStudio
                      ? "app-sidebar-selected text-ink font-medium"
                      : "text-ink-soft hover:bg-paper hover:text-ink"
                  }`}
                >
                  <Shapes className="h-3.5 w-3.5 shrink-0" />
                  Studio
                </Link>
                <Link
                  href={`/app/s/${sessionId}/report`}
                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-caption transition-colors ${
                    showReport
                      ? "app-sidebar-selected text-ink font-medium"
                      : "text-ink-soft hover:bg-paper hover:text-ink"
                  }`}
                >
                  <FileText className="h-3.5 w-3.5 shrink-0" />
                  Report
                </Link>
              </div>
              <div className="mt-4 border-t border-line pt-4">
                <button onClick={handleNewChat} className="flex w-full items-center gap-2 rounded-lg bg-[var(--selected)] border border-line px-3 py-2 text-caption font-medium text-ink hover:bg-[var(--hover)]"><SquarePen className="h-3.5 w-3.5" />New Chat</button>
                <p className="mt-5 px-1.5 pb-1.5 text-label text-ink-soft/70">CHATS</p>
                <div className="min-h-0 max-h-[40vh] flex-1 overflow-y-auto">{recentChats.length === 0 ? <p className="px-2 py-3 text-caption text-ink-soft">No chats yet</p> : <ChatHistory chats={recentChats} activeChatId={initialChatId} sessionId={sessionId} onRename={handleRenameChat} onDelete={handleDeleteChat} onPin={handlePinChat} />}</div>
              </div>
            </div>}

            <div className="mt-auto border-t border-line px-3 py-3 shrink-0">
              <button onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} className="mb-2 flex h-9 w-9 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
              </button>
              <div className="group relative">
              <button onClick={() => setUserMenuOpen((value) => !value)} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-paper">
                <Avatar name={currentUser?.name} email={currentUser?.email} className="h-7 w-7" />
                <div className="min-w-0 flex-1"><p className="truncate text-caption font-medium text-ink">{currentUser?.name || "Researcher"}</p><p className="truncate text-micro text-ink-soft">{currentUser?.email || "Signed in"}</p></div>
              </button>
              {userMenuOpen && <div className="absolute bottom-14 left-2 z-50 w-52 rounded-xl border border-line bg-white p-2 shadow-xl"><div className="mb-1 flex items-center gap-2 border-b border-line px-2 pb-2"><Avatar name={currentUser?.name} email={currentUser?.email} className="h-8 w-8" /><span className="min-w-0 truncate text-xs font-medium">{currentUser?.name || currentUser?.email}</span></div><Link href="/app/settings" className="block rounded-lg px-3 py-2 text-xs hover:bg-paper">Settings</Link><Link href="/" className="block rounded-lg px-3 py-2 text-xs hover:bg-paper">← Back to website</Link><button onClick={handleLogout} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-danger hover:bg-danger/5"><LogOut className="h-3.5 w-3.5" />Log out</button></div>}
              </div>
            </div>
          </div>
        ) : (
          <div
            className="flex h-full flex-col items-center gap-2 py-3"
            style={{ width: SIDEBAR_COLLAPSED_WIDTH }}
          >
            <div className="flex flex-col items-center gap-1">
              <Link href="/" aria-label="Back to Sykra Research home" title="Website" className="flex h-9 w-9 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink transition-colors">
                <Image src="/sykra-logo.svg" alt="Sykra Research" width={28} height={28} className="h-7 w-7 shrink-0 object-contain" />
              </Link>
              <button
                onClick={() => setSidebarOpen(true)}
                aria-label="Expand sidebar"
                title="Expand sidebar"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink transition-colors"
              >
                <PanelLeft className="h-4 w-4" />
              </button>
            </div>

            <div className="my-1 h-px w-6 bg-line" aria-hidden="true" />
            <button onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} className="flex h-9 w-9 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            {/* New Chat */}
            <button
              onClick={handleNewChat}
              aria-label="New chat"
              title="New chat"
              className="relative flex h-9 w-9 items-center justify-center rounded-lg text-ink-soft hover:bg-paper hover:text-ink transition-colors"
            >
              <SquarePen className="h-4 w-4" />
              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </button>

            <Link
              href={`/app/s/${sessionId}/files`}
              aria-label="Open files"
              title="Files"
              className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
                "text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              <FolderOpen className="h-4 w-4" />
              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </Link>

            {/* Studio */}
            <Link
              href={`/app/s/${sessionId}/studio`}
              aria-label="Open Studio"
              title="Studio"
              className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
                showStudio
                  ? "app-sidebar-selected text-ink"
                  : "text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {showStudio && (
                <span
                  className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-indigo"
                  aria-hidden="true"
                />
              )}
              <Shapes className="h-4 w-4" />
              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </Link>

            {/* Report */}
            <Link
              href={`/app/s/${sessionId}/report`}
              aria-label="Open Report"
              title="Report"
              className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
                showReport
                  ? "app-sidebar-selected text-ink"
                  : "text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {showReport && (
                <span
                  className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-indigo"
                  aria-hidden="true"
                />
              )}
              <FileText className="h-4 w-4" />
              <span
                className="absolute bottom-1.5 h-[2px] w-3.5 rounded-full bg-line/80"
                aria-hidden="true"
              />
            </Link>
          </div>
        )}
      </div>

      <div ref={containerRef} className="flex flex-1 min-h-0 min-w-0">
        <main className="flex-1 min-w-0">
          {dashboard ? <SessionDashboard sessions={sessions} chats={recentChats} userName={currentUser?.name} onOpen={(id) => router.push(`/app/s/${id}`)} onRename={handleRenameSession} onDelete={handleDeleteSession} onCreateSession={handleCreateSession} /> : showFiles ? (
            <FilesPage sessionId={sessionId} onOpenPdf={handleOpenPdf} />
          ) : showReport ? (
            <ReportView sessionId={sessionId} />
          ) : showStudio ? (
            <StudioView
              sessionId={sessionId}
              getConversationContext={getConversationContext}
              chatOpen={studioChatOpen}
              onToggleChat={() => setStudioChatOpen((open) => !open)}
            />
          ) : showGraphView ? (
            <div className="h-full flex flex-col">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <button
                  onClick={handleBackToChat}
                  className="flex items-center gap-2 text-body text-ink-soft hover:text-ink"
                >
                  <ArrowLeft className="h-4 w-4" /> Back to Chat
                </button>
                <span className="font-serif text-[15px] font-semibold text-ink">Knowledge graph · {recentChats.find((chat) => chat.id === initialChatId)?.title ?? "Chat"}</span>
                <span className="w-[90px]" />
              </div>
              <div className="flex-1 min-h-0 bg-paper">
                <GraphView sessionId={sessionId} chatId={initialChatId} activeTurnId={lastAssistantTurnId} messagePaperLinks={lastAssistantPaperLinks} />
              </div>
            </div>
          ) : (
            chatPanel
          )}
        </main>

        {!dashboard && showStudio && (
          <aside
            className={`relative shrink-0 h-full overflow-hidden transition-[width] duration-200 ease-out ${studioChatOpen ? "border-l border-line" : ""}`}
            style={{ width: studioChatOpen ? RAIL_WIDTH : 0 }}
            aria-label="Studio chat"
          >
            {studioChatOpen ? (
              <div className="h-full flex flex-col" style={{ width: RAIL_WIDTH }}>
                <div className="flex items-center justify-between border-b border-line px-3 py-2">
                  <span className="text-xs font-semibold text-ink">Diagram assistant</span>
                  <button
                    onClick={() => setStudioChatOpen(false)}
                    aria-label="Collapse studio chat"
                    className="rounded-md p-1 text-ink-soft hover:bg-paper hover:text-ink"
                  >
                    <PanelRight className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="min-h-0 flex-1">{chatPanel}</div>
              </div>
            ) : (
              <button
                onClick={() => setStudioChatOpen(true)}
                aria-label="Expand studio chat"
                className="m-2 flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-paper hover:text-ink"
              >
                <PanelRight className="h-3.5 w-3.5" />
              </button>
            )}
          </aside>
        )}

        {!dashboard && !showFiles && !pdfViewerUrl && !showStudio && !showReport && (
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
                    <PanelRight className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="flex-1 min-h-0">
                  <RightRail
                    papers={papers}
                    sessionId={sessionId}
                    chatId={initialChatId}
                    tab={tab}
                    setTab={setTab}
                    onOpenPdf={handleOpenPdf}
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
                  <PanelRight className="h-3.5 w-3.5" />
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
      <NameDialog open={dialog !== null} title={dialog?.kind === "create-session" ? "New session" : dialog?.kind === "rename-session" ? "Rename session" : "Rename chat"} initialValue={dialog?.item && "name" in dialog.item ? dialog.item.name : dialog?.item && "title" in dialog.item ? dialog.item.title : ""} onCancel={() => setDialog(null)} onSubmit={submitDialog} />
      <ConfirmDialog open={confirm !== null} title={confirm?.kind === "chat" ? "Delete chat?" : "Delete session?"} body={confirm?.kind === "chat" ? `This will permanently delete "${(confirm.item as ChatSummary).title}" and all its messages. This can't be undone.` : `This will permanently delete "${(confirm?.item as DashboardSession)?.name}" including ${(confirm?.item as DashboardSession)?.chat_count} ${(confirm?.item as DashboardSession)?.chat_count === 1 ? "chat" : "chats"} and ${(confirm?.item as DashboardSession)?.paper_count} ${(confirm?.item as DashboardSession)?.paper_count === 1 ? "paper" : "papers"}.`} onCancel={() => setConfirm(null)} onConfirm={confirmDelete} />
      {toast && <div role="status" className="fixed bottom-5 left-1/2 z-[110] -translate-x-1/2 rounded-full bg-forest px-4 py-2 text-sm font-medium text-white shadow-lg">{toast}</div>}
    </div>
  );
}

export function AppShell(props: { initialSessionId?: string; initialChatId?: string; dashboard?: boolean; initialGraphView?: boolean; initialFiles?: boolean; initialStudio?: boolean; initialReport?: boolean }) {
  return <ThemeProvider><AppShellInner {...props} /></ThemeProvider>;
}

export function SessionShell({ sessionId }: { sessionId: string }) {
  const pathname = usePathname();
  const rest = pathname.split("/").filter(Boolean).slice(3);
  const chatId = rest[0] === "chat" ? rest[1] : undefined;
  return (
    <AppShell
      initialSessionId={sessionId}
      initialChatId={chatId}
      initialGraphView={!!chatId && rest[2] === "graph"}
      initialFiles={rest[0] === "files"}
      initialStudio={rest[0] === "studio"}
      initialReport={rest[0] === "report"}
    />
  );
}