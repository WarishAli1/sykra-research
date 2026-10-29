import { useEffect, useMemo, useRef, useState } from "react";
import type { HTMLAttributes, ImgHTMLAttributes } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { ResearchSteps } from "./ResearchSteps";
import "katex/dist/katex.min.css";
import {
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
  Zap,
  ChevronDown,
  Table2,
} from "lucide-react";
import type { ChatTurn } from "@/lib/types";
import { api, ApiError, resolveAssetUrl } from "@/lib/api";

function stripReferencesBlock(text: string): string {
  let s = text;
  const refPatterns = [
    /\n\n---\n\n\*\*References\*\*[\s\S]*$/i,
    /\n\n---\n\n#{1,6}\s*References\b[\s\S]*$/i,
    /\n\n#{1,6}\s*References\b[\s\S]*$/i,
  ];
  for (const p of refPatterns) {
    if (p.test(s)) {
      s = s.replace(p, "");
      break;
    }
  }
  return s.trim();
}

const DISCLAIMER_PATTERN = /(?:^|\n+)\s*\*?_?Sykra can make mistakes\.[^\n]*?starting baseline\.?_?\*?\s*$/i;

function stripDisclaimerLine(text: string): string {
  return text
    .replace(DISCLAIMER_PATTERN, "")
    .replace(/\n+---\s*$/, "")
    .trim();
}

function stripMarkdown(text: string): string {
  let s = text;
  s = s.replace(/\$\$(.+?)\$\$/gs, "$1");
  s = s.replace(/\$(.+?)\$/g, "$1");
  s = s.replace(/\*\*(.+?)\*\*/g, "$1");
  s = s.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, "$1");
  s = s.replace(/`([^`\n]+?)`/g, "$1");
  s = s.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  s = s.replace(/^#{1,6}\s+/gm, "");
  s = s.replace(/^\s*[-*+]\s+/gm, "");
  s = s.replace(/^\s*\d+[.)]\s+/gm, "");
  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

function formatRefPlain(ref: { id: number; title: string; authors?: string[]; link?: string; published?: string | null }): string {
  const authors = ref.authors?.length ? ref.authors.slice(0, 3).join(", ") + ". " : "";
  const year = ref.published ? `(${ref.published})` : "";
  return `[${ref.id}] ${authors}${ref.title}${year}. ${ref.link ?? ""}`;
}

function formatRefMarkdown(ref: { id: number; title: string; authors?: string[]; link?: string; published?: string | null }): string {
  const authors = ref.authors?.length ? `— ${ref.authors.slice(0, 3).join(", ")}` : "";
  const year = ref.published ? `(${ref.published})` : "";
  return `${ref.id}. [${ref.title}](${ref.link ?? ""})${authors}${year}`;
}

function refYear(published?: string | null): string {
  if (!published) return "";
  const m = String(published).match(/^\d{4}/);
  return m ? m[0] : String(published);
}

function refAuthors(authors?: string[]): string {
  if (!authors?.length) return "";
  const first = authors.slice(0, 3).join(", ");
  return authors.length > 3 ? `${first} et al.` : first;
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

function isMathFenceLine(line: string): boolean {
  return /^[ \t]*\$\$[ \t]*$/.test(line);
}

function isMathProseBoundary(line: string): boolean {
  return /^[ \t]*$/.test(line) || /^[ \t]*#{1,6}\s/.test(line);
}

function normalizeMathFences(md: string): string {
  let s = md;
  s = s.replace(/【/g, "[").replace(/】/g, "]")
    .replace(/（/g, "(").replace(/）/g, ")")
    .replace(/：/g, ":").replace(/；/g, ";");
  s = s.replace(/[\[【]\s*paper[\s_]?id[^\]】]*[\]】]/gi, "");
  s = s.replace(/[\u200b\ufeff]/g, "").replace(/\u00a0/g, " ");

  const mathSpans: string[] = [];
  const MATH_PLACEHOLDER = (i: number) => `\u0000MATH${i}\u0000`;
  s = s.replace(/\$\$[^]*?\$\$/g, (m) => {
    mathSpans.push(m);
    return MATH_PLACEHOLDER(mathSpans.length - 1);
  });
  s = s.replace(/\$([^$\n]+?)\$(?!\$|\d)/g, (m) => {
    mathSpans.push(m);
    return MATH_PLACEHOLDER(mathSpans.length - 1);
  });
  s = s.replace(/\$(\d)/g, "USD $1");
  mathSpans.forEach((span, i) => {
    s = s.replace(MATH_PLACEHOLDER(i), () => span);
  });

  for (let pass = 0; pass < 2; pass++) {
    s = s.replace(/([^\n])\$\$/g, "$1\n$$");
    s = s.replace(/\$\$([^\n])/g, "$$\n$1");
  }
  s = s.replace(/\n{3,}/g, "\n\n");
  const lines = s.split("\n");
  const out: string[] = [];
  let inMath = false;
  const ensureBlank = () => {
    if (out.length && out[out.length - 1].trim() !== "") out.push("");
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (isMathFenceLine(line)) {
      if (!inMath) {
        if (i + 1 < lines.length && isMathFenceLine(lines[i + 1])) {
          i++;
          continue;
        }
        ensureBlank();
        out.push("$$");
        inMath = true;
      } else {
        out.push("$$");
        inMath = false;
        ensureBlank();
      }
    } else if (inMath && isMathProseBoundary(line)) {
      out.push("$$");
      inMath = false;
      out.push(line);
      if (line.trim() !== "") ensureBlank();
    } else {
      out.push(line);
    }
  }
  if (inMath) out.push("$$");
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

function polishAnswer(md: string, turnKey: string): string {
  const spans: string[] = [];
  const stash = (m: string) => {
    spans.push(m);
    return `\u0000S${spans.length - 1}\u0000`;
  };
  let s = md.replace(/```[\s\S]*?```|\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|`[^`\n]+`/g, stash);
  s = s.replace(/(?<=\S)[ \t]+([.,;:!?])(?=\s|$)/g, "$1");
  s = s.replace(/\[(\d{1,3})\](?![(:])/g, (_, n) => `[${n}](#ref-${turnKey}-${n})`);
  return s.replace(/\u0000S(\d+)\u0000/g, (_, i) => spans[Number(i)]);
}

