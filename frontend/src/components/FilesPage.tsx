"use client";

import { Download, ExternalLink, FileText, MoreHorizontal, Search, Trash2, UploadCloud, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, resolveAssetUrl } from "@/lib/api";
import type { SessionFile, UploadStreamEvent } from "@/lib/types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const GRID = "grid min-w-[760px] grid-cols-[minmax(240px,2.4fr)_90px_minmax(150px,1.2fr)_80px_80px_44px] items-center gap-4 px-5";

function sourceLabel(source: SessionFile["source"]) {
  return source === "chat" ? "Chat" : source === "report" ? "Report" : "Files";
}

export function FilesPage({ sessionId, onOpenPdf }: { sessionId: string; onOpenPdf: (url: string) => void }) {
  const [files, setFiles] = useState<SessionFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | SessionFile["source"]>("all");
  const [sort, setSort] = useState<"newest" | "name">("newest");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState<{ name: string; label: string } | null>(null);
  const [confirm, setConfirm] = useState<SessionFile | null>(null);
  const [deleting, setDeleting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [menu, setMenu] = useState<{ file: SessionFile; top: number; left: number } | null>(null);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("resize", close); window.removeEventListener("scroll", close, true); window.removeEventListener("keydown", esc); };
  }, [menu]);

  function openMenu(e: React.MouseEvent<HTMLButtonElement>, file: SessionFile) {
    e.stopPropagation();
    if (menu?.file.id === file.id) { setMenu(null); return; }
    const r = e.currentTarget.getBoundingClientRect();
    const width = 176, height = 132;
    const top = r.bottom + height + 8 > window.innerHeight ? Math.max(8, r.top - height - 4) : r.bottom + 4;
    setMenu({ file, top, left: Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8)) });
  }

  function downloadFile(file: SessionFile) {
    const a = document.createElement("a");
    a.href = resolveAssetUrl(file.url) ?? file.url;
    a.download = file.name;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    document.body.appendChild(a); a.click(); a.remove();
  }

  const refresh = () => {
    api.listFiles(sessionId)
      .then(setFiles)
      .catch((error) => { console.error("Could not load session files:", error); setFiles([]); })
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    let active = true;
    api.listFiles(sessionId)
      .then((result) => { if (active) setFiles(result); })
      .catch((error) => { console.error("Could not load session files:", error); if (active) setFiles([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sessionId]);

  const visibleFiles = useMemo(() => files
    .filter((file) => file.name.toLowerCase().includes(query.toLowerCase()))
    .filter((file) => sourceFilter === "all" || file.source === sourceFilter)
    .sort((a, b) => sort === "name"
      ? a.name.localeCompare(b.name)
      : (b.uploaded_at ?? "").localeCompare(a.uploaded_at ?? "")), [files, query, sort, sourceFilter]);

  async function upload(file: File) {
    setUploading({ name: file.name, label: "Uploading and indexing..." });
    try {
      await api.uploadPdfStream(file, sessionId, (event: UploadStreamEvent) => {
        if (event.type === "progress") setUploading({ name: file.name, label: event.label });
        if (event.type === "error") throw new Error(event.message);
      }, undefined, undefined, undefined, "files");
      setLoading(true);
      refresh();
    } catch (error) {
      console.error("Could not upload file:", error);
    } finally {
      setUploading(null);
    }
  }

  async function deleteFile() {
    if (!confirm) return;
    setDeleting(true);
    try {
      await api.deleteFile(sessionId, confirm.id);
      setFiles((current) => current.filter((file) => file.id !== confirm.id));
      setConfirm(null);
    } catch (error) {
      console.error("Could not delete file:", error);
    } finally {
      setDeleting(false);
    }
  }

  function openFile(file: SessionFile) {
    const url = resolveAssetUrl(file.url) ?? file.url;
    if (file.type === "application/pdf") onOpenPdf(url);
    else window.open(url, "_blank", "noopener,noreferrer");
  }

  return (
    <main className="flex h-full min-h-0 flex-col bg-paper p-6 text-ink sm:p-8"
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file) void upload(file); }}>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="font-serif text-3xl">Files</h1><p className="mt-1 text-sm text-ink-soft">Everything uploaded in this session</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex h-9 min-w-[190px] items-center gap-2 rounded-lg border border-line bg-paper-dim/50 px-3 text-sm text-ink-soft">
            <Search className="h-4 w-4" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files" className="min-w-0 flex-1 bg-transparent outline-none" />
          </label>
          <select value={sort} onChange={(event) => setSort(event.target.value as "newest" | "name")} className="h-9 rounded-lg border border-line bg-paper-dim/50 px-3 text-sm"><option value="newest">Newest first</option><option value="name">Name</option></select>
          <select aria-label="Filter by source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as "all" | SessionFile["source"])} className="h-9 rounded-lg border border-line bg-paper-dim/50 px-3 text-sm"><option value="all">All sources</option><option value="chat">Chat</option><option value="report">Report</option><option value="files">Files</option></select>
          <button onClick={() => inputRef.current?.click()} className="flex h-9 items-center gap-2 rounded-lg bg-indigo px-4 text-sm font-semibold text-white hover:opacity-90"><UploadCloud className="h-4 w-4" />Upload file</button>
          <input ref={inputRef} type="file" accept=".pdf,application/pdf" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ""; }} />
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-line bg-paper-dim/30">
        <div className={`${GRID} sticky top-0 z-10 border-b border-line bg-paper-dim/60 py-3 text-label uppercase tracking-wide text-ink-soft`}><span>File name</span><span>Source</span><span>Uploaded</span><span>Size</span><span>Used in</span><span /></div>
        {!loading && visibleFiles.length === 0 && <div className="flex h-48 items-center justify-center text-sm text-ink-soft">No files</div>}
        {!loading && visibleFiles.map((file) => <div key={file.id} className={`${GRID} group border-b border-line py-3 last:border-b-0 hover:bg-paper-dim/40`}>
          <button onClick={() => openFile(file)} title={file.name} className="flex min-w-0 items-center gap-3 text-left"><FileText className="h-5 w-5 shrink-0 text-indigo" /><span className="truncate text-sm font-medium hover:text-indigo">{file.name}</span></button>
          <span><b className="rounded-full bg-paper-dim px-2 py-1 text-xs font-medium text-ink">{sourceLabel(file.source)}</b></span>
          <span className="truncate text-xs text-ink-soft">{file.uploaded_at ? new Date(file.uploaded_at).toLocaleString() : "—"}</span>
          <span className="text-xs text-ink-soft">{formatBytes(file.size)}</span>
          <span className="text-xs text-ink-soft" title={file.references?.join(", ")}>{file.references?.length ?? 0}</span>
          <div className="flex justify-end"><button onClick={(e) => openMenu(e, file)} aria-haspopup="menu" aria-expanded={menu?.file.id === file.id} aria-label={`Actions for ${file.name}`} className="rounded-md p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink"><MoreHorizontal className="h-4 w-4" /></button></div>
        </div>)}
        {uploading && <div className="flex items-center gap-3 border-b border-line px-5 py-4 text-sm"><UploadCloud className="h-4 w-4 text-indigo" /><span className="truncate">{uploading.name}</span><span className="text-ink-soft">{uploading.label}</span></div>}
      </div>

      {menu && typeof document !== "undefined" && createPortal(
        <>
          <div className="fixed inset-0 z-[60]" onMouseDown={() => setMenu(null)} />
          <div role="menu" style={{ top: menu.top, left: menu.left }} className="fixed z-[61] w-44 overflow-hidden rounded-lg border border-line bg-paper py-1 text-sm shadow-lg shadow-black/20">
            <button role="menuitem" onClick={() => { openFile(menu.file); setMenu(null); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-ink hover:bg-paper-dim"><ExternalLink className="h-4 w-4 text-ink-soft" />Open</button>
            <button role="menuitem" onClick={() => { downloadFile(menu.file); setMenu(null); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-ink hover:bg-paper-dim"><Download className="h-4 w-4 text-ink-soft" />Download</button>
            <div className="my-1 border-t border-line" />
            <button role="menuitem" onClick={() => { setConfirm(menu.file); setMenu(null); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-danger hover:bg-danger/10"><Trash2 className="h-4 w-4" />Delete</button>
          </div>
        </>, document.body)}
      {dragging && <div className="pointer-events-none fixed inset-4 z-40 flex items-center justify-center rounded-2xl border-2 border-dashed border-indigo bg-paper/90 text-lg font-medium text-indigo">Drop file to upload</div>}
      {confirm && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-5"><div className="w-full max-w-md rounded-xl border border-line bg-paper p-6 text-ink shadow-xl"><div className="flex justify-between"><h2 className="font-serif text-xl">Delete file?</h2><button onClick={() => setConfirm(null)}><X className="h-4 w-4" /></button></div><p className="mt-3 text-sm text-ink-soft">This permanently removes the file, its index, and its links.</p>{(confirm.references?.length ?? 0) > 0 && <ul className="mt-3 list-disc pl-5 text-sm">{confirm.references?.map((reference) => <li key={reference}>{reference}</li>)}</ul>}<div className="mt-6 flex justify-end gap-2"><button onClick={() => setConfirm(null)} className="rounded-lg px-4 py-2 text-sm">Cancel</button><button disabled={deleting} onClick={() => void deleteFile()} className="rounded-lg bg-danger px-4 py-2 text-sm font-semibold text-white">Delete</button></div></div></div>}
    </main>
  );
}