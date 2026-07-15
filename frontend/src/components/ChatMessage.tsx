import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, BookMarked } from "lucide-react";
import type { ChatTurn } from "@/lib/types";

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end animate-fade-up">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo px-3.5 py-2.5 text-[13.5px] text-white">
          {turn.text}
        </div>
      </div>
    );
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

        {typeof turn.papersBelowThreshold === "number" &&
          turn.papersBelowThreshold > 0 && (
            <div className="mt-2 text-[11.5px] text-ink-soft">
              {turn.papersBelowThreshold} additional paper
              {turn.papersBelowThreshold === 1 ? "" : "s"} scored below the
              relevance threshold and were omitted.
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

        {!!turn.papers?.length && (
          <div className="mt-3 flex items-center gap-1.5 border-t border-line pt-2.5 text-[11.5px] text-ink-soft">
            <BookMarked className="h-3.5 w-3.5 shrink-0" />
            {turn.papers.length} paper{turn.papers.length === 1 ? "" : "s"} added to Library
          </div>
        )}
      </div>
    </div>
  );
}