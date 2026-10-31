"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import katex from "katex";
import { useEditor, EditorContent, type Editor } from "@tiptap/react";
import { ArrowRight, ArrowUp, Download, Loader2, Paperclip, Plus, Square, X, History, Trash2, PanelRight, Check, FileText } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  EvidenceMode, ReportPrepareResponse, ReportRecord, ReportStreamEvent, RefineSection,
  ReportStructureDraft, ReportRunResult, StatusStep, ReportArtifact, ReportListItem, RefineStatus
} from "@/lib/types";
import { ReportPrepareModal, toConfirmed } from "@/components/ReportPrepareModal";
import dynamic from "next/dynamic";
import { UploadPreviewCard } from "@/components/UploadPreviewCard";
import { ResearchSteps } from "@/components/ResearchSteps";
import { ReportToolbar } from "@/components/report/ReportToolBar";
import { RichField } from "@/components/report/RichField";
import {
  bodyExtensions, DOCX_STYLE, editorMarkdown, escHtml, hasFormatting, headingHtml, loadHtml,
  styleParagraphs, type ActiveField,
} from "@/components/report/ReportFormat";
const PdfViewer = dynamic(
  () => import("@/components/PdfViewer").then((m) => m.PdfViewer),
  { ssr: false }
);

type SheetSection = { section_id: string; title: string; titleHtml?: string; markdown: string; html?: string; final: boolean };
type Attached = {
  id: string; name: string; kind: "data" | "guideline"; text?: string; url?: string;
  status: "uploading" | "processing" | "done" | "error"; progress?: string; sent?: boolean;
}; 
type Msg = { role: "user" | "assistant"; text: string; status?: "working" | RefineStatus; sections?: RefineSection[] };

const BRIEF_MAX_HEIGHT = 180;
const GUIDE_NAME_RE = /guideline|template|format|structure|instruction|outline/i;
const GUIDE_BODY_RE = /instruction|guideline|outline|template|must be|should be|format/gi;
const NUMERIC_RE = /^[-+\u2212\u2013(]?\s*\d[\d.,]*\)?$/;

function looksLikeGuideline(name: string, text: string) {
  if (GUIDE_NAME_RE.test(name)) return true;
  const head = text.slice(0, 4000);
  return (head.match(GUIDE_BODY_RE)?.length ?? 0) >= 4 && /chapter\s*\d|outline/i.test(head);
}
const dParts = (iso: string) => {
  const d = new Date(iso);
  return {
    md: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    y: d.getFullYear(),
    t: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
  };
};
const cleanMd = (md: string) => md.replace(/\[ev_[a-z]+_\d+\]\s?/gi, "");
const linkCitations = (md: string) =>
  cleanMd(md).replace(/<u>([\s\S]*?)<\/u>/g, "[$1](#rp-u)").replace(/\[(\d{1,3})\](?![(:])/g, "[[$1]](#rp-ref-$1)");
const stripU = (md: string) => md.replace(/<\/?u>/g, "");
const mdComponents: Components = {
  a({ href, children }) {
    if (href === "#rp-u") return <u>{children}</u>;
    if (href?.startsWith("#rp-ref-"))
      return <span className="cite"><a href={href} onClick={(e) => {
        e.preventDefault(); e.stopPropagation();
        document.getElementById(href.slice(1))?.scrollIntoView({ behavior: "smooth", block: "center" });
      }}>{children}</a></span>;
    return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
  },
};

const unesc = (t: string) => t.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const texHtml = (x: string, display: boolean) => {
  try { return katex.renderToString(unesc(x), { displayMode: display, throwOnError: false }); }
  catch { return escHtml(unesc(x)); }
};

const renderStored = (html: string) =>
  cleanMd(html).replace(/>([^<]+)</g, (_m, txt: string) =>
    ">" + txt.replace(/$$([\s\S]+?)$$|$([^$\n]+?)$|\[(\d{1,3})\]/g,
      (_x, d: string | undefined, i: string | undefined, n: string | undefined) =>
        d != null ? texHtml(d, true) : i != null ? texHtml(i, false)
        : `<span class="cite"><a href="#rp-ref-${n}">[${n}]</a></span>`) + "<");

function SectionEditor({ initial, initialHtml, onSave, onCancel, onActivate, onRelease }: {
  initial: string; initialHtml?: string; onSave: (md: string, html: string) => void; onCancel: () => void;
  onActivate: (a: ActiveField) => void; onRelease: (e: Editor) => void;
}) {
  const editor = useEditor({
    immediatelyRender: false, autofocus: "end",
    content: initialHtml ? "" : initial,
    extensions: bodyExtensions(),
    onCreate: ({ editor: ed }) => { if (initialHtml) { loadHtml(ed, initialHtml); ed.commands.focus("end"); } },
  });
  useEffect(() => {
    if (!editor) return;
    onActivate({ editor, kind: "body" });
    return () => onRelease(editor);
  }, [editor]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = () => { if (editor) onSave(editorMarkdown(editor), editor.getHTML()); };
  return (
    <div onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) save(); }}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}
      className="rounded-sm outline outline-1 outline-indigo/40">
      <EditorContent editor={editor} />
    </div>
  );
}

