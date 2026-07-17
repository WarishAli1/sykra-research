import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, BookMarked, Download, Loader2 } from "lucide-react";
import type { ChatTurn } from "@/lib/types";
import { api, ApiError } from "@/lib/api";

export function ChatMessage({ turn, sessionId }: { turn: ChatTurn; sessionId: string }) {
  const [exporting, setExporting] = useState<"standard" | "latex" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

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

  async function handleExport(format: "standard" | "latex") {
    setExporting(format);
    setExportError(null);
    try {
      const blob = await api.exportPdf({
        session_id: sessionId,
        format,
        answer: turn.text,
        references: turn.references ?? [],
        title: "Research Assistant Answer",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `answer-${format}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof ApiError ? e.message : "Could not generate PDF.");
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="animate-fade-up space-y-3">
      <div className="rounded-2xl rounded-bl-sm border border-line bg-paper/85 px-4 py-3 shadow-sm shadow-black/5">
        <div className="prose-chat text-[13.5px] leading-relaxed text-ink">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.text}</ReactMarkdown>
        </div>

        {turn.domainCaveat && (
          <div className="mt-3 flex items-start gap-2 rounded-md bg-gold-tint px-2.5 py-2 text-[12px] text-ink-soft">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
            <span>{turn.domainCaveat}</span>
          </div>
        )}

        {!!turn.coverageGaps?.length && (
          <div className="mt-2 text-[12px] text-ink-soft">
            <span className="font-medium text-ink">Coverage gaps: </span>
            {turn.coverageGaps.join("; ")}
          </div>
        )}

        {!!turn.sources?.length && (
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

        {showReferencesInline && (
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

        {!showReferencesInline && !!turn.references?.length && (
          <div className="mt-2 text-[11.5px] text-ink-soft">
            {turn.references.length} reference{turn.references.length === 1 ? "" : "s"} added to Library.
          </div>
        )}

        {!!turn.papers?.length && (
          <div className="mt-3 flex items-center gap-1.5 border-t border-line pt-2.5 text-[11.5px] text-ink-soft">
            <BookMarked className="h-3.5 w-3.5 shrink-0" />
            {turn.papers.length} paper{turn.papers.length === 1 ? "" : "s"} added to Library
          </div>
        )}

        <div className="mt-3 flex items-center gap-2 border-t border-line pt-2.5">
          <button
            onClick={() => handleExport("standard")}
            disabled={exporting !== null}
            className="flex items-center gap-1 rounded-md bg-paper-dim px-2 py-1 text-[11px] text-ink-soft hover:text-indigo disabled:opacity-50"
          >
            {exporting === "standard" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Download className="h-3 w-3" />
            )}
            PDF
          </button>
          <button
            onClick={() => handleExport("latex")}
            disabled={exporting !== null}
            className="flex items-center gap-1 rounded-md bg-paper-dim px-2 py-1 text-[11px] text-ink-soft hover:text-indigo disabled:opacity-50"
            title="Academic-style layout"
          >
            {exporting === "latex" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Download className="h-3 w-3" />
            )}
            PDF (Academic style)
          </button>
        </div>

        {exportError && (
          <div className="mt-1.5 text-[11px] text-danger">{exportError}</div>
        )}
      </div>
    </div>
  );
}