import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { ResearchSteps } from "./ResearchSteps";
import "katex/dist/katex.min.css";
import {
  AlertTriangle,
  BookMarked,
  Download,
  Loader2,
  Share2,
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  MoreHorizontal,
  RefreshCw,
  FileText,
  FileDown,
  GraduationCap,
  OctagonX,
} from "lucide-react";
import type { ChatTurn } from "@/lib/types";
import { api, ApiError, resolveAssetUrl } from "@/lib/api";
function stripReferencesBlock(text: string): string {
  const marker = "\n\n---\n\n**References**";
  const idx = text.indexOf(marker);
  return idx === -1 ? text : text.slice(0, idx).trim();
}

function stripMarkdown(text: string): string {
  let s = text;
  s = s.replace(/\$\$(.+?)\$\$/gs, "$1");
  s = s.replace(/\$(.+?)\$/g, "$1");
  s = s.replace(/\*\*(.+?)\*\*/g, "$1");
  s = s.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, "$1");
  s = s.replace(/`([^`]+?)`/g, "$1");
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  s = s.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  s = s.replace(/^#{1,6}\s+/gm, "");
  s = s.replace(/^\s*[-*+]\s+/gm, "");
  s = s.replace(/^\s*\d+[.)]\s+/gm, "");
  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

function formatRefPlain(ref: { id: number; title: string; authors?: string[]; link?: string; published?: string | null }): string {
  const authors = ref.authors?.length ? ref.authors.slice(0, 3).join(", ") + ". " : "";
  const year = ref.published ? ` (${ref.published})` : "";
  return `[${ref.id}] ${authors}${ref.title}${year}. ${ref.link ?? ""}`;
}

function formatRefMarkdown(ref: { id: number; title: string; authors?: string[]; link?: string; published?: string | null }): string {
  const authors = ref.authors?.length ? ` — ${ref.authors.slice(0, 3).join(", ")}` : "";
  const year = ref.published ? ` (${ref.published})` : "";
  return `${ref.id}. [${ref.title}](${ref.link ?? ""})${authors}${year}`;
}

function downloadTextFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const markdownComponents = {
  ul({ children, ...props }: any) {
    return (
      <ul {...props} className="my-2 space-y-1 pl-1">
        {children}
      </ul>
    );
  },
  ol({ children, ...props }: any) {
    return (
      <ol {...props} className="my-2 space-y-1 pl-1 list-decimal list-inside marker:text-ink-soft">
        {children}
      </ol>
    );
  },
  li({ children, ordered, ...props }: any) {
    if (ordered) {
      return (
        <li {...props} className="pl-1 text-[13.5px] leading-relaxed">
          {children}
        </li>
      );
    }
    return (
      <li {...props} className="flex gap-2 text-[13.5px] leading-relaxed">
        <span aria-hidden="true" className="shrink-0 text-ink-soft select-none">
          •
        </span>
        <span className="flex-1">{children}</span>
      </li>
    );
  },
  table({ children, ...props }: any) {
    return (
      <div className="my-3 overflow-x-auto rounded-md border border-line">
        <table {...props} className="w-full border-collapse text-[12.5px]">
          {children}
        </table>
      </div>
    );
  },
  thead({ children, ...props }: any) {
    return (
      <thead {...props} className="bg-paper-dim text-ink">
        {children}
      </thead>
    );
  },
  th({ children, ...props }: any) {
    return (
      <th {...props} className="border-b border-line px-3 py-1.5 text-left font-semibold">
        {children}
      </th>
    );
  },
  td({ children, ...props }: any) {
    return (
      <td {...props} className="border-b border-line/60 px-3 py-1.5 align-top">
        {children}
      </td>
    );
  },
  img({ src, alt, ...props }: any) {
    const resolved = resolveAssetUrl(src);
    return (
      <span className="my-3 block">
        <img
          {...props}
          src={resolved ?? src}
          alt={alt ?? "Generated chart"}
          className="max-w-full max-h-[360px] w-auto h-auto rounded-md border border-line shadow-sm shadow-black/5 object-contain"
        />
        {alt && <span className="mt-1 block text-center text-[11px] text-ink-soft">{alt}</span>}
      </span>
    );
  },
};

export function ChatMessage({
  turn,
  sessionId,
  onRegenerate,
}: {
  turn: ChatTurn;
  sessionId: string;
  onRegenerate?: () => void | Promise<void>;
}) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  if (turn.role === "user") {
    return (
      <div className="flex justify-end animate-fade-up">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo px-3.5 py-2.5 text-[13.5px] text-white">
          {turn.text}
        </div>
      </div>
    );
  }

  const isResearched = turn.responseMode === "researched";
  const showReferencesInline = !!turn.references?.length;
  const isStreaming = !!turn.streaming;
  const isStopped = !!turn.stopped;
  const hasText = turn.text.trim().length > 0;
  const showMetadata = !isStreaming;

  async function handleExport(format: "standard" | "latex") {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await api.exportPdf({
        session_id: sessionId,
        turn_id: turn.turnId,
        format,
        answer: turn.text,
        references: turn.references ?? [],
        title: "Research Assistant Answer",
        chart_path: turn.chartUrl ?? undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${turn.filename ?? "research-answer"}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof ApiError ? e.message : "Could not generate PDF.");
    } finally {
      setExporting(false);
      setMenuOpen(false);
    }
  }

  function handleExportMarkdown() {
    const body = stripReferencesBlock(turn.text);
    let content = body;
    if (turn.references?.length) {
      content += "\n\n---\n\n## References\n";
      for (const r of turn.references) {
        content += "\n" + formatRefMarkdown(r);
      }
    }
    downloadTextFile(`${turn.filename ?? "research-answer"}.md`,content,"text/markdown");
    setMenuOpen(false);
  }

  function handleExportText() {
    let body = stripReferencesBlock(turn.text);
    body = stripMarkdown(body);
    let content = body;
    if (turn.references?.length) {
      content += "\n\nReferences\n";
      for (const r of turn.references) {
        content += "\n" + formatRefPlain(r);
      }
    }
    downloadTextFile(`${turn.filename ?? "research-answer"}.txt`, content, "text/plain");
    setMenuOpen(false);
  }

  async function handleRegenerateClick() {
    if (!onRegenerate) return;
    setMenuOpen(false);
    setRegenerating(true);
    try {
      await onRegenerate();
    } finally {
      setRegenerating(false);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(stripReferencesBlock(turn.text));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
    }
  }

  async function handleShare() {
    const shareText = stripReferencesBlock(turn.text);
    if (navigator.share) {
      try {
        await navigator.share({ text: shareText });
        return;
      } catch {
      }
    }
    await handleCopy();
  }
  const hasSteps = !!turn.statusSteps?.length;
  const showStatusFallback = isStreaming && !!turn.statusLabel && !hasText && !hasSteps;
  const hasBody = hasText || isStopped || regenerating || showMetadata;
    return (
    <div className="animate-fade-up space-y-3">
      <div className="rounded-2xl rounded-bl-sm border border-line bg-paper/85 px-4 py-3 shadow-sm shadow-black/5">
        {hasSteps && (
          <ResearchSteps
            embedded
            steps={turn.statusSteps!}
            streaming={isStreaming}
          />
        )}

        {showStatusFallback && (
          <div className="flex items-center gap-2 text-[12.5px] text-ink-soft">
            <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
            <span>{turn.statusLabel}</span>
          </div>
        )}

        {hasBody && (
          <div className={hasSteps ? "border-t border-line pt-3" : ""}>
            {hasText && (
              <div className="prose-chat text-[13.5px] leading-relaxed text-ink">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={markdownComponents}
                >
                  {stripReferencesBlock(turn.text)}
                </ReactMarkdown>
                {isStreaming && (
                  <span
                    aria-hidden="true"
                    className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-pulse bg-indigo/70"
                  />
                )}
              </div>
            )}

            {isStopped && (
              <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-ink-soft">
                <OctagonX className="h-3 w-3 shrink-0" />
                <span>Generation stopped.</span>
              </div>
            )}

            {showMetadata && turn.domainCaveat && (
              <div className="mt-3 flex items-start gap-2 rounded-md bg-gold-tint px-2.5 py-2 text-[12px] text-ink-soft">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
                <span>{turn.domainCaveat}</span>
              </div>
            )}

            {showMetadata && !!turn.coverageGaps?.length && (
              <div className="mt-2 text-[12px] text-ink-soft">
                <span className="font-medium text-ink">Coverage gaps: </span>
                {turn.coverageGaps.join("; ")}
              </div>
            )}

            {showMetadata && !!turn.sources?.length && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5">
                <BookMarked className="h-3.5 w-3.5 text-ink-soft" />
                {turn.sources.map((s, i) => (
                  <span
                    key={i}
                    className="rounded-full bg-paper-dim px-2 py-0.5 text-[11px] text-ink-soft"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}

            {showMetadata && showReferencesInline && (
              <div className="mt-3 border-t border-line pt-2.5">
                <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  <BookMarked className="h-3.5 w-3.5" />
                  {isResearched ? "References" : "Key References"}
                </div>

                {isResearched ? (
                  <ol className="space-y-1 text-[12px] text-ink-soft list-decimal list-inside">
                    {turn.references!.map((r) => (
                      <li key={r.id} value={r.id}>
                        <a href={r.link} target="_blank" rel="noopener noreferrer" className="text-indigo hover:underline">
                          {r.title}
                        </a>
                        {r.authors?.length ? ` — ${r.authors.slice(0, 3).join(", ")}` : ""}
                        {r.published ? ` (${r.published})` : ""}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <ul className="space-y-1.5 text-[12.5px]">
                    {turn.references!.map((r) => (
                      <li key={r.id} className="flex items-baseline gap-2">
                        <a href={r.link} target="_blank" rel="noopener noreferrer" className="text-indigo hover:underline font-medium">
                          {r.title}
                        </a>
                        {r.published && <span className="text-ink-soft shrink-0">({r.published})</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {showMetadata && !showReferencesInline && !!turn.references?.length && (
              <div className="mt-2 text-[11.5px] text-ink-soft">
                {turn.references.length} reference{turn.references.length === 1 ? "" : "s"} added to Library.
              </div>
            )}

            {showMetadata && !!turn.papers?.length && (
              <div className="mt-3 flex items-center gap-1.5 border-t border-line pt-2.5 text-[11.5px] text-ink-soft">
                <BookMarked className="h-3.5 w-3.5 shrink-0" />
                {turn.papers.length} paper{turn.papers.length === 1 ? "" : "s"} added to Library
              </div>
            )}

            {regenerating && (
              <div className="mt-3 flex items-center gap-2 border-t border-line pt-2.5 text-[11.5px] text-ink-soft">
                <Loader2 className="h-3 w-3 animate-spin" />
                Regenerating this answer…
              </div>
            )}

            {showMetadata && !regenerating && (
              <div className="mt-3 flex items-center gap-1 border-t border-line pt-2.5">
                <button
                  onClick={() => handleExport("standard")}
                  disabled={exporting}
                  aria-label="Download standard PDF"
                  title="Download standard PDF"
                  className="flex items-center gap-1 rounded-md bg-paper-dim px-2 py-1 text-[11px] text-ink-soft hover:text-indigo disabled:opacity-50"
                >
                  {exporting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="h-3 w-3" />
                  )}
                  PDF
                </button>

                <button
                  onClick={handleShare}
                  aria-label="Share answer"
                  title="Share"
                  className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
                >
                  <Share2 className="h-3.5 w-3.5" />
                </button>

                <button
                  onClick={handleCopy}
                  aria-label="Copy answer"
                  title="Copy"
                  className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
                </button>

                <button
                  onClick={() => setFeedback((f) => (f === "up" ? null : "up"))}
                  aria-label="Good response"
                  aria-pressed={feedback === "up"}
                  title="Good response"
                  className={`flex h-6 w-6 items-center justify-center rounded-md hover:bg-paper-dim ${
                    feedback === "up" ? "text-indigo" : "text-ink-soft hover:text-indigo"
                  }`}
                >
                  <ThumbsUp className="h-3.5 w-3.5" />
                </button>

                <button
                  onClick={() => setFeedback((f) => (f === "down" ? null : "down"))}
                  aria-label="Bad response"
                  aria-pressed={feedback === "down"}
                  title="Bad response"
                  className={`flex h-6 w-6 items-center justify-center rounded-md hover:bg-paper-dim ${
                    feedback === "down" ? "text-danger" : "text-ink-soft hover:text-danger"
                  }`}
                >
                  <ThumbsDown className="h-3.5 w-3.5" />
                </button>

                <div className="relative ml-1" ref={menuRef}>
                  <button
                    onClick={() => setMenuOpen((o) => !o)}
                    aria-label="More actions"
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    title="More actions"
                    className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </button>

                  {menuOpen && (
                    <div
                      role="menu"
                      className="absolute left-0 bottom-full z-20 mb-1.5 w-48 rounded-lg border border-line bg-paper shadow-lg shadow-black/10 py-1"
                    >
                      <button
                        role="menuitem"
                        onClick={handleExportMarkdown}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-ink hover:bg-paper-dim"
                      >
                        <FileText className="h-3.5 w-3.5 text-ink-soft" />
                        Export Markdown
                      </button>
                      <button
                        role="menuitem"
                        onClick={handleExportText}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-ink hover:bg-paper-dim"
                      >
                        <FileDown className="h-3.5 w-3.5 text-ink-soft" />
                        Export Text
                      </button>
                      {onRegenerate && (
                        <button
                          role="menuitem"
                          onClick={handleRegenerateClick}
                          disabled={regenerating}
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-ink hover:bg-paper-dim disabled:opacity-50"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 text-ink-soft ${regenerating ? "animate-spin" : ""}`} />
                          Regenerate
                        </button>
                      )}
                      <button
                        role="menuitem"
                        onClick={() => handleExport("latex")}
                        disabled={exporting}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-ink hover:bg-paper-dim disabled:opacity-50"
                      >
                        <GraduationCap className="h-3.5 w-3.5 text-ink-soft" />
                        Academic PDF
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {exportError && (
              <div className="mt-1.5 text-[11px] text-danger">{exportError}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}