export function ReportView({ sessionId }: { sessionId: string }) {
  const [started, setStarted] = useState(false);
  const [page, setPage] = useState<"new" | "history">("new");
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<Attached[]>([]);
  const [pdf, setPdf] = useState<{ url: string; name: string } | null>(null);
  const [pdfW, setPdfW] = useState(() => {
    const v = typeof window !== "undefined" ? Number(localStorage.getItem("sykra.report.pdfW")) : 0;
    return v >= 320 ? v : 560;
  });
  const [dragging, setDragging] = useState(false);
  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const x0 = e.clientX, w0 = pdfW;
    setDragging(true);
    const move = (ev: PointerEvent) =>
      setPdfW(Math.max(320, Math.min(window.innerWidth * 0.7, w0 - (ev.clientX - x0))));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDragging(false);
      setPdfW((w) => { localStorage.setItem("sykra.report.pdfW", String(Math.round(w))); return w; });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const [hasUpload, setHasUpload] = useState(false);
  const [busyUpload, setBusyUpload] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [running, setRunning] = useState(false);
  const [refining, setRefining] = useState(false);
  const [prepareData, setPrepareData] = useState<ReportPrepareResponse | null>(null);
  const [pending, setPending] = useState<{ structure: ReportStructureDraft; path?: string } | null>(null);
  const [draft, setDraft] = useState<ReportStructureDraft | null>(null);
  const [steps, setSteps] = useState<StatusStep[]>([]);
  const [sheet, setSheet] = useState<SheetSection[]>([]);
  const [title, setTitle] = useState("");
  const [titleHtml, setTitleHtml] = useState("");
  const [result, setResult] = useState<ReportRunResult | null>(null);
  const [meta, setMeta] = useState<{ chatId: string; messageId: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chat, setChat] = useState<Msg[]>([]);
  const [filename, setFilename] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [active, setActive] = useState<ActiveField | null>(null);
  const [, redraw] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const refineFileRef = useRef<HTMLInputElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ed = active?.editor;
    if (!ed) return;
    const h = () => redraw((n) => n + 1);
    ed.on("transaction", h);
    return () => { ed.off("transaction", h); };
  }, [active]);
  const activate = useCallback((a: ActiveField) => setActive(a), []);
  const release = useCallback((ed: Editor) => setActive((a) => (a?.editor === ed ? null : a)), []);

  const evidenceMode: EvidenceMode = hasUpload ? "blended" : "literature";
  const dataText = files.filter((f) => f.kind === "data" && f.text).map((f) => f.text).join("\n\n");
  const guidelineText = files.filter((f) => f.kind === "guideline" && f.text).map((f) => f.text).join("\n\n");

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, BRIEF_MAX_HEIGHT) + "px";
  }, [query, started, page]);

  const refreshReports = useCallback(() => {
    api.reportList(sessionId).then(setReports).catch(() => setReports([]));
  }, [sessionId]);

  useEffect(() => { refreshReports(); }, [refreshReports]);

  const patchFile = (id: string, patch: Partial<Attached>) =>
    setFiles((p) => p.map((f) => (f.id === id ? { ...f, ...patch } : f)));

  async function addFiles(list: FileList | null) {
    if (!list) return;
    for (const f of Array.from(list)) {
      const id = crypto.randomUUID();
      const isPdf = f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
      if (!isPdf) {
        const text = await f.text();
        setFiles((p) => [...p, { id, name: f.name, kind: GUIDE_NAME_RE.test(f.name) ? "guideline" : "data", text, status: "done", progress: "Ready" }]);
        continue;
      }
      const url = URL.createObjectURL(f);
      setFiles((p) => [...p, { id, name: f.name, kind: "data", url, status: "uploading", progress: "Reading file..." }]);
      setBusyUpload(true);
      try {
        const { text } = await api.reportGuidelineText(f).catch(() => ({ text: "" }));
        if (text && looksLikeGuideline(f.name, text)) {
          patchFile(id, { kind: "guideline", text, status: "done", progress: "Ready" });
          continue;
        }
        await api.uploadPdfStream(f, sessionId, (ev) => {
          if (ev.type === "progress") patchFile(id, { status: "processing", progress: ev.label });
          if (ev.type === "result") { setHasUpload(true); patchFile(id, { status: "done", progress: "Ready" }); }
          if (ev.type === "error") { setError(ev.message); patchFile(id, { status: "error" }); }
        }, undefined, crypto.randomUUID(), undefined);
      } catch { patchFile(id, { status: "error" }); setError("Upload failed."); } finally { setBusyUpload(false); }
    }
  }
  const removeFile = (id: string) => setFiles((p) => {
    const f = p.find((x) => x.id === id);
    if (f?.url) { URL.revokeObjectURL(f.url); setPdf((v) => (v?.url === f.url ? null : v)); }
    return p.filter((x) => x.id !== id);
  });
  const toggleKind = (id: string) => setFiles((p) => p.map((f) =>
    f.id === id && f.text ? { ...f, kind: f.kind === "data" ? "guideline" : "data" } : f));

  const fileCards = (cls: string, pendingOnly = false) => {
    const list = pendingOnly ? files.filter((f) => !f.sent) : files;
    return list.length > 0 && (
    <div className={cls}>
      {list.map((f) => (
        <div key={f.id} className="flex items-center gap-1.5">
          <div className="min-w-0 flex-1">
            <UploadPreviewCard
              filename={f.name}
              status={f.status}
              progress={f.progress}
              fileUrl={f.url}
              onOpen={() => f.url && setPdf({ url: f.url, name: f.name })}
              onCancel={() => removeFile(f.id)}
              onClose={() => removeFile(f.id)}
            />
          </div>
          {f.text && (
            <button onClick={() => toggleKind(f.id)} title="Click to switch"
              className="shrink-0 rounded-md border border-line bg-paper px-1.5 py-0.5 text-micro text-ink-soft hover:text-indigo">{f.kind}</button>
          )}
        </div>
      ))}
    </div>
    );
  };

  const startRun = useCallback(async (d: ReportStructureDraft, records: ReportRecord[], path?: string) => {
    setError(null); setRunning(true); setStarted(true);
    setSheet([]); setSteps([]); setResult(null); setFilename(null); setTitleHtml("");
    const controller = new AbortController(); abortRef.current = controller;
    const requestId = crypto.randomUUID(); requestIdRef.current = requestId;
    try {
      await api.reportRunStream({
        query, session_id: sessionId, request_id: requestId, evidence_mode: evidenceMode,
        execution_path: path ?? null, title: title || undefined, guideline_text: guidelineText || null,
        analysis: d.analysis, sections: d.sections,
        confirmed_source_records: records.length ? records : null,
      }, (ev: ReportStreamEvent) => {
        if (ev.type === "progress") setSteps((s) => [...s, { stage: ev.stage ?? "default", label: ev.label, detail: ev.detail, items: ev.items }]);
        else if (ev.type === "report_section") {
          setSheet((prev) => {
            const i = prev.findIndex((s) => s.section_id === ev.section_id);
            const next = { section_id: ev.section_id, title: ev.title ?? prev[i]?.title ?? ev.section_id, markdown: ev.markdown, final: ev.final };
            if (i === -1) return [...prev, next];
            const copy = [...prev]; copy[i] = { ...copy[i], ...next, title: next.title || copy[i].title }; return copy;
          });
        } else if (ev.type === "result" && "sections" in ev.payload) {
          const r = ev.payload as ReportRunResult;
          setResult(r); setTitle(r.title); setMeta({ chatId: r.chat_id, messageId: r.message_id });
          setFiles((p) => p.map((f) => ({ ...f, sent: true })));
          setTitleHtml(r.title_html ?? "");
          setSheet(r.sections.map((s) => ({ section_id: s.section_id, title: s.title, titleHtml: s.title_html ?? undefined, markdown: s.content, html: s.html ?? undefined, final: true })));
        } else if (ev.type === "filename") setFilename(ev.filename);
        else if (ev.type === "error") setError(ev.message);
      }, controller.signal);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 0)) setError(e instanceof ApiError ? e.message : "Report generation failed.");
    } finally { setRunning(false); abortRef.current = null; requestIdRef.current = null; refreshReports(); }
  }, [query, sessionId, evidenceMode, title, guidelineText, refreshReports]);

  async function handleGenerate() {
    setError(null); setPlanning(true);
    const c = new AbortController(); abortRef.current = c;
    try {
      const combined = dataText ? `${query}\n\n${dataText}` : query;
      const wantPrep = hasUpload || !!dataText || (query.match(/\d+/g)?.length ?? 0) >= 4;
      const [structure, prep] = await Promise.all([
        api.reportStructure({ query, session_id: sessionId, evidence_mode: evidenceMode, guideline_text: guidelineText || null }, c.signal),
        wantPrep ? api.reportPrepare({ query: combined, session_id: sessionId, evidence_mode: evidenceMode }, c.signal) : Promise.resolve(null),
      ]);
      setDraft(structure);
      const records = prep?.records ?? [];
      const needsReview = records.some((r) => !NUMERIC_RE.test(r.value_raw.trim()));
      if (prep && needsReview) { setPending({ structure, path: prep.suggested_execution_path }); setPrepareData(prep); }
      else void startRun(structure, records.map(toConfirmed), prep?.suggested_execution_path);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the report.");
    } finally { setPlanning(false); if (abortRef.current === c) abortRef.current = null; }
  }

  function handlePrepareConfirm(_t: string, records: ReportRecord[]) {
    const p = pending; setPrepareData(null); setPending(null);
    if (p) void startRun(p.structure, records, p.path);
  }

  function resetDoc() {
    files.forEach((f) => f.url && URL.revokeObjectURL(f.url)); setPdf(null);
    setStarted(false); setSheet([]); setResult(null); setChat([]); setFiles([]);
    setHasUpload(false); setTitle(""); setTitleHtml(""); setMeta(null); setEditing(null); setSteps([]);
    setConfirmDeleteId(null); setError(null);
  }
  const goNew = () => { resetDoc(); setPage("new"); };
  const goHistory = () => {
    if (running || refining) return;
    resetDoc(); setPage("history"); refreshReports();
  };

  async function openReport(item: ReportListItem) {
    if (running || refining) return;
    setError(null); setEditing(null);
    try {
      const latest = await api.reportGet(sessionId, item.message_id);
      const a: ReportArtifact = latest.artifact;
      setTitle(a.title); setTitleHtml(a.title_html ?? "");
      setSheet(a.sections.map((s) => ({ section_id: s.section_id, title: s.title, titleHtml: s.title_html ?? undefined, markdown: s.content, html: s.html ?? undefined, final: true })));
      setResult({
        turn_id: "", chat_id: latest.chat_id, message_id: latest.message_id, title: a.title, title_html: a.title_html ?? null,
        answer: "", references: a.references, sections: a.sections, papers: [],
      });
      setMeta({ chatId: latest.chat_id, messageId: latest.message_id });
      setSteps(latest.status_steps ?? []); setChat(chatFromLog(a.refine_log)); setFilename(null);
      setStarted(true);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not open the report."); }
  }

  async function deleteReport(item: ReportListItem) {
    setConfirmDeleteId(null);
    try {
      await api.reportDelete(sessionId, item.chat_id);
      setReports((p) => p.filter((r) => r.message_id !== item.message_id));
      if (meta?.messageId === item.message_id) {
        setStarted(false); setSheet([]); setResult(null); setMeta(null);
        setChat([]); setTitle(""); setTitleHtml(""); setEditing(null);
      }
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not delete the report."); }
  }
  const [railCollapsed, setRailCollapsed] = useState(() =>
    typeof window !== "undefined" && localStorage.getItem("sykra.report.rail") === "collapsed");
  useEffect(() => {
    localStorage.setItem("sykra.report.rail", railCollapsed ? "collapsed" : "expanded");
  }, [railCollapsed]);

  const refineRef = useRef<HTMLTextAreaElement>(null);
  const expandForRefine = () => {
    setRailCollapsed(false);
    setTimeout(() => refineRef.current?.focus(), 60);
  };

  const exportMenu = (pos: string) => menu && (
    <div className={`absolute z-10 w-32 rounded-lg border border-line bg-paper py-1 text-caption shadow-lg ${pos}`}>
      {(["pdf", "docx", "md"] as const).map((k) => (
        <button key={k} onClick={() => exportAs(k)} className="block w-full px-3 py-1.5 text-left hover:bg-paper-dim">
          {k === "md" ? "Markdown" : k.toUpperCase()}
        </button>
      ))}
    </div>
  );
  function handleStop() {
    if (requestIdRef.current) api.cancelStream(requestIdRef.current).catch(() => {});
    abortRef.current?.abort();
  }

  async function saveSection(id: string, md: string, rawHtml: string) {
    setEditing(null);
    const cur = sheet.find((s) => s.section_id === id);
    const html = hasFormatting(rawHtml) ? rawHtml : "";
    if (!meta || !cur || (cur.markdown === md && (cur.html ?? "") === html)) return;
    try {
      await api.reportPatchSections({ chat_id: meta.chatId, message_id: meta.messageId, sections: [{ section_id: id, content: md, html }] });
      setSheet((p) => p.map((s) => s.section_id === id ? { ...s, markdown: md, html: html || undefined } : s));
      setResult((r) => r ? { ...r, sections: r.sections.map((s) => s.section_id === id ? { ...s, content: md, html: html || null } : s) } : r);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not save the edit."); }
  }

  async function saveTitle(t: string, h: string) {
    setTitle(t); setTitleHtml(h);
    setResult((r) => (r ? { ...r, title: t, title_html: h || null } : r));
    if (!meta) return;
    try { await api.reportPatchSections({ chat_id: meta.chatId, message_id: meta.messageId, sections: [], title: t, title_html: h }); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not save the title."); }
  }
  async function saveSectionTitle(id: string, t: string, h: string) {
    setSheet((p) => p.map((s) => (s.section_id === id ? { ...s, title: t, titleHtml: h || undefined } : s)));
    setResult((r) => (r ? { ...r, sections: r.sections.map((s) => (s.section_id === id ? { ...s, title: t, title_html: h || null } : s)) } : r));
    if (!meta) return;
    try { await api.reportPatchSections({ chat_id: meta.chatId, message_id: meta.messageId, sections: [{ section_id: id, title: t, title_html: h }] }); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not save the heading."); }
  }

  const chatFromLog = (log: ReportArtifact["refine_log"]): Msg[] =>
    (log ?? []).flatMap((t) => [
      { role: "user" as const, text: t.instruction },
      { role: "assistant" as const, text: t.summary, status: t.status, sections: t.changed },
    ]);

  const [flashIds, setFlashIds] = useState<string[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [chat]);
  const jumpToSection = (id: string) => {
    document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlashIds((f) => [...f, id]);
    setTimeout(() => setFlashIds((f) => f.filter((x) => x !== id)), 2200);
  };
  async function handleRefine() {
    const pending = files.filter((f) => !f.sent && f.status === "done");
    const instruction = chatInput.trim() || (pending.length ? "Use the attached file(s) to improve the report." : "");
    if (!instruction || !meta || refining || running || busyUpload) return;
    const newData = pending.filter((f) => f.kind === "data" && f.text).map((f) => f.text).join("\n\n");
    const newGuide = pending.filter((f) => f.kind === "guideline" && f.text).map((f) => f.text).join("\n\n");
    const hasUp = pending.some((f) => f.kind === "data" && f.url);
    setChatInput(""); setRefining(true);
    setFiles((p) => p.map((f) => (pending.some((x) => x.id === f.id) ? { ...f, sent: true } : f)));
    setChat((l) => [...l, { role: "user", text: instruction + (pending.length ? `\n[+ ${pending.map((f) => f.name).join(", ")}]` : "") },
      { role: "assistant", text: "Understanding your request…", status: "working" }]);
    const settle = (patch: Partial<Msg>) =>
      setChat((l) => { const c = [...l]; c[c.length - 1] = { ...c[c.length - 1], ...patch }; return c; });
    const c = new AbortController(); abortRef.current = c;
    try {
      await api.reportRefineStream({ chat_id: meta.chatId, message_id: meta.messageId, instruction, request_id: crypto.randomUUID(),
          guideline_text: newGuide || null, data_text: newData || null, has_upload: hasUp },
        (ev: ReportStreamEvent) => {
          if (ev.type === "progress") settle({ text: ev.label });
          else if (ev.type === "refine_plan") settle({ sections: ev.sections });
          else if (ev.type === "report_section" && ev.final) {
            setSheet((p) => p.some((s) => s.section_id === ev.section_id)
              ? p.map((s) => s.section_id === ev.section_id ? { ...s, markdown: ev.markdown, html: undefined, final: true } : s)
              : [...p, { section_id: ev.section_id, title: ev.title ?? ev.section_id, markdown: ev.markdown, final: true }]);
            setResult((r) => r ? { ...r, sections: r.sections.some((s) => s.section_id === ev.section_id)
              ? r.sections.map((s) => s.section_id === ev.section_id ? { ...s, content: ev.markdown, html: null } : s)
              : [...r.sections, { section_id: ev.section_id, title: ev.title ?? ev.section_id, content: ev.markdown }] } : r);
            jumpToSection(ev.section_id);
          } else if (ev.type === "report_structure") {
            const order = new Map(ev.sections.map((s, i) => [s.section_id, i] as const));
            const arrange = <T extends { section_id: string }>(a: T[]) =>
              a.filter((s) => order.has(s.section_id)).sort((x, y) => order.get(x.section_id)! - order.get(y.section_id)!);
            setSheet(arrange);
            setResult((r) => r ? { ...r, sections: arrange(r.sections) } : r);
          } else if (ev.type === "refine_done") settle({ text: ev.summary, status: ev.status, sections: ev.changed });
          else if (ev.type === "error") settle({ text: ev.message, status: "failed" });
        }, c.signal);
    } catch (e) {
      const m = e instanceof ApiError ? e.message : "Refinement failed.";
      settle({ text: m, status: "failed" }); setError(m);
    } finally {
      setChat((l) => l.at(-1)?.status === "working"
        ? [...l.slice(0, -1), { ...l[l.length - 1], text: "Connection ended before finishing. Reload to check the report.", status: "failed" }]
        : l);
      setRefining(false); abortRef.current = null;
    }
  }

  const refText = (r: ReportRunResult["references"][number]) => {
    const au = r.authors?.length ? r.authors.slice(0, 3).join(", ") + (r.authors.length > 3 ? " et al." : "") : "";
    const yr = r.published ? ` (${String(r.published).slice(0, 4)})` : "";
    return { head: `[${r.id}] ${au}${yr}${au || yr ? ". " : ""}${r.title}.`, link: r.link };
  };
  const buildMarkdown = () =>
    `# ${title}\n\n` + sheet.map((s) => `## ${s.title}\n\n${cleanMd(s.markdown)}`).join("\n\n") +
    (result?.references.length ? `\n\n## References\n\n` + result.references.map((r) => { const t = refText(r); return `${t.head} ${t.link}  `; }).join("\n") : "");
  const download = (blob: Blob, name: string) => {
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };
  async function exportAs(kind: "pdf" | "docx" | "md") {
    setMenu(false);
    if (!result) return;
    const base = filename ?? title ?? "report";
    if (kind === "md") return download(new Blob([buildMarkdown()], { type: "text/markdown" }), `${base}.md`);
    if (kind === "pdf") {
      const answer = `# ${title}\n\n` + sheet.map((s) => `## ${s.title}\n\n${stripU(cleanMd(s.markdown))}`).join("\n\n");
      return download(await api.exportPdf({
        session_id: sessionId, format: "standard", answer, references: result.references, title,
        title_html: titleHtml || null,
        sections: sheet.map((s) => ({
          title: s.title, title_html: s.titleHtml ?? null,
          html: s.html ? cleanMd(s.html) : null, markdown: stripU(cleanMd(s.markdown)),
        })),
      }), `${base}.pdf`);
    }
    const { default: HTMLtoDOCX } = await import("html-to-docx");
    const { marked } = await import("marked");
    const brk = '<div style="page-break-after: always"></div>';
    const parts: string[] = [headingHtml("h1", title, titleHtml || undefined, DOCX_STYLE.title)];
    for (let i = 0; i < sheet.length; i++) {
      const s = sheet[i];
      if (i > 0) parts.push(brk);
      const raw = s.html ? cleanMd(s.html) : await marked.parse(cleanMd(s.markdown));
      const inner = styleParagraphs(raw, DOCX_STYLE.body)
        .replace(/<h([1-6])(\s[^>]*)?>/g, (_m: string, n: string) => `<h${n} style="font-family:'Times New Roman';font-weight:bold;font-size:${n === "1" ? 16 : n === "2" ? 14 : 12}pt">`);
      parts.push(headingHtml("h2", s.title, s.titleHtml, DOCX_STYLE.heading) + `<div>${inner}</div>`);
    }
    if (result.references.length) {
      parts.push(brk, `<h2 style="${DOCX_STYLE.heading}">References</h2>`,
        ...result.references.map((r) => { const t = refText(r); return `<p style="${DOCX_STYLE.body}">${escHtml(t.head)} <a href="${t.link}">${escHtml(t.link)}</a></p>`; }));
    }
    const blob = await HTMLtoDOCX(`<div>${parts.join("")}</div>`, null, {
      font: "Times New Roman", fontSize: 24,
      margins: { left: 2160, right: 1800, top: 1440, bottom: 1440 },
    });
    download(blob as Blob, `${base}.docx`);
  }

  const pendingSections = useMemo(
    () => (draft?.sections ?? []).filter((p) => !sheet.some((s) => s.section_id === p.section_id)),
    [draft, sheet]);

  if (!started && page === "history") return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[820px] px-6 py-12">
        <div className="mb-14 flex items-end justify-between">
          <div>
            <p className="text-micro font-semibold uppercase tracking-widest text-ink-soft/70">This session</p>
            <h1 className="font-serif text-[26px] font-semibold leading-tight text-ink">Report history</h1>
          </div>
          <button onClick={goNew}
            className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-caption text-ink hover:bg-paper-dim">
            <Plus className="h-4 w-4" /> New report
          </button>
        </div>

        {error && <div className="mb-6 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-caption text-danger">{error}</div>}

        {reports.length === 0 ? (
          <p className="text-caption text-ink-soft">No reports yet. Create your first one.</p>
        ) : (
          <ol className="relative">
            <span aria-hidden className="absolute bottom-0 left-8 top-0 w-px bg-line" />
            {reports.map((r) => {
              const d = dParts(r.updated_at);
              return (
                <li key={r.message_id} className="group relative flex gap-8 pb-10 last:pb-0">
                  <div className="relative z-10 w-16 shrink-0 self-start bg-paper pb-1 pt-0.5 text-center leading-tight">
                    <div className="text-[11px] font-bold uppercase text-ink">{d.md}</div>
                    <div className="text-micro text-ink-soft">{d.y}</div>
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-4">
                      <button onClick={() => openReport(r)} className="min-w-0 flex-1 text-left">
                        <h2 className="line-clamp-2 font-serif text-[19px] font-semibold uppercase leading-snug tracking-tight text-ink transition-colors group-hover:text-indigo">
                          {r.title}
                        </h2>
                      </button>

                      <div className="flex h-7 shrink-0 items-center gap-1.5">
                        {confirmDeleteId === r.message_id ? (
                          <>
                            <button onClick={() => deleteReport(r)} className="rounded-md bg-danger px-2 py-1 text-micro text-white">Delete</button>
                            <button onClick={() => setConfirmDeleteId(null)} className="rounded-md px-2 py-1 text-micro text-ink-soft hover:bg-paper-dim">Cancel</button>
                          </>
                        ) : (
                          <button aria-label="Delete report" onClick={() => setConfirmDeleteId(r.message_id)}
                            className="rounded-md p-1.5 text-ink-soft opacity-0 transition hover:bg-danger/10 hover:text-danger focus-visible:opacity-100 group-hover:opacity-100">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="mt-1 flex items-center gap-2 text-micro text-ink-soft">
                      <span>{d.t}</span>
                      <span aria-hidden>·</span>
                      <button onClick={() => openReport(r)} className="flex items-center gap-1 hover:text-indigo">
                        Open <ArrowRight className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );

  const pdfPane = pdf && (
    <>
      <div onPointerDown={startResize} role="separator" aria-orientation="vertical" aria-label="Resize PDF"
        className="group relative z-10 w-1.5 shrink-0 cursor-col-resize touch-none bg-line/60 transition-colors hover:bg-indigo/30">
        <span className="absolute left-1/2 top-1/2 h-10 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink-soft/40 group-hover:bg-indigo/60" />
      </div>
      <div style={{ width: pdfW }} className="relative h-full min-w-[320px] max-w-[70vw] shrink-0">
        {dragging && <div className="absolute inset-0 z-20" />}
        <PdfViewer key={pdf.url} url={pdf.url} name={pdf.name} onClose={() => setPdf(null)} />
      </div>
    </>
  );

  if (!started) return (
    <div className="flex h-full bg-paper">
    <div className="relative flex min-w-0 flex-1 items-center justify-center px-6">
      <button onClick={goHistory}
        className="absolute right-5 top-4 flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-caption text-ink-soft hover:bg-paper-dim hover:text-ink">
        <History className="h-4 w-4" /> History
        {reports.length > 0 && <span className="text-micro">({reports.length})</span>}
      </button>

      <div className="w-full max-w-[680px]">
        <h1 className="mb-5 text-center font-serif text-[26px] font-semibold text-ink">What should the report cover?</h1>

        {fileCards("mb-2 flex flex-col gap-1.5")}
        <div className="rounded-2xl border border-line bg-paper-dim/50 px-3 py-2 focus-within:border-indigo/50">
          <div className="flex items-end gap-2">
            <button onClick={() => fileRef.current?.click()} disabled={busyUpload} aria-label="Attach files"
              className="mb-0.5 shrink-0 rounded-lg p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-50">
              {busyUpload ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
            </button>
            <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.md,.csv" className="hidden"
              onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />

            <textarea
              ref={taRef}
              value={query}
              rows={1}
              autoFocus
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && query.trim() && !planning) handleGenerate(); }}
              placeholder="Describe the report. Paste figures here or attach your dataset…"
              className="max-h-[180px] min-h-[28px] flex-1 resize-none overflow-y-auto bg-transparent py-1 text-[14.5px] text-ink placeholder:text-ink-soft/60 focus:outline-none"
            />

            <button onClick={handleGenerate} disabled={!query.trim() || planning || busyUpload} aria-label="Generate report"
              className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-white disabled:opacity-30">
              {planning ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <p className="mt-3 text-center text-caption text-ink-soft">
          Tip: attach your dataset, plus a guideline or university template if you have one. Listing the exact
          headings you want gives a closer match to your required structure.
        </p>
        {error && <div className="mt-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-caption text-danger">{error}</div>}
      </div>
      {prepareData && <ReportPrepareModal data={prepareData} onConfirm={handlePrepareConfirm} onCancel={() => { setPrepareData(null); setPending(null); }} />}
    </div>
    {pdfPane}
    </div>
  );

  return (
    <div className="flex h-full min-h-0 bg-paper">
      <div className="flex min-w-0 flex-1 flex-col">
      <ReportToolbar active={active} />
      <div className="min-h-0 flex-1 overflow-y-auto bg-paper-dim/40 py-8">
        <div className="rp-sheet">
          <RichField kind="title" text={title || "Report"} html={titleHtml || undefined} disabled={running || !result}
            onCommit={saveTitle} onActivate={activate} onRelease={release} />
          {sheet.map((s) => (
            <section key={s.section_id} id={`sec-${s.section_id}`}
              className={`transition-colors duration-700 ${flashIds.includes(s.section_id) ? "rounded-sm bg-indigo/10 outline outline-2 outline-indigo/30" : ""}`}>
              <RichField kind="heading" text={s.title} html={s.titleHtml} disabled={running || !s.final}
                onCommit={(t, h) => saveSectionTitle(s.section_id, t, h)} onActivate={activate} onRelease={release} />
              {editing === s.section_id ? (
                <SectionEditor initial={s.markdown} initialHtml={s.html}
                  onSave={(md, html) => saveSection(s.section_id, md, html)} onCancel={() => setEditing(null)}
                  onActivate={activate} onRelease={release} />
              ) : (
                <div onClick={(e) => {
                  const a = (e.target as HTMLElement).closest("a");
                  if (a) {
                    const h = a.getAttribute("href") ?? "";
                    if (h.startsWith("#rp-ref-")) { e.preventDefault(); document.getElementById(h.slice(1))?.scrollIntoView({ behavior: "smooth", block: "center" }); }
                    return;
                  }
                  if (!running && s.final) setEditing(s.section_id);
                }}
                  className={!running && s.final ? "cursor-text" : ""}>
                  {s.html ? (
                    <div dangerouslySetInnerHTML={{ __html: renderStored(s.html) }} />
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { throwOnError: false }]]} components={mdComponents}>
                      {linkCitations(s.markdown)}
                    </ReactMarkdown>
                  )}
                  {!s.final && <span className="inline-block h-[1em] w-[2px] animate-pulse bg-indigo/70" />}
                </div>
              )}
            </section>
          ))}
          {running && pendingSections.map((p) => (
            <section key={p.section_id} className="opacity-40"><h2>{p.title}</h2></section>
          ))}
          {result && result.references.length > 0 && (
            <section>
              <h2>References</h2>
              {result.references.map((r) => {
                const t = refText(r);
                return (
                  <p key={r.id} id={`rp-ref-${r.id}`} className="rp-ref">
                    {t.head} <a href={r.link} target="_blank" rel="noopener noreferrer">{r.link}</a>
                  </p>
                );
              })}
            </section>
          )}
        </div>
      </div>
      </div>

      {pdfPane}

      <div className={`flex shrink-0 flex-col border-l border-line bg-paper transition-[width] duration-200 ${railCollapsed ? "w-12" : "w-[340px]"}`}>
        {railCollapsed ? (
          <>
            <div className="flex shrink-0 flex-col items-center gap-1 border-b border-line py-2">
              <button onClick={() => setRailCollapsed(false)} aria-label="Expand panel" title="Expand panel"
                className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink">
                <PanelRight className="h-4 w-4" />
              </button>
              <span aria-hidden className="my-1 h-px w-5 bg-line" />
              <button onClick={goNew} aria-label="New report" title="New report"
                className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink">
                <Plus className="h-4 w-4" />
              </button>
              <button onClick={goHistory} disabled={running || refining} aria-label="Report history" title="History"
                className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-40">
                <History className="h-4 w-4" />
              </button>
              <div className="relative">
                {running ? (
                  <button onClick={handleStop} aria-label="Stop" title="Stop"
                    className="rounded-md bg-danger p-1.5 text-white"><Square className="h-3 w-3 fill-current" /></button>
                ) : (
                  <button onClick={() => setMenu((m) => !m)} disabled={!result} aria-label="Export" title="Export"
                    className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-40">
                    <Download className="h-4 w-4" />
                  </button>
                )}
                {exportMenu("right-full top-0 mr-2")}
              </div>
            </div>
            <div className="flex-1" />
            <div className="flex shrink-0 justify-center border-t border-line p-1.5">
              <button onClick={expandForRefine} disabled={running || !result}
                aria-label="Refine report" title="Tell Sykra what to change"
                className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-40">
                <Plus className="h-4 w-4" />
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="shrink-0 border-b border-line">
              <div className="flex items-center px-3 pt-2">
                <button onClick={() => setRailCollapsed(true)} aria-label="Collapse panel" title="Collapse panel"
                  className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink">
                  <PanelRight className="h-4 w-4" />
                </button>
              </div>
              <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
                <button onClick={goNew}
                  className="flex items-center gap-1.5 rounded-md px-2 py-1 text-caption text-ink-soft hover:bg-paper-dim hover:text-ink">
                  <Plus className="h-4 w-4" /> New report
                </button>
                <button onClick={goHistory} disabled={running || refining} aria-label="Report history"
                  className="flex items-center gap-1 rounded-md px-2 py-1 text-caption text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-40">
                  <History className="h-4 w-4" /> History
                </button>
                <div className="relative">
                  {running ? (
                    <button onClick={handleStop} aria-label="Stop" className="rounded-md bg-danger p-1.5 text-white"><Square className="h-3 w-3 fill-current" /></button>
                  ) : (
                    <button onClick={() => setMenu((m) => !m)} disabled={!result}
                      className="flex items-center gap-1 rounded-md px-2 py-1 text-caption text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-40">
                      <Download className="h-4 w-4" /> Export
                    </button>
                  )}
                  {exportMenu("right-0 top-full mt-1")}
                </div>
              </div>
            </div>
            <div className="flex-1 min-h-0 space-y-3 overflow-y-auto px-4 py-3">
              {steps.length > 0 && (
                <ResearchSteps key={running ? "run" : "done"} embedded steps={steps} streaming={running} />
              )}
              {!running && result && chat.length === 0 && (
                <p className="text-caption text-ink-soft">Click any section to edit it, or tell Sykra what to change.</p>
              )}
              {chat.map((m, i) => m.role === "user" ? (
                <div key={i} className="ml-auto w-fit max-w-[90%] rounded-lg bg-indigo px-2.5 py-1.5 text-caption text-white">{m.text}</div>
              ) : (
                <div key={i} className={`rounded-lg border px-2.5 py-2 text-caption ${
                  m.status === "failed" ? "border-danger/30 bg-danger/5 text-danger" : "border-line bg-paper-dim text-ink"}`}>
                  <div className="flex items-start gap-2">
                    {m.status === "working" && <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-indigo" />}
                    {m.status === "done" && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />}
                    <span>{m.text}</span>
                  </div>
                  {m.sections && m.sections.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {m.sections.map((s) => (
                        <button key={s.section_id} onClick={() => jumpToSection(s.section_id)}
                          className="rounded-md border border-line bg-paper px-2 py-0.5 text-micro hover:border-indigo/50 hover:text-indigo">{s.title}</button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              <div ref={chatEndRef} />
              {error && <div className="rounded-md border border-danger/30 bg-danger/5 px-2 py-2 text-caption text-danger">{error}</div>}
            </div>

            <div className="shrink-0 border-t border-line p-3">
              {fileCards("mb-2 flex flex-col gap-1.5", true)}
              <div className="flex items-end gap-2 rounded-xl border border-line bg-paper-dim/70 px-2.5 py-1.5 focus-within:border-indigo/50">
                <input ref={refineFileRef} type="file" multiple accept=".pdf,.txt,.md,.csv" className="hidden"
                  onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
                <button onClick={() => refineFileRef.current?.click()} disabled={busyUpload || running || refining || !result}
                  aria-label="Attach files"
                  className="mb-0.5 shrink-0 rounded-lg p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-50">
                  {busyUpload ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
                </button>
                <textarea ref={refineRef} value={chatInput} onChange={(e) => setChatInput(e.target.value)} rows={1} disabled={running || !result}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleRefine(); } }}
                  placeholder={running ? "Writing…" : "Tell Sykra what to change…"}
                  className="max-h-24 min-h-[24px] flex-1 resize-none bg-transparent py-1 text-[13px] text-ink placeholder:text-ink-soft/60 focus:outline-none disabled:opacity-50" />
                <button onClick={handleRefine} disabled={(!chatInput.trim() && !files.some((f) => !f.sent && f.status === "done")) || refining || running || busyUpload} aria-label="Send"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-white disabled:opacity-30">
                  {refining ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowUp className="h-3.5 w-3.5" />}
                </button>
              </div>
              <p className="mt-1.5 text-center text-micro text-ink-soft/80">Sykra can make mistakes. Verify important claims.</p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}