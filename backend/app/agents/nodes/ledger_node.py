import re
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import ReasoningLedger
from app.services.llm_client import get_llm, is_llm_rate_limited
from app.config import settings

_LEDGER_PROMPT = """You are a quantitative research analyst building a structured evidence ledger.
Your job is NOT to write prose. Your job is to extract a structured ledger of facts, numbers, claims, and disagreements from the retrieved sources.

USER QUESTION:
{query}

REQUIRED QUANTITATIVE VARIABLES:
{required_variables}

SCENARIO DIMENSIONS:
{scenario_dimensions}

RETRIEVED SOURCES:
{paper_block}

TASK:
1. extracted_variables: For each quantitative figure a source explicitly states, extract name, value, unit, source paper_id, and year. ONLY extract numbers literally present in a source.
2. unsupported_variables: List every required variable that NO source provides.
3. scenario_matrix: If the question involves trade-offs, build a scenario matrix.
4. contradictions: Where two sources disagree on a factual point, record both positions and both source paper_ids.
5. key_assumptions: List assumptions any quantitative conclusion depends on.
6. effect_sizes: For each outcome, extract the effect vs the specific comparator (e.g., "IF vs CR", "IF vs unrestricted"). Include outcome, comparator, effect, certainty, source_paper_id.
7. disagreements: If reviews or studies disagree, record:
   - topic
   - claim_a and source_a_paper_id
   - claim_b and source_b_paper_id
   - disagreement_type: one of "population", "intervention", "comparator", "outcome", "duration", "study_design", "analysis", "risk_of_bias", "publication_year", "statistical", "true_scientific"
   - likely_explanation: WHY they disagree
   - resolution: how to interpret the disagreement
   - confidence: 0.0-1.0
8. robustness_assessment: Map each outcome to "robust", "probable", "uncertain", or "unsupported".
9. claim_robustness: For each major claim, assess:
   - claim: the claim text
   - robustness: "robust", "probable", "uncertain", or "unsupported"
   - confidence: 0.0-1.0
   - supporting_sources: list of paper_ids
   - contradicting_sources: list of paper_ids
   - reason: why this robustness level

RULES:
NEVER invent a number. If no source states it, it belongs in unsupported_variables.
Every extracted value MUST cite a real paper_id from the sources above.
Preserve units, ranges, and stated uncertainty exactly.
Distinguish between intervention vs matched comparator comparisons — these answer different questions.
Separate different intervention protocols — do not pool them as identical.
Break down broad outcomes into specific measurable markers.

Return ONLY a JSON object matching ReasoningLedger.
"""


def _build_paper_block(
    papers: list[dict],
    max_papers: int = 6,
    max_abstract: int = 700,
) -> str:
    parts = []
    for i, p in enumerate(papers[:max_papers]):
        parts.append(
            f"[paper_id={i}]\n"
            f"Title: {p.get('title', '')}\n"
            f"Year: {p.get('published', '')}\n"
            f"Source: {p.get('source', '')}\n"
            f"Citations: {p.get('citation_count', 0)}\n"
            f"Abstract: {(p.get('summary') or p.get('text') or '')[:max_abstract]}"
        )
    return "\n\n".join(parts)


_NUM_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(%|percent|USD|EUR|GW|MW|kW|TWh|MWh|kWh|Gt|Mt|billion|million|trillion|"
    r"per year|/year|°C|degrees celsius)",
    re.IGNORECASE,
)


def _deterministic_ledger(papers: list[dict], answer_spec: dict) -> dict:
    required_vars = answer_spec.get("required_quantitative_variables") or []
    extracted = []
    for i, p in enumerate(papers[:6]):
        text = (p.get("summary") or p.get("text") or "")[:1200]
        for m in _NUM_PATTERN.finditer(text):
            extracted.append(
                {
                    "name": "stated_figure",
                    "value": m.group(1),
                    "unit": m.group(2),
                    "source_paper_id": i,
                    "year": str(p.get("published", ""))[:4],
                    "confidence": "low",
                }
            )
        if len(extracted) >= 12:
            break
    return {
        "extracted_variables": extracted[:12],
        "unsupported_variables": list(required_vars),
        "scenario_matrix": [],
        "contradictions": [],
        "key_assumptions": [],
        "ledger_source": "deterministic",
        "effect_sizes": [],
        "disagreements": [],
        "robustness_assessment": {},
        "claim_robustness": [],
    }


def ledger_node(state: AgentState) -> AgentState:
    term_coverage = state.get("term_coverage") or {}
    if term_coverage:
        covered = sum(1 for v in term_coverage.values() if v.get("status") == "covered")
        coverage_ratio = covered / len(term_coverage)
        if coverage_ratio < 0.30:
            print("[ledger] skipping: low coverage ratio")
            return {"reasoning_ledger": {}}
    answer_spec = state.get("answer_spec") or {}
    papers = state.get("ranked_papers") or []
    mode = state.get("response_mode", "normal")
    quantitative_required = bool(answer_spec.get("quantitative_required"))
    scenario_required = bool(answer_spec.get("scenario_analysis_required"))
    difficulty = int(answer_spec.get("difficulty_level", 3))

    if mode == "normal":
        return {"reasoning_ledger": None}
    if not (quantitative_required or scenario_required or difficulty >= 4):
        return {"reasoning_ledger": None}
    if not papers:
        return {"reasoning_ledger": _deterministic_ledger([], answer_spec)}
    if is_llm_rate_limited():
        return {"reasoning_ledger": _deterministic_ledger(papers, answer_spec)}

    required_vars = answer_spec.get("required_quantitative_variables") or []
    scenario_dims = answer_spec.get("scenario_dimensions") or []

    max_papers = getattr(settings, "LEDGER_MAX_PAPERS", 6)
    max_abstract = getattr(settings, "LEDGER_MAX_ABSTRACT_CHARS", 700)

    prompt = _LEDGER_PROMPT.format(
        query=state.get("query", ""),
        required_variables=(
            "\n".join(f"- {v}" for v in required_vars)
            or "none specified"
        ),
        scenario_dimensions=(
            "\n".join(f"- {d}" for d in scenario_dims)
            or "none specified"
        ),
        paper_block=_build_paper_block(
            papers, max_papers=max_papers, max_abstract=max_abstract
        )
        or "(no sources)",
    )

    try:
        llm = get_llm(temperature=0, task="structured")
        result = llm.with_structured_output(ReasoningLedger).invoke(
            [
                SystemMessage(
                    content=(
                        "You are a quantitative research analyst. "
                        "Return ONLY a valid JSON object matching "
                        "ReasoningLedger."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            config={
                "timeout": settings.REPORT_SECTION_TIMEOUT_NORMAL
            },
        )
        if isinstance(result, dict):
            ledger = ReasoningLedger.model_validate(result).model_dump()
        else:
            ledger = result.model_dump()
        ledger["ledger_source"] = "llm"
        n_vars = len(ledger.get("extracted_variables") or [])
        n_unsup = len(ledger.get("unsupported_variables") or [])
        n_disagree = len(ledger.get("disagreements") or [])
        print(
            f"[ledger] extracted={n_vars} unsupported={n_unsup} "
            f"disagreements={n_disagree}"
        )
        return {"reasoning_ledger": ledger}
    except Exception as e:
        print(
            f"[ledger_node] LLM extraction failed, using deterministic "
            f"fallback: {type(e).__name__}: {e}"
        )
        return {
            "reasoning_ledger": _deterministic_ledger(papers, answer_spec)
        }