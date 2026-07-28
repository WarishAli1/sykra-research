"use client";

import { useMemo, useState, useRef, useEffect } from "react";
import { Search, Library, SlidersHorizontal, Check } from "lucide-react";
import { PaperCard } from "./PaperCard";
import type { Paper } from "@/lib/types";

type SortMode = "relevance" | "newest" | "oldest" | "title";

export function LibraryPanel({
  papers,
  onOpenPdf,
  onDeletePaper,
}: {
  papers: Paper[];
  onOpenPdf: (url: string) => void;
  onDeletePaper: (paper: Paper) => void | Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [minRelevance, setMinRelevance] = useState(0);
  const [sortMode, setSortMode] = useState<SortMode>("relevance");
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setFilterOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const filtered = useMemo(() => {
    let result = papers;

    if (query.trim()) {
      const q = query.toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(q) ||
          p.authors.some((a) => a.toLowerCase().includes(q))
      );
    }

    if (minRelevance > 0) {
      result = result.filter((p) => (p.relevance_score ?? 0) >= minRelevance);
    }

    result = [...result].sort((a, b) => {
      switch (sortMode) {
        case "relevance":
          return (b.relevance_score ?? 0) - (a.relevance_score ?? 0);
        case "newest":
          return (b.published ?? "").localeCompare(a.published ?? "");
        case "oldest":
          return (a.published ?? "").localeCompare(b.published ?? "");
        case "title":
          return a.title.localeCompare(b.title);
        default:
          return 0;
      }
    });

    return result;
  }, [papers, query, minRelevance, sortMode]);

  const filterActive = minRelevance > 0 || sortMode !== "relevance";

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center gap-2 mb-3">
          <Library className="h-4 w-4 text-indigo" />
          <span className="font-serif text-[15px] font-semibold text-ink">Library</span>
          <span className="ml-auto text-[11px] text-ink-soft">{papers.length}</span>
        </div>
        <div className="flex items-center gap-1.5 rounded-lg border border-line bg-paper-dim/75 px-2.5 py-1.5 shadow-inner shadow-black/5">
          <Search className="h-3.5 w-3.5 text-ink-soft shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sources"
            className="w-full bg-transparent text-[12.5px] text-ink placeholder:text-ink-soft/60 focus:outline-none"
          />
          <div className="relative" ref={filterRef}>
            <button
              onClick={() => setFilterOpen((v) => !v)}
              aria-label="Filter and sort"
              aria-expanded={filterOpen}
              className={`flex items-center justify-center rounded-md p-0.5 transition-colors ${
                filterActive
                  ? "text-indigo"
                  : "text-ink-soft hover:text-indigo"
              }`}
            >
              <SlidersHorizontal className="h-3.5 w-3.5 shrink-0" />
              {filterActive && (
                <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-gold" />
              )}
            </button>

            {filterOpen && (
              <div className="absolute right-0 top-6 z-20 w-56 rounded-lg border border-line bg-paper/95 p-3 shadow-lg shadow-black/10 animate-fade-up">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  Sort by
                </p>
                <div className="mb-3 space-y-0.5">
                  {(
                    [
                      ["relevance", "Relevance"],
                      ["newest", "Newest first"],
                      ["oldest", "Oldest first"],
                      ["title", "Title (A\u2013Z)"],
                    ] as [SortMode, string][]
                  ).map(([mode, label]) => (
                    <button
                      key={mode}
                      onClick={() => setSortMode(mode)}
                      className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-[12px] text-ink hover:bg-paper-dim/90"
                    >
                      {label}
                      {sortMode === mode && <Check className="h-3.5 w-3.5 text-indigo" />}
                    </button>
                  ))}
                </div>

                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  Min. relevance
                </p>
                <div className="flex items-center gap-2 px-1">
                  <input
                    type="range"
                    min={0}
                    max={0.9}
                    step={0.1}
                    value={minRelevance}
                    onChange={(e) => setMinRelevance(parseFloat(e.target.value))}
                    className="w-full accent-indigo"
                  />
                  <span className="w-8 shrink-0 text-[11px] tabular-nums text-ink-soft">
                    {(minRelevance * 100).toFixed(0)}%
                  </span>
                </div>

                {filterActive && (
                  <button
                    onClick={() => {
                      setMinRelevance(0);
                      setSortMode("relevance");
                    }}
                    className="mt-2.5 text-[11.5px] font-medium text-indigo hover:text-indigo-dark"
                  >
                    Reset
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2.5">
        {papers.length === 0 && (
          <div className="px-2 py-8 text-center">
            <p className="text-[12.5px] text-ink-soft">
              Papers discovered in chat will collect here.
            </p>
          </div>
        )}

        {papers.length > 0 && filtered.length === 0 && (
          <p className="px-2 text-[12.5px] text-ink-soft">
            No matches{query ? ` for "${query}"` : ""}.
          </p>
        )}

        {filtered.map((p, i) => (
          <PaperCard key={`${p.link}-${i}`} paper={p} onOpenPdf={onOpenPdf} onDeletePaper={onDeletePaper} />
        ))}
      </div>
    </div>
  );
}