const baseMarkdownComponents: Components = {
  table({ children, ...props }: HTMLAttributes<HTMLTableElement>) {
    return (
      <div className="my-5 overflow-x-auto rounded-xl border border-sage/60 bg-paper shadow-soft">
        <table {...props}>{children}</table>
      </div>
    );
  },
  img({ src, alt, ...props }: ImgHTMLAttributes<HTMLImageElement>) {
    const source = typeof src === "string" ? src : undefined;
    const resolved = resolveAssetUrl(source);
    return (
      <span className="my-3 block">
        <img
          {...props}
          src={resolved ?? source}
          alt={alt ?? "Generated chart"}
          className="max-w-full max-h-[360px] w-auto h-auto rounded-md border border-line shadow-sm shadow-black/5 object-contain"
        />
        {alt && <span className="mt-1 block text-center text-micro text-ink-soft">{alt}</span>}
      </span>
    );
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
};

function buildMarkdownComponents(turnKey: string): Components {
  const prefix = `#ref-${turnKey}-`;
  return {
    ...baseMarkdownComponents,
    a({ href, children }) {
      if (href && href.startsWith(prefix)) {
        const targetId = href.slice(1);
        return (
          <sup className="cite">
            <a
              href={href}
              onClick={(e) => {
                e.preventDefault();
                const el = document.getElementById(targetId);
                if (el) {
                  el.scrollIntoView({ behavior: "smooth", block: "center" });
                  el.classList.add("ref-flash");
                  setTimeout(() => el.classList.remove("ref-flash"), 1600);
                }
              }}
            >
              [{children}]
            </a>
          </sup>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      );
    },
  };
}

function PreviewAnswer({ preview, hasFinal, streaming }: { preview: string; hasFinal: boolean; streaming: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? !hasFinal;
  const generating = streaming && !hasFinal;

  return (
    <div className="mb-4 animate-fade-up overflow-hidden rounded-lg border border-gold/35 bg-gold-tint/40">
      <button
        onClick={() => setUserOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-gold-tint/70"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-accent/40 bg-accent/15">
          <Zap className={`h-3 w-3 text-accent ${generating ? "animate-pulse" : ""}`} />
        </span>
        <span className="shrink-0 text-label text-ink">Quick answer</span>
        <span className="hidden truncate text-micro text-ink-soft sm:inline">
          {generating ? "summarizing…" : hasFinal ? "at a glance · full answer below" : "at a glance"}
        </span>
        {generating && <Loader2 className="h-3 w-3 shrink-0 animate-spin text-ink-soft" />}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="ml-auto shrink-0"
        >
          <ChevronDown className="h-3.5 w-3.5 text-ink-soft" />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="preview-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="border-t border-gold/25 px-3.5 py-3">
              <div className="prose-chat border-l-2 border-gold/50 pl-3">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[[rehypeKatex, { throwOnError: false, errorColor: "#8a9099" }]]}
                  components={baseMarkdownComponents}
                >
                  {normalizeMathFences(preview)}
                </ReactMarkdown>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function ChatMessage({
  turn,
  sessionId,
  onRegenerate,
  onOpenGraph,
}: {
  turn: ChatTurn;
  sessionId: string;
  onRegenerate?: () => void | Promise<void>;
  onOpenGraph?: () => void;
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
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const isAssistant = turn.role === "assistant";
  const rawAnswer = useMemo(
    () => (isAssistant ? stripDisclaimerLine(stripReferencesBlock(turn.text)) : ""),
    [turn.text, isAssistant]
  );
  const displayAnswer = useMemo(
    () => polishAnswer(normalizeMathFences(rawAnswer), turn.id),
    [rawAnswer, turn.id]
  );
  const markdownComponents = useMemo(() => buildMarkdownComponents(turn.id), [turn.id]);

  if (turn.role === "user") {
    return (
      <div className="flex justify-end animate-fade-up">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo px-4 py-2.5 text-[15px] leading-relaxed text-white">
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
  const hasPreview = !!turn.previewText;
  const showMetadata = !isStreaming && (hasText || hasPreview);
  const artifacts = turn.artifacts;

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
        chart_path: artifacts?.chartUrl ?? turn.chartUrl ?? undefined,
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
      for (const r of turn.references) content += "\n" + formatRefMarkdown(r);
    }
    downloadTextFile(`${turn.filename ?? "research-answer"}.md`, content, "text/markdown");
    setMenuOpen(false);
  }

  function handleExportText() {
    let body = stripReferencesBlock(turn.text);
    body = stripMarkdown(body);
    let content = body;
    if (turn.references?.length) {
      content += "\n\nReferences\n";
      for (const r of turn.references) content += "\n" + formatRefPlain(r);
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
    } catch {}
  }

  async function handleShare() {
    const shareText = stripReferencesBlock(turn.text);
    if (navigator.share) {
      try {
        await navigator.share({ text: shareText });
        return;
      } catch {}
    }
    await handleCopy();
  }

  const hasSteps = !!turn.statusSteps?.length;
  const showStatusFallback = isStreaming && !!turn.statusLabel && !hasText && !hasPreview && !hasSteps;
  const hasBody = hasText || isStopped || regenerating || showMetadata;
  const isEmptyFailure = !isStreaming && !isStopped && !regenerating && !hasText && !hasPreview && !hasSteps;

  return (
    <div className="animate-fade-up px-1">
      {hasSteps && (
        <div className="mb-3">
          <ResearchSteps embedded steps={turn.statusSteps!} streaming={isStreaming} />
        </div>
      )}

      {showStatusFallback && (
        <div className="flex items-center gap-2 text-caption text-ink-soft">
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
          <span>{turn.statusLabel}</span>
        </div>
      )}

      {isEmptyFailure && (
        <div className="flex items-center gap-1.5 text-caption text-ink-soft">
          <OctagonX className="h-3.5 w-3.5 shrink-0" />
          <span>No answer was generated. Please try again.</span>
        </div>
      )}

      {hasPreview && <PreviewAnswer preview={turn.previewText!} hasFinal={hasText} streaming={isStreaming} />}

      {hasBody && (
        <div>
          {hasText && (
            <>
              {hasPreview && (
                <div className="mb-2 flex items-center gap-1.5 text-label text-ink-soft">
                  <FileText className="h-3.5 w-3.5" />
                  Full answer
                </div>
              )}       
              <div className="prose-chat">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[[rehypeKatex, { throwOnError: false, errorColor: "#8a9099" }]]}
                  components={markdownComponents}
                >
                  {displayAnswer}
                </ReactMarkdown>
                {isStreaming && (
                  <span
                    aria-hidden="true"
                    className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-pulse bg-indigo/70"
                  />
                )}
              </div>

              {/* {!isStreaming && turn.methodNote && (
                <p className="mt-3 text-sm leading-relaxed text-ink-soft">
                  {turn.methodNote}
                </p>
              )} */}

            </>
          )}
          {artifacts?.chartUrl && (
            <figure className="mt-4 animate-fade-up">
              <img
                src={resolveAssetUrl(artifacts.chartUrl) ?? artifacts.chartUrl}
                alt="Generated chart"
                className="max-w-full max-h-[360px] w-auto h-auto rounded-lg border border-line shadow-sm shadow-black/5 object-contain"
              />
              <figcaption className="mt-1 text-center text-micro text-ink-soft">Generated chart</figcaption>
            </figure>
          )}

          {artifacts?.comparisonTableMarkdown && (
            <div className="mt-4 animate-fade-up">
              <div className="mb-1.5 flex items-center gap-1.5 text-label text-ink-soft">
                <Table2 className="h-3.5 w-3.5 text-indigo" />
                {artifacts.comparisonTableCaption || "Comparison"}
              </div>
              <div className="prose-chat">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={baseMarkdownComponents}>
                  {artifacts.comparisonTableMarkdown}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {isStopped && (
            <div className="mt-2 flex items-center gap-1.5 text-micro text-ink-soft">
              <OctagonX className="h-3 w-3 shrink-0" />
              <span>Generation stopped.</span>
            </div>
          )}

          {showMetadata && !!turn.sources?.length && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
              <BookMarked className="h-3.5 w-3.5 text-ink-soft" />
              {turn.sources.map((s, i) => (
                <span key={i} className="rounded-full bg-paper-dim px-2 py-0.5 text-micro text-ink-soft">
                  {s}
                </span>
              ))}
            </div>
          )}

          {showMetadata && showReferencesInline && (
            <div className="mt-6 border-t border-line pt-4">
              <div className="mb-3 flex items-center gap-1.5 text-label text-ink-soft">
                <BookMarked className="h-3.5 w-3.5" />
                {isResearched ? "References" : "Key references"}
              </div>
              <ul className="space-y-1">
                {turn.references!.map((r) => {
                  const meta = [refAuthors(r.authors), refYear(r.published)].filter(Boolean).join(" · ");
                  return (
                    <li
                      key={r.id}
                      id={`ref-${turn.id}-${r.id}`}
                      className="grid scroll-mt-24 grid-cols-[2.5rem_minmax(0,1fr)] gap-x-1 rounded-md px-1.5 py-1.5 transition-colors"
                    >
                      <span className="pt-px text-right text-caption tabular-nums text-ink-soft">[{r.id}]</span>
                      <div className="min-w-0 text-[14px] leading-snug">
                        <a
                          href={r.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-medium text-indigo hover:underline"
                        >
                          {r.title}
                        </a>
                        {meta && <div className="mt-0.5 text-caption text-ink-soft">{meta}</div>}
                        {r.why_cited && <div className="mt-0.5 text-caption text-ink-soft">{r.why_cited}</div>}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {showMetadata && !showReferencesInline && !!turn.references?.length && (
            <div className="mt-2 text-micro text-ink-soft">
              {turn.references.length} reference{turn.references.length === 1 ? "" : "s"} added to Library.
            </div>
          )}

          {showMetadata && !!turn.papers?.length && (
            <div className="mt-3 flex items-center gap-1.5 text-micro text-ink-soft">
              <BookMarked className="h-3.5 w-3.5 shrink-0" />
              {turn.papers.length} paper{turn.papers.length === 1 ? "" : "s"} added to Library
            </div>
          )}

          {regenerating && (
            <div className="mt-3 flex items-center gap-2 border-t border-line pt-2.5 text-micro text-ink-soft">
              <Loader2 className="h-3 w-3 animate-spin" />
              Regenerating this answer…
            </div>
          )}

          {showMetadata && !regenerating && (
            <div className="mt-4 flex items-center gap-1">
              <button
                onClick={() => handleExport("standard")}
                disabled={exporting}
                aria-label="Download standard PDF"
                title="Download standard PDF"
                className="flex items-center gap-1 rounded-md bg-paper-dim px-2 py-1 text-micro text-ink-soft hover:text-indigo disabled:opacity-50"
              >
                {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
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
                className={`flex h-6 w-6 items-center justify-center rounded-md hover:bg-paper-dim ${feedback === "up" ? "text-indigo" : "text-ink-soft hover:text-indigo"}`}
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setFeedback((f) => (f === "down" ? null : "down"))}
                aria-label="Bad response"
                aria-pressed={feedback === "down"}
                title="Bad response"
                className={`flex h-6 w-6 items-center justify-center rounded-md hover:bg-paper-dim ${feedback === "down" ? "text-danger" : "text-ink-soft hover:text-danger"}`}
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
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption text-ink hover:bg-paper-dim"
                    >
                      <FileText className="h-3.5 w-3.5 text-ink-soft" />
                      Export Markdown
                    </button>
                    <button
                      role="menuitem"
                      onClick={handleExportText}
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption text-ink hover:bg-paper-dim"
                    >
                      <FileDown className="h-3.5 w-3.5 text-ink-soft" />
                      Export Text
                    </button>
                    {onRegenerate && (
                      <button
                        role="menuitem"
                        onClick={handleRegenerateClick}
                        disabled={regenerating}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption text-ink hover:bg-paper-dim disabled:opacity-50"
                      >
                        <RefreshCw className={`h-3.5 w-3.5 text-ink-soft ${regenerating ? "animate-spin" : ""}`} />
                        Regenerate
                      </button>
                    )}
                    <button
                      role="menuitem"
                      onClick={() => handleExport("latex")}
                      disabled={exporting}
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption text-ink hover:bg-paper-dim disabled:opacity-50"
                    >
                      <GraduationCap className="h-3.5 w-3.5 text-ink-soft" />
                      Academic PDF
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {exportError && <div className="mt-1.5 text-micro text-danger">{exportError}</div>}
        </div>
      )}
    </div>
  );
}