from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.state import AgentState
from app.agents.schemas import ComparisonTable
from app.services.llm_client import get_llm


def _gather_comparison_candidates(state: AgentState) -> list[str]:
    """Pull candidate 'things being compared' from query understanding —
    methods/techniques and named entities are the most reliable signal that
    the user is weighing multiple named items against each other (as opposed
    to e.g. comparing findings across an unspecified set of papers)."""
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
    return deduped


def _should_attempt_comparison(state: AgentState) -> bool:
    """True when there's real structural signal of >=2 comparable items —
    not a keyword match on the word 'compare' or 'table'. This deliberately
    also fires on queries that never say the word 'table' at all, since a
    query like 'Transformer vs RNN vs LSTM: which is more efficient?' should
    still get a guaranteed table."""
    candidates = _gather_comparison_candidates(state)
    if len(candidates) >= 2:
        return True

    q = state.get("query", "").lower()
    if any(w in q for w in ("compare", "versus", " vs ", "vs.", "difference between", "trade-off", "tradeoff", "comparison table")):
        return True

    understanding = state.get("query_understanding") or {}
    subtopics = understanding.get("subtopics") or []
    return len(subtopics) >= 2


_COMPARISON_TABLE_PROMPT = """You are building ONE comparison table to help answer a research question.

USER QUESTION: {query}

CANDIDATE ITEMS TO COMPARE (from query understanding — use these as the
table's columns if they genuinely are the subject of comparison; ignore any
that don't fit):
{candidates}

PAPERS AVAILABLE (title + key contribution/findings — use these ONLY to
ground comparison claims; cite via [paper_id=N] inline in cell text where a
specific paper directly supports that cell's claim, otherwise rely on
well-established domain knowledge for that cell and do not force a citation):
{paper_block}

Build a table where:
- columns = the specific things being compared (e.g. "Transformer", "RNN", "LSTM")
  — 2 to 5 columns. Do NOT make columns out of unrelated ideas.
- rows = the DIMENSIONS of comparison (e.g. "Time complexity", "Parallelizability",
  "Long-range dependency handling", "Memory cost") — 3 to 8 rows. Choose
  dimensions that actually matter for answering the user's question.
- each cell = a short, specific, factual claim (under ~20 words). Cite
  [paper_id=N] only where a specific retrieved paper substantiates the claim.

Set applicable=false ONLY if the query truly has no comparable multi-item
structure (e.g. a single-concept explainer question) — this should be rare
given the candidates provided.

Return a ComparisonTable JSON object matching the schema exactly."""


def _generate_comparison_table(query: str, candidates: list[str], papers: list[dict], summaries: dict) -> ComparisonTable | None:
    llm = get_llm(temperature=0, task="light")

    paper_block = "\n\n".join([
        f"[{i}] {p.get('title', '')}: "
        f"{summaries.get(str(i), {}).get('key_contribution', '')} "
        f"{summaries.get(str(i), {}).get('findings', '')}"
        for i, p in enumerate(papers)
    ]) or "(no papers retrieved — rely on established domain knowledge)"

    try:
        table = llm.with_structured_output(ComparisonTable).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to ComparisonTable. No text before or after."),
                HumanMessage(content=_COMPARISON_TABLE_PROMPT.format(
                    query=query,
                    candidates="\n".join(f"- {c}" for c in candidates) or "(none extracted — infer from the query itself)",
                    paper_block=paper_block,
                )),
            ],
            config={"timeout": 30},
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
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines)


def _generate_basic_fallback_table(candidates: list[str], papers: list[dict], summaries: dict) -> str | None:
    """Last-resort table when the dedicated LLM call fails or returns
    applicable=false, used ONLY when the user's query had explicit
    comparison intent. Built from whatever candidates/papers we have —
    no LLM call, so it's instant and always succeeds if we have >=2
    candidates or >=2 papers to compare."""
    columns = candidates[:5] if len(candidates) >= 2 else [
        p.get("title", f"Item {i+1}")[:40] for i, p in enumerate(papers[:4])
    ]
    if len(columns) < 2:
        return None

    rows = [
        ("Key contribution", [
            (summaries.get(str(i), {}).get("key_contribution", "") or "See references")[:80]
            for i in range(len(columns))
        ]),
        ("Relevance to query", [
            (summaries.get(str(i), {}).get("relevance_to_query", "") or "General background")[:80]
            for i in range(len(columns))
        ]),
    ]

    header = "| Dimension | " + " | ".join(columns) + " |"
    sep = "|---|" + "---|" * len(columns)
    lines = [header, sep]
    for dim, values in rows:
        values = (values + [""] * len(columns))[:len(columns)]
        lines.append("| " + dim + " | " + " | ".join(v.replace("|", "/") for v in values) + " |")
    return "\n".join(lines)


def compare_node(state: AgentState) -> AgentState:
    query = state.get("query", "")

    if not _should_attempt_comparison(state):
        print("[compare_node] skipping: no comparative structure detected")
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
        print("[compare_node] LLM table generation failed/inapplicable — trying no-LLM fallback")
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