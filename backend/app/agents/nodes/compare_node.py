import re
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import ComparisonTable
from app.services.llm_client import get_llm
from app.config import settings


_COMPARE_WORDS = (
    "compare",
    "comparison",
    "versus",
    "vs",
    "vs.",
    "difference between",
    "differences between",
    "trade-off",
    "tradeoff",
    "pros and cons",
    "advantages and disadvantages",
    "better",
    "faster",
    "more efficient",
    "outperform",
)

_DEFINITIONAL_STARTS = (
    "what is",
    "what are",
    "what's",
    "define",
    "definition of",
    "explain",
    "explain what",
    "what does",
    "what do",
    "how does",
    "how do",
    "describe",
    "overview of",
    "introduction to",
)

def _clean_table_cell(text: str) -> str:
    text = re.sub(r"\[paper_id=\d+\]", "", text)
    return text.replace("|", "/").strip()


def _is_definitional_query(query: str) -> bool:
    q = query.strip().lower()
    return any(q.startswith(p) for p in _DEFINITIONAL_STARTS)


def _has_explicit_compare_intent(query: str) -> bool:
    q = query.lower()
    return any(w in q for w in _COMPARE_WORDS)


def _gather_comparison_candidates(state: AgentState) -> list[str]:
    understanding = state.get("query_understanding") or {}
    candidates = []
    candidates.extend(understanding.get("methods_techniques") or [])
    candidates.extend(understanding.get("entities") or [])
    
    seen = set()
    deduped = []
    for c in candidates:
        key = c.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(c.strip())
            
    if not deduped and state.get("evidence_mode") == "uploaded":
        q = state.get("query", "")
        match = re.search(r"compare\s+(.*?)\s+and\s+(.*?)(?:\s+in\s+terms|\s+vs|\.|,|$)", q, re.IGNORECASE)
        if match:
            deduped = [match.group(1).strip(), match.group(2).strip()]
        else:
            match_vs = re.search(r"\b(.*?)\s+vs\.?\s+(.*?)\b", q, re.IGNORECASE)
            if match_vs:
                deduped = [match_vs.group(1).strip(), match_vs.group(2).strip()]
                
    return deduped


def _plan_wants_comparison(state: AgentState) -> bool:
    plan = state.get("report_plan") or {}

    module_ids = {m.get("module_id") for m in plan.get("modules", [])}
    if "comparative_analysis" in module_ids:
        return True

    needs = {str(n).lower() for n in plan.get("information_needs", [])}
    if "comparison" in needs or "compare" in needs or "tradeoffs" in needs:
        return True

    return False


def _should_attempt_comparison(state: AgentState) -> bool:
    query = state.get("query", "")
    explicit = _has_explicit_compare_intent(query)

    plan_wants = _plan_wants_comparison(state)

    if not plan_wants and not explicit:
        return False

    if _is_definitional_query(query) and not explicit:
        return False

    candidates = _gather_comparison_candidates(state)

    if len(candidates) >= 2 and (explicit or plan_wants):
        return True

    if explicit:
        return True

    return False


_COMPARISON_TABLE_PROMPT = """You are building ONE comparison table to help answer a research question.

USER QUESTION: {query}

CANDIDATE ITEMS TO COMPARE:
{candidates}

PAPERS AVAILABLE:
{paper_block}

Build a table where:
- columns = the specific things being compared (2 to 5 columns)
- rows = comparison dimensions (3 to 8 rows)
- each cell = a short, specific, factual claim under ~20 words
- cite [paper_id=N] only where a retrieved paper directly supports the claim

MANDATORY DIMENSION CATEGORIES TO CONSIDER (use these exact rows if applicable to the domain):
- Core Mechanism / Pathway (How it fundamentally works)
- Asymptotic / Theoretical Bounds (Big-O, physical limits, mathematical guarantees)
- Empirical Performance / Effect Size (Benchmark results, clinical outcomes, yield)
- Resource / Cost Profile (Compute, memory, capital, biological toll, time)
- Boundary Conditions / Failure Modes (Where it breaks down or is contraindicated)
- Ecosystem / Maturity (Tooling, standardization, clinical adoption, market penetration)

Rules for cells:
- Be highly specific and analytical. Use quantitative anchors where possible.
- Cite [paper_id=N] or [web_doc] where supported.
- Set applicable=false ONLY if the query truly has no comparable multi-item structure.
Return a ComparisonTable JSON object.
"""


