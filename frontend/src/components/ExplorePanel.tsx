"use client";

import { useState } from "react";
import {
  Network,
  ChevronDown,
  ChevronRight,
  Loader2,
  ArrowLeft,
  ExternalLink,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { useResearchGraph } from "@/lib/useResearchGraph";

export function ExplorePanel({ projectId }: { projectId: string }) {
  const {
    clusters,
    contradictions,
    loading,
    error,
    loadOverview,
    focusLink,
    focusTitle,
    focus,
    focusLoading,
    focusError,
    openFocus,
    closeFocus,
  } = useResearchGraph(projectId);
  const [openCluster, setOpenCluster] = useState<string | null>(null);

  if (focusLink) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
          <button
            onClick={closeFocus}
            aria-label="Back to clusters"
            className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
          </button>
          <span className="font-serif text-[13px] font-semibold text-ink truncate">
            {focusTitle}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4 text-[12.5px]">
          {focusLoading && (
            <div className="flex items-center gap-2 text-[12px] text-ink-soft animate-fade-up">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading citation network...
            </div>
          )}

          {focusError && (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
              {focusError}
            </div>
          )}

          {focus && (
            <>
              {!!focus.concepts?.length && (
                <div>
                  <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
                    Concepts
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {focus.concepts.map((c) => (
                      <span
                        key={c}
                        className="rounded-full bg-paper-dim px-2 py-0.5 text-[11px] text-ink-soft"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {!!focus.methods?.length && (
                <div>
                  <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
                    Methods
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {focus.methods.map((m) => (
                      <span
                        key={m}
                        className="rounded-full bg-gold-tint px-2 py-0.5 text-[11px] text-ink"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
                  Cites ({focus.children?.length ?? 0})
                </p>
                {!focus.children?.length && (
                  <p className="text-[11.5px] text-ink-soft">No outgoing citations recorded yet.</p>
                )}
                <div className="space-y-1.5">
                  {focus.children?.map((p) => (
                    <NodeRow key={p.link} node={p} onOpen={openFocus} />
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
                  Cited by ({focus.parents?.length ?? 0})
                </p>
                {!focus.parents?.length && (
                  <p className="text-[11.5px] text-ink-soft">No incoming citations recorded yet.</p>
                )}
                <div className="space-y-1.5">
                  {focus.parents?.map((p) => (
                    <NodeRow key={p.link} node={p} onOpen={openFocus} />
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Network className="h-4 w-4 text-indigo" />
        <span className="font-serif text-[15px] font-semibold text-ink">Explore</span>
        <button
          onClick={loadOverview}
          aria-label="Refresh graph"
          className="flex h-6 w-6 items-center justify-center rounded-md text-ink-soft hover:bg-paper-dim hover:text-indigo"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4 text-[12.5px]">
        {loading && !clusters && (
          <div className="flex items-center gap-2 text-[12px] text-ink-soft animate-fade-up">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading the research graph...
          </div>
        )}

        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
            {error}
          </div>
        )}

        {clusters && clusters.length === 0 && !loading && (
          <div className="px-2 py-8 text-center">
            <p className="text-[12.5px] text-ink-soft">
              No graph data yet. Ask a research question to populate the graph.
            </p>
          </div>
        )}

        {!!clusters?.length && (
          <div>
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
              Topics
            </p>
            <p className="mb-2 text-[11.5px] text-ink-soft leading-relaxed">
              Groups of papers that cover the same subject.
            </p>
            <div className="space-y-2">
              {clusters.map((c) => {
                const isOpen = openCluster === c.concept;
                return (
                  <div
                    key={c.concept}
                    className="rounded-lg border border-line bg-paper/80 shadow-sm shadow-black/5"
                  >
                    <button
                      onClick={() => setOpenCluster(isOpen ? null : c.concept)}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
                    >
                      {isOpen ? (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                      )}
                      <span className="font-serif text-[13px] capitalize text-ink truncate">
                        {c.concept}
                      </span>
                      <span className="ml-auto shrink-0 rounded-full bg-paper-dim px-2 py-0.5 text-[10.5px] text-ink-soft">
                        {c.paper_count}
                      </span>
                    </button>
                    {isOpen && (
                      <div className="space-y-1 border-t border-line px-3 py-2">
                        {c.papers.map((title) => (
                          <p key={title} className="text-[11.5px] leading-relaxed text-ink-soft">
                            {title}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {!!contradictions.length && (
          <div>
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
              Where papers disagree
            </p>
            <p className="mb-2 text-[11.5px] text-ink-soft leading-relaxed">
              These pairs of papers make conflicting claims that the system verified.
            </p>
            <div className="space-y-2">
              {contradictions.map((c, i) => (
                <div
                  key={i}
                  className="rounded-md border border-danger/20 bg-danger/5 px-2.5 py-2"
                >
                  <div className="flex items-start gap-1.5">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-danger" />
                    <div className="min-w-0">
                      <p className="text-[11px] font-medium text-ink truncate">
                        {c.paper_a} <span className="text-ink-soft">vs</span> {c.paper_b}
                      </p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-ink-soft">
                        {c.reason}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function NodeRow({
  node,
  onOpen,
}: {
  node: { title?: string; link?: string; published?: string };
  onOpen: (link: string, title: string) => void;
}) {
  return (
    <button
      onClick={() => node.link && onOpen(node.link, node.title ?? node.link)}
      className="flex w-full items-center justify-between gap-2 rounded-md bg-paper-dim px-2.5 py-1.5 text-left hover:bg-paper-dim/70"
    >
      <span className="min-w-0 truncate text-[11.5px] text-ink">{node.title ?? "Untitled"}</span>
      <ExternalLink className="h-3 w-3 shrink-0 text-ink-soft" />
    </button>
  );
}