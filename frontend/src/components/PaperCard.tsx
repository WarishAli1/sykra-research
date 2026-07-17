import { ExternalLink } from "lucide-react";
import { RelevanceStack } from "./RelevanceStack";
import type { Paper } from "@/lib/types";

export function PaperCard({
  paper,
  index,
}: {
  paper: Paper;
  index?: number;
}) {
  return (
    <div className="group relative rounded-lg border border-line bg-paper/80 p-3.5 shadow-sm shadow-black/5 transition-colors hover:border-indigo/40 hover:bg-paper">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          {typeof index === "number" && (
            <span className="mt-0.5 shrink-0 text-[11px] font-medium text-ink-soft tabular-nums">
              [{index}]
            </span>
          )}
          <h4 className="font-serif text-[13.5px] leading-snug text-ink line-clamp-2">
            {paper.title}
          </h4>
        </div>
      </div>

      <p className="mt-1 text-[11.5px] text-ink-soft line-clamp-1">
        {paper.authors.join(", ") || "Unknown authors"}
        {paper.published ? ` \u00b7 ${paper.published}` : ""}
      </p>

      <p className="mt-2 text-[12.5px] leading-relaxed text-ink-soft line-clamp-3">
        {paper.summary}
      </p>

      <div className="mt-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RelevanceStack score={paper.relevance_score} />
          {paper.is_uploaded && (
            <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
              Uploaded
            </span>
          )}
        </div>
        {(paper.link || paper.file_url) && (
          <a
            href={paper.file_url ?? paper.link}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
          >
            {paper.is_uploaded ? "Open PDF" : "View source"} <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}
