import { ExternalLink, X } from "lucide-react";
import { RelevanceStack } from "./RelevanceStack";
import { resolvePdfUrl } from "@/lib/api";
import type { Paper } from "@/lib/types";

export function PaperCard({
  paper,
  index,
  onOpenPdf,
  onDeletePaper,
}: {
  paper: Paper;
  index?: number;
  onOpenPdf: (url: string) => void;
  onDeletePaper: (paper: Paper) => void | Promise<void>;
}) {
  const isUpload = paper.source === "user_upload";
  const pdfUrl = isUpload ? resolvePdfUrl(paper) : null;
  const canOpen = isUpload ? !!pdfUrl : !!paper.link;

  return (
    <div
      className={`group relative rounded-lg border bg-paper p-3.5 shadow-sm transition-colors hover:border-indigo/40 ${
        paper.source === "user_upload"
          ? "border-l-4 border-l-indigo"
          : paper.source === "arxiv"
          ? "border-l-4 border-l-gold"
          : "border-l-4 border-l-ink-soft/40"
      }`}
    >
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
            aria-label="Remove uploaded PDF"
            className="opacity-0 group-hover:opacity-100 transition text-ink-soft hover:text-danger shrink-0"
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
            <span className="text-[10px] font-medium text-gold">arXiv</span>
          )}
          {paper.source === "openalex" && (
            <span className="text-[10px] font-medium text-ink-soft">OpenAlex</span>
          )}
        </div>

        {canOpen &&
          (isUpload ? (
            <button
              onClick={() => onOpenPdf(pdfUrl!)}
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