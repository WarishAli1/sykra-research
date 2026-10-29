"use client";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ElementType } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { useEditor, EditorContent, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Table } from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import { Markdown } from "tiptap-markdown";
import { ArrowLeft, ArrowUp, Download, Loader2, Paperclip, Square, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  EvidenceMode, ReportPrepareResponse, ReportRecord, ReportStreamEvent,
  ReportStructureDraft, ReportRunResult, StatusStep, ReportArtifact,
} from "@/lib/types";
import { ReportPrepareModal, toConfirmed } from "@/components/ReportPrepareModal";
import { ResearchSteps } from "@/components/ResearchSteps";
import { ReportToolbar, FONTS, DEFAULT_FORMAT, type DocFormat } from "@/components/report/ReportToolBar";
type SheetSection = { section_id: string; title: string; markdown: string; final: boolean };
type Attached = { name: string; kind: "data" | "guideline"; text?: string }; 
type Msg = { role: "user" | "assistant"; text: string };

const BRIEF_MAX_HEIGHT = 180;
const escHtml = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const GUIDE_NAME_RE = /guideline|template|format|structure|instruction|outline/i;
const GUIDE_BODY_RE = /instruction|guideline|outline|template|must be|should be|format/gi;
const NUMERIC_RE = /^[-+\u2212\u2013(]?\s*\d[\d.,]*\)?$/;

function looksLikeGuideline(name: string, text: string) {
  if (GUIDE_NAME_RE.test(name)) return true;
  const head = text.slice(0, 4000);
  return (head.match(GUIDE_BODY_RE)?.length ?? 0) >= 4 && /chapter\s*\d|outline/i.test(head);
}

