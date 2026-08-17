"use client";

import { useState } from "react";
import {
  ChevronUp,
  ChevronDown,
  Search,
  Layers,
  PenLine,
  ShieldCheck,
  CheckCheck,
  Loader2,
  Check,
} from "lucide-react";

export type StepEvent = {
  stage: string;
  label: string;
  detail?: string;
  items?: string[];
  done?: boolean;
  evidence_mode?: string;
};

type PhaseId = "search" | "review" | "synthesize" | "refine" | "finalize";
type Mode = "label" | "silent";

type PhaseDef = {
  id: PhaseId;
  title: string;
  icon: React.ElementType;
  placeholder: string;
  stages: Record<string, Mode>;
};

const PHASES: PhaseDef[] = [
  {
    id: "search",
    title: "Searching the web",
    icon: Search,
    placeholder: "Searching",
    stages: {
      plan_query: "label",
      plan_report: "label",
      search: "label",
      retrieve_uploaded: "label",
      answer_spec_node: "label",
      build_retrieval_plan: "label",
    },
  },
  {
    id: "review",
    title: "Reviewing sources",
    icon: Layers,
    placeholder: "Reviewing sources",
    stages: { validate: "label", rank: "label" },
  },
  {
    id: "synthesize",
    title: "Synthesizing the answer",
    icon: PenLine,
    placeholder: "Writing the response",
    stages: {
      quick_preview: "label",
      preview_answer: "label",
      build_ledger: "label",
      summarize: "silent",
    },
  },
  {
    id: "refine",
    title: "Checking answer quality",
    icon: ShieldCheck,
    placeholder: "Cross-checking the draft against your question",
    stages: { critique: "label", revise: "label", after_critique: "silent", verify_claims: "label", },
  },
  {
    id: "finalize",
    title: "Finalizing the response",
    icon: CheckCheck,
    placeholder: "Adding citations and finishing up",
    stages: {
      cite: "label",
      answer_ready: "silent",
      compare: "silent",
      chart: "silent",
      graph_write: "silent",
    },
  },
];

function phaseForStage(stage: string): { def: PhaseDef; mode: Mode } {
  for (const def of PHASES) {
    const mode = def.stages[stage];
    if (mode) return { def, mode };
  }
  return { def: PHASES[PHASES.length - 1], mode: "silent" };
}

type PhaseState = {
  def: PhaseDef;
  seen: boolean;
  lines: string[];
  chips: string[];
  items: string[];
};

function buildPhases(steps: StepEvent[]): PhaseState[] {
  const states: Record<PhaseId, PhaseState> = {
    search: { def: PHASES[0], seen: false, lines: [], chips: [], items: [] },
    review: { def: PHASES[1], seen: false, lines: [], chips: [], items: [] },
    synthesize: { def: PHASES[2], seen: false, lines: [], chips: [], items: [] },
    refine: { def: PHASES[3], seen: false, lines: [], chips: [], items: [] },
    finalize: { def: PHASES[4], seen: false, lines: [], chips: [], items: [] },
  };

  for (const s of steps) {
    const { def, mode } = phaseForStage(s.stage);
    const st = states[def.id];
    st.seen = true;

    if (mode === "label") {
      if (s.label && !st.lines.includes(s.label)) st.lines.push(s.label);
      if (s.detail && !st.chips.includes(s.detail)) st.chips.push(s.detail);
      if (s.items?.length)
        for (const it of s.items) if (it && !st.items.includes(it)) st.items.push(it);
    }
  }

  return PHASES.map((d) => states[d.id]).filter((st) => st.seen);
}

function Dots() {
  return (
    <span className="ml-1 inline-flex items-center gap-0.5 align-middle">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1 w-1 rounded-full bg-ink-soft/60 animate-pulse"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </span>
  );
}