def _generate_comparison_table(
    query: str,
    candidates: list[str],
    papers: list[dict],
    summaries: dict,
) -> ComparisonTable | None:
    llm = get_llm(temperature=0, task="fast")

    paper_block = "\n\n".join(
        [
            f"[{i}] {p.get('title', '')}: "
            f"{summaries.get(str(i), {}).get('key_contribution', '')} "
            f"{summaries.get(str(i), {}).get('findings', '')}"
            for i, p in enumerate(papers)
        ]
    ) or "(no papers retrieved — rely on established domain knowledge)"

    try:
        table = llm.with_structured_output(ComparisonTable).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to ComparisonTable."),
                HumanMessage(
                    content=_COMPARISON_TABLE_PROMPT.format(
                        query=query,
                        candidates="\n".join(f"- {c}" for c in candidates) or "(none extracted)",
                        paper_block=paper_block,
                    )
                ),
            ],
            config={"timeout": settings.REPORT_COMPARE_TIMEOUT},
        )

        if isinstance(table, dict):
            table = ComparisonTable.model_validate(table)

        return table

    except Exception as e:
        print(f"[compare_node] comparison table generation failed: {type(e).__name__}: {e}")
        return None


def _table_to_markdown(table: ComparisonTable) -> str:
    header = "| Dimension | " + " | ".join(table.columns) + " |"
    sep = "|---|" + "---|" * len(table.columns)

    lines = [header, sep]
    for row in table.rows:
        cells = [row.dimension] + row.values
        cells = (cells + [""] * (len(table.columns) + 1))[: len(table.columns) + 1]
        lines.append(
            "| "
            + " | ".join(_clean_table_cell(c) for c in cells)
            + " |"
        )

    return "\n".join(lines)


def _generate_basic_fallback_table(
    candidates: list[str],
    papers: list[dict],
    summaries: dict,
) -> str | None:
    columns = candidates[:5] if len(candidates) >= 2 else [
        p.get("title", f"Item {i + 1}")[:40] for i, p in enumerate(papers[:4])
    ]

    if len(columns) < 2:
        return None

    rows = [
        (
            "Key contribution",
            [
                (summaries.get(str(i), {}).get("key_contribution", "") or "See references")[:80]
                for i in range(len(columns))
            ],
        ),
        (
            "Relevance to query",
            [
                (summaries.get(str(i), {}).get("relevance_to_query", "") or "General background")[:80]
                for i in range(len(columns))
            ],
        ),
    ]

    header = "| Dimension | " + " | ".join(columns) + " |"
    sep = "|---|" + "---|" * len(columns)

    lines = [header, sep]

    for dim, values in rows:
        values = (values + [""] * len(columns))[:len(columns)]
        lines.append(
            "| "
            + dim
            + " | "
            + " | ".join(_clean_table_cell(v) for v in values)
            + " |"
        )

    return "\n".join(lines)



def compare_node(state: AgentState) -> AgentState:
    query = state.get("query", "")

    if not _should_attempt_comparison(state):
        print("[compare_node] skipping: no comparative structure / not planned")
        return {
            "comparison_table_markdown": None,
            "comparison_table_caption": None,
        }

    candidates = _gather_comparison_candidates(state)
    papers = state.get("ranked_papers", [])
    summaries = state.get("summaries", {})

    print(f"[compare_node] comparative intent detected, candidates={candidates}")

    table = _generate_comparison_table(query, candidates, papers, summaries)

    if table is None or not table.applicable or not table.columns or not table.rows:
        print("[compare_node] LLM table generation failed/inapplicable — trying fallback")

        fallback = _generate_basic_fallback_table(candidates, papers, summaries)

        if fallback:
            return {
                "comparison_table_markdown": fallback,
                "comparison_table_caption": "Comparison",
            }

        return {
            "comparison_table_markdown": None,
            "comparison_table_caption": None,
        }

    markdown = _table_to_markdown(table)

    return {
        "comparison_table_markdown": markdown,
        "comparison_table_caption": table.caption,
    }