const cleanMd = (md: string) => md.replace(/\[ev_[a-z]+_\d+\]\s?/gi, "");
const linkCitations = (md: string) =>
  cleanMd(md).replace(/<u>([\s\S]*?)<\/u>/g, "[$1](#rp-u)").replace(/\[(\d{1,3})\](?![(:])/g, "[$1](#rp-ref-$1)");
const stripU = (md: string) => md.replace(/<\/?u>/g, "");
const mdComponents: Components = {
  a({ href, children }) {
    if (href === "#rp-u") return <u>{children}</u>;
    if (href?.startsWith("#rp-ref-"))
      return <sup className="cite"><a href={href} onClick={(e) => {
        e.preventDefault(); e.stopPropagation();
        document.getElementById(href.slice(1))?.scrollIntoView({ behavior: "smooth", block: "center" });
      }}>{children}</a></sup>;
    return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
  },
};

function EditableText({ value, tag, disabled, onCommit }: {
  value: string; tag: "h1" | "h2"; disabled?: boolean; onCommit: (v: string) => void;
}) {
  const Tag: ElementType = tag;
  const end = (el: HTMLElement, text: string) => { el.textContent = text; el.blur(); };
  return (
    <Tag key={value} contentEditable={!disabled} suppressContentEditableWarning spellCheck={false}
      onBlur={(e: React.FocusEvent<HTMLElement>) => {
        const t = (e.currentTarget.textContent ?? "").replace(/\s+/g, " ").trim();
        if (t && t !== value) onCommit(t); else e.currentTarget.textContent = value;
      }}
      onKeyDown={(e: React.KeyboardEvent<HTMLElement>) => {
        if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
        if (e.key === "Escape") end(e.currentTarget, value);
      }}
      onPaste={(e: React.ClipboardEvent) => { e.preventDefault(); document.execCommand("insertText", false, e.clipboardData.getData("text/plain")); }}
    >{value}</Tag>
  );
}

function SectionEditor({ initial, onSave, onCancel, onReady }: { initial: string; onSave: (md: string) => void; onCancel: () => void; onReady: (e: Editor | null) => void }) {
  const editor = useEditor({
    immediatelyRender: false, autofocus: "end", content: initial,
    extensions: [StarterKit, Table, TableRow, TableHeader, TableCell, Markdown.configure({ html: true })],
  });
  useEffect(() => { onReady(editor); return () => onReady(null); }, [editor]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = () => {
    if (!editor) return;
    type MdStorage = { markdown: { getMarkdown(): string } };
    const md = (editor.storage as unknown as MdStorage).markdown
      .getMarkdown()
      .replace(/\\\[(\d{1,3})\\\]/g, "[$1]");
    onSave(md);
  };
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
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<Attached[]>([]);
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
  const [result, setResult] = useState<ReportRunResult | null>(null);
  const [meta, setMeta] = useState<{ chatId: string; messageId: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chat, setChat] = useState<Msg[]>([]);
  const [filename, setFilename] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [fmt, setFmt] = useState<DocFormat>(DEFAULT_FORMAT);
  const [activeEditor, setActiveEditor] = useState<Editor | null>(null);
  const [, redraw] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!activeEditor) return;
    const h = () => redraw((n) => n + 1);
    activeEditor.on("transaction", h);
    return () => { activeEditor.off("transaction", h); };
  }, [activeEditor]);

  const evidenceMode: EvidenceMode = hasUpload ? "blended" : "literature";
  const dataText = files.filter((f) => f.kind === "data" && f.text).map((f) => f.text).join("\n\n");
  const guidelineText = files.filter((f) => f.kind === "guideline" && f.text).map((f) => f.text).join("\n\n");

  // auto-grow the brief input (single row by default, capped, then scrolls)
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, BRIEF_MAX_HEIGHT) + "px";
  }, [query, started]);

  useEffect(() => {
    api.reportLatest(sessionId).then((latest) => {
      if (!latest) return;
      const a: ReportArtifact = latest.artifact;
      setTitle(a.title);
      setSheet(a.sections.map((s) => ({ section_id: s.section_id, title: s.title, markdown: s.content, final: true })));
      setResult({
        turn_id: "", chat_id: latest.chat_id, message_id: latest.message_id, title: a.title, answer: "",
        references: a.references, sections: a.sections, papers: [],
      });
      setMeta({ chatId: latest.chat_id, messageId: latest.message_id });
      setStarted(true);
    }).catch(() => {});
  }, [sessionId]);

  async function addFiles(list: FileList | null) {
    if (!list) return;
    for (const f of Array.from(list)) {
      const isPdf = f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
      if (!isPdf) {
        const text = await f.text();
        setFiles((p) => [...p, { name: f.name, kind: GUIDE_NAME_RE.test(f.name) ? "guideline" : "data", text }]);
        continue;
      }
      setBusyUpload(true);
      try {
        const { text } = await api.reportGuidelineText(f).catch(() => ({ text: "" }));
        if (text && looksLikeGuideline(f.name, text)) {
          setFiles((p) => [...p, { name: f.name, kind: "guideline", text }]); // structure only, never indexed
          continue;
        }
        await api.uploadPdfStream(f, sessionId, (ev) => {
          if (ev.type === "result") setHasUpload(true);
          if (ev.type === "error") setError(ev.message);
        }, undefined, crypto.randomUUID(), undefined);
        setFiles((p) => [...p, { name: f.name, kind: "data" }]);
      } catch { setError("Upload failed."); } finally { setBusyUpload(false); }
    }
  }
  const toggleKind = (i: number) => setFiles((p) => p.map((f, j) =>
    j === i && f.text ? { ...f, kind: f.kind === "data" ? "guideline" : "data" } : f));

  const startRun = useCallback(async (d: ReportStructureDraft, records: ReportRecord[], path?: string) => {
    setError(null); setRunning(true); setStarted(true);
    setSheet([]); setSteps([]); setResult(null); setFilename(null);
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
            const copy = [...prev]; copy[i] = { ...next, title: next.title || copy[i].title }; return copy;
          });
        } else if (ev.type === "result" && "sections" in ev.payload) {
          const r = ev.payload as ReportRunResult;
          setResult(r); setTitle(r.title); setMeta({ chatId: r.chat_id, messageId: r.message_id });
          setSheet(r.sections.map((s) => ({ section_id: s.section_id, title: s.title, markdown: s.content, final: true })));
        } else if (ev.type === "filename") setFilename(ev.filename);
        else if (ev.type === "error") setError(ev.message);
      }, controller.signal);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 0)) setError(e instanceof ApiError ? e.message : "Report generation failed.");
    } finally { setRunning(false); abortRef.current = null; requestIdRef.current = null; }
  }, [query, sessionId, evidenceMode, title, guidelineText]);

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

  function handleStop() {
    if (requestIdRef.current) api.cancelStream(requestIdRef.current).catch(() => {});
    abortRef.current?.abort();
  }

  async function saveSection(id: string, md: string) {
    setEditing(null);
    const cur = sheet.find((s) => s.section_id === id);
    if (!meta || !cur || cur.markdown === md) return;
    try {
      await api.reportPatchSections({ chat_id: meta.chatId, message_id: meta.messageId, sections: [{ section_id: id, content: md }] });
      setSheet((p) => p.map((s) => s.section_id === id ? { ...s, markdown: md } : s));
      setResult((r) => r ? { ...r, sections: r.sections.map((s) => s.section_id === id ? { ...s, content: md } : s) } : r);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not save the edit."); }
  }

  async function saveTitle(t: string) {
    setTitle(t); setResult((r) => (r ? { ...r, title: t } : r));
    if (!meta) return;
    try { await api.reportPatchSections({ chat_id: meta.chatId, message_id: meta.messageId, sections: [], title: t }); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not save the title."); }
  }
  async function saveSectionTitle(id: string, t: string) {
    setSheet((p) => p.map((s) => (s.section_id === id ? { ...s, title: t } : s)));
    setResult((r) => (r ? { ...r, sections: r.sections.map((s) => (s.section_id === id ? { ...s, title: t } : s)) } : r));
    if (!meta) return;
    try { await api.reportPatchSections({ chat_id: meta.chatId, message_id: meta.messageId, sections: [{ section_id: id, title: t }] }); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not save the heading."); }
  }

  async function handleRefine() {
    const instruction = chatInput.trim();
    if (!instruction || !meta || refining || running) return;
    setChatInput(""); setRefining(true);
    setChat((l) => [...l, { role: "user", text: instruction }]);
    const c = new AbortController(); abortRef.current = c;
    try {
      await api.reportRefineStream({ chat_id: meta.chatId, message_id: meta.messageId, instruction, request_id: crypto.randomUUID() },
        (ev: ReportStreamEvent) => {
          if (ev.type === "report_section" && ev.final) {
            setSheet((p) => p.map((s) => s.section_id === ev.section_id ? { ...s, markdown: ev.markdown, final: true } : s));
            setResult((r) => r ? { ...r, sections: r.sections.map((s) => s.section_id === ev.section_id ? { ...s, content: ev.markdown } : s) } : r);
          } else if (ev.type === "error") setChat((l) => [...l, { role: "assistant", text: ev.message }]);
        }, c.signal);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Refinement failed."); }
    finally { setRefining(false); abortRef.current = null; }
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
      return download(await api.exportPdf({ session_id: sessionId, format: "standard", answer, references: result.references, title }), `${base}.pdf`);
    }
    const { default: HTMLtoDOCX } = await import("html-to-docx");
    const { marked } = await import("marked");
    const HEAD = "font-family:'Times New Roman';font-weight:bold;";
    const body = `font-family:'${fmt.font}';font-size:${fmt.size}pt;line-height:${fmt.spacing};text-align:${fmt.align};`;
    const brk = '<div style="page-break-after: always"></div>';
    const parts: string[] = [`<h1 style="${HEAD}font-size:18pt;text-align:center">${escHtml(title)}</h1>`];
    for (let i = 0; i < sheet.length; i++) {
      const s = sheet[i];
      if (i > 0) parts.push(brk);
      const inner = (await marked.parse(cleanMd(s.markdown)))
        .replace(/<(p|li)>/g, (_m: string, t: string) => `<${t} style="${body}">`)
        .replace(/<h([1-6])(\s[^>]*)?>/g, (_m: string, n: string) => `<h${n} style="${HEAD}font-size:${n === "1" ? 16 : n === "2" ? 14 : 12}pt">`);
      parts.push(`<h2 style="${HEAD}font-size:16pt">${escHtml(s.title)}</h2><div style="${body}">${inner}</div>`);
    }
    if (result.references.length) {
      parts.push(brk, `<h2 style="${HEAD}font-size:16pt">References</h2>`,
        ...result.references.map((r) => { const t = refText(r); return `<p style="${body}">${escHtml(t.head)} <a href="${t.link}">${escHtml(t.link)}</a></p>`; }));
    }
    const blob = await HTMLtoDOCX(`<div>${parts.join("")}</div>`, null, {
      font: fmt.font, fontSize: fmt.size * 2,
      margins: { left: 2160, right: 1800, top: 1440, bottom: 1440 }, // 1.5in / 1.25in / 1in
    });
    download(blob as Blob, `${base}.docx`);
  }

  const pendingSections = useMemo(
    () => (draft?.sections ?? []).filter((p) => !sheet.some((s) => s.section_id === p.section_id)),
    [draft, sheet]);

  if (!started) return (
    <div className="flex h-full items-center justify-center bg-paper px-6">
      <div className="w-full max-w-[680px]">
        <h1 className="mb-5 text-center font-serif text-[26px] font-semibold text-ink">What should the report cover?</h1>

        <div className="rounded-2xl border border-line bg-paper-dim/50 px-3 py-2 focus-within:border-indigo/50">
          {files.length > 0 && (
            <div className="mb-1.5 flex flex-wrap gap-1.5">
              {files.map((f, i) => (
                <span key={i} className="flex items-center gap-1 rounded-md border border-line bg-paper px-2 py-0.5 text-micro text-ink-soft">
                  {f.name}
                  {f.text && <button onClick={() => toggleKind(i)} className="rounded bg-paper-dim px-1 text-ink hover:text-indigo" title="Click to switch">{f.kind}</button>}
                  <button aria-label="Remove" onClick={() => setFiles((p) => p.filter((_, j) => j !== i))}><X className="h-3 w-3" /></button>
                </span>
              ))}
            </div>
          )}

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
  );

  return (
    <div className="flex h-full min-h-0 bg-paper">
      <div className="flex min-w-0 flex-1 flex-col">
      <ReportToolbar editor={activeEditor} fmt={fmt} onChange={setFmt} />
      <div className="min-h-0 flex-1 overflow-y-auto bg-paper-dim/40 py-8">
        <div className="rp-sheet" style={{ "--rp-font": FONTS.find((f) => f.label === fmt.font)?.css, "--rp-size": `${fmt.size}pt`, "--rp-lh": fmt.spacing, "--rp-align": fmt.align } as CSSProperties}>
          <EditableText tag="h1" value={title || "Report"} disabled={running || !result} onCommit={saveTitle} />
          {sheet.map((s) => (
            <section key={s.section_id}>
              <EditableText tag="h2" value={s.title} disabled={running || !s.final} onCommit={(t) => saveSectionTitle(s.section_id, t)} />
              {editing === s.section_id ? (
                <SectionEditor initial={s.markdown} onSave={(md) => saveSection(s.section_id, md)} onCancel={() => setEditing(null)} onReady={setActiveEditor} />
              ) : (
                <div onClick={(e) => { if (!running && s.final && !(e.target as HTMLElement).closest("a")) setEditing(s.section_id); }}
                  className={!running && s.final ? "cursor-text" : ""}>
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { throwOnError: false }]]} components={mdComponents}>
                    {linkCitations(s.markdown)}
                  </ReactMarkdown>
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

      <div className="flex w-[340px] shrink-0 flex-col border-l border-line bg-paper">
        <div className="relative flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
          <button onClick={() => { setStarted(false); setSheet([]); setResult(null); setChat([]); setFiles([]); setHasUpload(false); setTitle(""); }}
            className="flex items-center gap-1.5 text-caption text-ink-soft hover:text-ink"><ArrowLeft className="h-4 w-4" /> New report</button>
          {running ? (
            <button onClick={handleStop} aria-label="Stop" className="rounded-md bg-danger p-1.5 text-white"><Square className="h-3 w-3 fill-current" /></button>
          ) : (
            <button onClick={() => setMenu((m) => !m)} disabled={!result}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-caption text-ink-soft hover:bg-paper-dim hover:text-ink disabled:opacity-40">
              <Download className="h-4 w-4" /> Export
            </button>
          )}
          {menu && (
            <div className="absolute right-3 top-11 z-10 w-32 rounded-lg border border-line bg-paper py-1 text-caption shadow-lg">
              {(["pdf", "docx", "md"] as const).map((k) => (
                <button key={k} onClick={() => exportAs(k)} className="block w-full px-3 py-1.5 text-left hover:bg-paper-dim">
                  {k === "md" ? "Markdown" : k.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1 min-h-0 space-y-3 overflow-y-auto px-4 py-3">
          {steps.length > 0 && (
            <ResearchSteps key={running ? "run" : "done"} embedded steps={steps} streaming={running} />
          )}
          {!running && result && chat.length === 0 && (
            <p className="text-caption text-ink-soft">Click any section to edit it, or tell Sykra what to change.</p>
          )}
          {chat.map((m, i) => (
            <div key={i} className={`rounded-lg px-2.5 py-1.5 text-caption ${m.role === "user" ? "bg-indigo text-white" : "bg-paper-dim text-ink"}`}>{m.text}</div>
          ))}
          {error && <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-caption text-danger">{error}</div>}
        </div>

        <div className="shrink-0 border-t border-line p-3">
          <div className="flex items-end gap-2 rounded-xl border border-line bg-paper-dim/70 px-2.5 py-1.5 focus-within:border-indigo/50">
            <textarea value={chatInput} onChange={(e) => setChatInput(e.target.value)} rows={1} disabled={running || !result}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleRefine(); } }}
              placeholder={running ? "Writing…" : "Tell Sykra what to change…"}
              className="max-h-24 min-h-[24px] flex-1 resize-none bg-transparent py-1 text-[13px] text-ink placeholder:text-ink-soft/60 focus:outline-none disabled:opacity-50" />
            <button onClick={handleRefine} disabled={!chatInput.trim() || refining || running} aria-label="Send"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-white disabled:opacity-30">
              {refining ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowUp className="h-3.5 w-3.5" />}
            </button>
          </div>
          <p className="mt-1.5 text-center text-micro text-ink-soft/80">Sykra can make mistakes. Verify important claims.</p>
        </div>
      </div>
    </div>
  );
}