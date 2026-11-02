"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { FileText, FolderOpen, Loader2, Monitor, Search, X } from "lucide-react";
import { api, resolveAssetUrl } from "@/lib/api";
import type { SessionFile } from "@/lib/types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type Props = {
  sessionId: string;
  icon: ReactNode;
  onPickComputer: () => void;
  onPickFiles: (files: File[]) => void | Promise<void>;
  disabled?: boolean;
  /** Max files selectable from the session picker. */
  maxSelect?: number;
  /** Restrict the picker to these file extensions, e.g. [".pdf"]. Empty = all. */
  extensions?: string[];
  ariaLabel?: string;
  title?: string;
  buttonClassName?: string;
};

export function UploadMenu({
  sessionId, icon, onPickComputer, onPickFiles, disabled, maxSelect = 3,
  extensions = [".pdf"], ariaLabel = "Attach files", title, buttonClassName,
}: Props) {
  const [open, setOpen] = useState(false);
  const [picker, setPicker] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div className="relative shrink-0" ref={wrapRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        title={title ?? ariaLabel}
        className={buttonClassName ?? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-paper hover:text-ink disabled:opacity-50"}
      >
        {icon}
      </button>
      {open && (
        <div role="menu" className="absolute bottom-full left-0 z-40 mb-2 w-56 overflow-hidden rounded-xl border border-line bg-paper py-1 shadow-lg shadow-black/20 animate-fade-up">
          <button
            role="menuitem"
            onClick={() => { setOpen(false); onPickComputer(); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-caption text-ink hover:bg-paper-dim"
          >
            <Monitor className="h-3.5 w-3.5 text-ink-soft" />Upload from computer
          </button>
          <button
            role="menuitem"
            onClick={() => { setOpen(false); setPicker(true); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-caption text-ink hover:bg-paper-dim"
          >
            <FolderOpen className="h-3.5 w-3.5 text-ink-soft" />Upload from files
          </button>
        </div>
      )}
      {picker && (
        <FilePicker
          sessionId={sessionId}
          maxSelect={maxSelect}
          extensions={extensions}
          onClose={() => setPicker(false)}
          onConfirm={async (files) => { await onPickFiles(files); setPicker(false); }}
        />
      )}
    </div>
  );
}

function FilePicker({ sessionId, maxSelect, extensions, onClose, onConfirm }: {
  sessionId: string;
  maxSelect: number;
  extensions: string[];
  onClose: () => void;
  onConfirm: (files: File[]) => Promise<void>;
}) {
  const [files, setFiles] = useState<SessionFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.listFiles(sessionId)
      .then((result) => { if (active) setFiles(result); })
      .catch(() => { if (active) setError("Could not load your files."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sessionId]);

  const visible = useMemo(() => files
    .filter((file) => !extensions.length || extensions.some((ext) => file.name.toLowerCase().endsWith(ext)))
    .filter((file) => file.name.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => (b.uploaded_at ?? "").localeCompare(a.uploaded_at ?? "")), [files, query, extensions]);

  const toggle = (id: string) => setSelected((current) =>
    current.includes(id) ? current.filter((x) => x !== id) : current.length >= maxSelect ? current : [...current, id]);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const picked = files.filter((file) => selected.includes(file.id));
      const blobs = await Promise.all(picked.map(async (file) => {
        const response = await fetch(resolveAssetUrl(file.url) ?? file.url, { credentials: "include" });
        if (!response.ok) throw new Error(file.name);
        const blob = await response.blob();
        return new File([blob], file.name, { type: file.type || blob.type });
      }));
      await onConfirm(blobs);
    } catch (e) {
      setError(`Could not add ${e instanceof Error && e.message ? e.message : "the selected file"}. Try again.`);
      setBusy(false);
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/40 p-5" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div role="dialog" aria-label="Choose from your files" className="flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-line bg-paper text-ink shadow-xl">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-serif text-lg">Choose from your files</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-ink-soft hover:bg-paper-dim hover:text-ink"><X className="h-4 w-4" /></button>
        </div>
        <div className="border-b border-line px-5 py-3">
          <label className="flex h-9 items-center gap-2 rounded-lg border border-line bg-paper-dim px-3 text-sm text-ink-soft">
            <Search className="h-4 w-4" />
            <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files" className="min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-ink-soft/70" />
          </label>
        </div>
        <div className="min-h-[180px] flex-1 overflow-y-auto px-2 py-2">
          {loading ? (
            <div className="flex h-40 items-center justify-center text-ink-soft"><Loader2 className="h-4 w-4 animate-spin" /></div>
          ) : visible.length === 0 ? (
            <div className="flex h-40 items-center justify-center text-sm text-ink-soft">No files found</div>
          ) : visible.map((file) => {
            const checked = selected.includes(file.id);
            const locked = !checked && selected.length >= maxSelect;
            return (
              <label key={file.id} className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-paper-dim ${locked ? "opacity-50" : ""}`}>
                <input type="checkbox" checked={checked} disabled={locked} onChange={() => toggle(file.id)} className="h-4 w-4 accent-[var(--indigo)]" />
                <FileText className="h-4 w-4 shrink-0 text-indigo" />
                <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
                <span className="shrink-0 text-xs text-ink-soft">{formatBytes(file.size)}</span>
              </label>
            );
          })}
        </div>
        {error && <p className="border-t border-line px-5 py-2 text-caption text-danger">{error}</p>}
        <div className="flex items-center justify-between border-t border-line px-5 py-3">
          <span className="text-caption text-ink-soft">{selected.length} of {maxSelect} selected</span>
          <div className="flex gap-2">
            <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-ink hover:bg-paper-dim">Cancel</button>
            <button onClick={() => void confirm()} disabled={selected.length === 0 || busy} className="flex items-center gap-2 rounded-lg bg-indigo px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40">
              {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Add
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}