export function ResearchSteps({
  steps,
  streaming,
  embedded = false,
}: {
  steps: StepEvent[];
  streaming: boolean;
  embedded?: boolean;
}) {
  const [open, setOpen] = useState(true);

  if (!steps.length) return null;

    let phases = buildPhases(steps);

  const uploadedOnly =
    steps.some((s) => s.evidence_mode === "uploaded") ||
    steps.some(
      (s) =>
        /reading uploaded document/i.test(s.label ?? "") ||
        /skipping external search/i.test(s.label ?? "")
    );

  if (uploadedOnly) {
    const uploadedMeta: Record<PhaseId, { title: string; placeholder: string }> = {
      search: {
        title: "Reading uploaded document",
        placeholder: "Reading uploaded document",
      },
      review: {
        title: "Reviewing uploaded document",
        placeholder: "Reviewing uploaded document",
      },
      synthesize: {
        title: "Writing from uploaded document",
        placeholder: "Writing from uploaded document",
      },
      refine: {
        title: "Checking document answer quality",
        placeholder: "Checking document answer quality",
      },
      finalize: {
        title: "Finalizing the response",
        placeholder: "Finalizing the response",
      },
    };

    phases = phases.map((st) => ({
      ...st,
      def: {
        ...st.def,
        title: uploadedMeta[st.def.id].title,
        placeholder: uploadedMeta[st.def.id].placeholder,
      },
    }));
  }
  const lastIndex = phases.length - 1;

  const rootCls = embedded
    ? "animate-fade-up"
    : "mb-3 rounded-xl border border-line bg-paper/70 shadow-sm shadow-black/5 animate-fade-up";

  const headerCls = embedded
    ? "flex w-full items-center gap-2 -mx-1 px-1 py-2 rounded-md text-left transition-colors hover:bg-paper-dim/50"
    : "flex w-full items-center gap-2 px-3.5 py-2.5 text-left";

  const bodyCls = embedded ? "pt-1 pb-1" : "border-t border-line px-3.5 py-3";

  return (
    <div className={rootCls}>
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className={headerCls}>
        <Layers className="h-3.5 w-3.5 text-indigo shrink-0" />
        <span className="text-[12.5px] font-medium text-ink">Steps taken by AI Agent</span>
        {streaming && <Loader2 className="h-3 w-3 animate-spin text-ink-soft shrink-0" />}
        <span className="ml-auto shrink-0 text-ink-soft">
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>

      {open && (
        <div className={bodyCls}>
          <div className="relative space-y-4 pl-4">
            <div className="absolute left-[3px] top-1.5 bottom-1.5 w-px bg-line" />

            {phases.map((st, i) => {
              const { def } = st;
              const Icon = def.icon;
              const active = streaming && i === lastIndex;
              const hasContent =
                st.lines.length > 0 || st.chips.length > 0 || st.items.length > 0;

              return (
                <div key={def.id} className="relative">
                  <span
                    className={`absolute -left-4 top-1 h-1.5 w-1.5 rounded-full ${
                      active ? "bg-indigo animate-pulse" : "bg-gold"
                    }`}
                  />
                  <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink">
                    {active ? (
                      <Loader2 className="h-3.5 w-3.5 text-indigo animate-spin" />
                    ) : (
                      <Icon className="h-3.5 w-3.5 text-ink-soft" />
                    )}
                    <span>{def.title}</span>
                  </div>

                  {(hasContent || active) && (
                    <div className="mt-1.5 space-y-1.5 rounded-lg border border-line bg-paper-dim/50 px-3 py-2">
                      {st.lines.map((line, j) => (
                        <p key={`l${j}`} className="text-[12px] leading-relaxed text-ink-soft">
                          {line}
                        </p>
                      ))}
                      {st.chips.map((chip, j) => (
                        <div
                          key={`c${j}`}
                          className="flex items-center gap-1.5 rounded-md bg-paper px-2.5 py-1.5 text-[11.5px] text-ink-soft"
                        >
                          <Search className="h-3 w-3 shrink-0 text-ink-soft/70" />
                          <span className="truncate">{chip}</span>
                        </div>
                      ))}
                      {st.items.length > 0 && (
                        <div className="space-y-1">
                          {st.items.map((it, k) => (
                            <div
                              key={`i${k}`}
                              className="flex items-center gap-2 rounded-md bg-paper px-2.5 py-1.5 text-[11.5px] text-ink"
                            >
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
                              <span className="truncate">{it}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {!hasContent && active && (
                        <p className="text-[12px] leading-relaxed text-ink-soft">
                          {def.placeholder}
                          <Dots />
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {!streaming && (
              <div className="relative">
                <span className="absolute -left-4 top-1 h-1.5 w-1.5 rounded-full bg-indigo" />
                <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink">
                  <Check className="h-3.5 w-3.5 text-indigo" />
                  Finished
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}