import { ExternalLink, X } from "lucide-react";
import { RelevanceStack } from "./RelevanceStack";
import type { Paper } from "@/lib/types";

export function PaperCard({
  paper,
  index,
  onOpenPdf,
  onDeletePaper
}: {
  paper: Paper;
  index?: number;
  onOpenPdf: (url: string) => void;
  onDeletePaper: (paper: Paper) => void | Promise<void>;
}) {
  return (
    <div className={`group relative rounded-lg border bg-paper/80 p-3.5 shadow-sm transition-colors hover:border-indigo/40 hover:bg-paper ${
      paper.source === "user_upload" ? "border-l-4 border-l-indigo" : 
      paper.source === "arxiv" ? "border-l-4 border-l-red-400" : 
      "border-l-4 border-l-blue-400"
    }`}>
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

        {paper.source === "user_upload" && (
          <button
            onClick={() => onDeletePaper(paper)}
            className="opacity-0 group-hover:opacity-100 transition text-red-500 hover:text-red-700"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <p className="mt-1 text-[11.5px] text-ink-soft line-clamp-1">
        {paper.authors.join(", ") || "Unknown authors"}
        {paper.published ? ` · ${paper.published}` : ""}
      </p>
      <p className="mt-2 text-[12.5px] leading-relaxed text-ink-soft line-clamp-3">
        {paper.summary}
      </p>
      <div className="mt-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RelevanceStack score={paper.relevance_score} />
          {paper.source === "user_upload" && (
            <span className="text-[10px] font-medium text-indigo">PDF</span>
          )}
          {paper.source === "arxiv" && (
            <span className="text-[10px] font-medium text-red-500">arXiv</span>
          )}
          {paper.source === "openalex" && (
            <span className="text-[10px] font-medium text-blue-500">OpenAlex</span>
          )}
        </div>
        {(paper.link || paper.file_url) &&
          (paper.source === "user_upload" ? (
            <button
              onClick={() => onOpenPdf(paper.file_url!)}
              className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
            >
              Open PDF
              <ExternalLink className="h-3 w-3" />
            </button>
          ) : (
            <a
              href={paper.link}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
            >
              View source
              <ExternalLink className="h-3 w-3" />
            </a>
          ))}
      </div>
    </div>
  );
}