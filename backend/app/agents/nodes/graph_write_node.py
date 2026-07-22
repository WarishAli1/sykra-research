from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.services.graph_store import graph_store
from app.services.llm_client import get_llm

_MAX_CONCEPTS_PER_PAPER = 6
_MAX_METHODS_PER_PAPER = 6
_ABSTRACT_CHARS_FOR_EXTRACTION = 1200


class PaperEntities(BaseModel):
    """Concepts and methods actually discussed in ONE paper — not author
    names, place names, or generic capitalized words. This replaces the old
    regex approach (re.findall on capitalized words), which had no notion of
    what a 'concept' actually is and surfaced things like author names and
    university names as if they were research concepts."""
    paper_id: str = Field(description="Index matching the [paper_id=N] marker given for this paper")
    concepts: list[str] = Field(
        default_factory=list,
        description=f"Up to {_MAX_CONCEPTS_PER_PAPER} real research concepts/topics "
                    "actually discussed in this paper (e.g. 'transfer learning', "
                    "'causal inference', 'attention mechanism'). NEVER include "
                    "author names, institution names, place names, or generic "
                    "words that merely appear in the text.",
    )
    methods: list[str] = Field(
        default_factory=list,
        description=f"Up to {_MAX_METHODS_PER_PAPER} specific named methods, "
                    "algorithms, models, or techniques the paper actually uses "
                    "or proposes (e.g. 'ResNet', 'Grad-CAM', 'BCE loss'). Empty "
                    "list if none are clearly stated.",
    )


class BatchPaperEntities(BaseModel):
    papers: list[PaperEntities]


_ENTITY_EXTRACTION_PROMPT = """Extract the real research concepts and named methods/techniques discussed in each paper below.

PAPERS:
{paper_block}

Rules:
- concepts = genuine research topics/ideas the paper is actually about. Never
  author names, universities, cities, or incidental capitalized words.
- methods = specific named algorithms/models/techniques the paper uses or
  proposes. Leave empty if the paper states none clearly.
- Return one PaperEntities entry per paper, in the same order, using the
  paper_id given.

Return a BatchPaperEntities JSON object matching the schema exactly."""


def _build_paper_block(papers: list[dict]) -> str:
    parts = []
    for i, p in enumerate(papers):
        text = (p.get("summary") or p.get("text") or "")[:_ABSTRACT_CHARS_FOR_EXTRACTION]
        parts.append(f"[paper_id={i}]\nTitle: {p.get('title', '')}\nAbstract: {text}")
    return "\n\n".join(parts)


def _extract_entities_batch(papers: list[dict]) -> dict[str, PaperEntities]:
    """One dedicated, cheap structured-output call covering every ranked
    paper for this turn — same pattern as chart_node's ChartSpec and
    compare_node's ComparisonTable. Uses task='light' to route to the
    fastest provider tier (Cerebras first, per llm_client.ORDER_MAP)."""
    if not papers:
        return {}

    llm = get_llm(temperature=0, task="light")
    paper_block = _build_paper_block(papers)

    try:
        result: BatchPaperEntities = llm.with_structured_output(BatchPaperEntities).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to BatchPaperEntities. No text before or after."),
                HumanMessage(content=_ENTITY_EXTRACTION_PROMPT.format(paper_block=paper_block)),
            ],
            config={"timeout": 20},
        )
        if isinstance(result, dict):
            result = BatchPaperEntities.model_validate(result)
        return {e.paper_id: e for e in result.papers}
    except Exception as e:
        print(f"[graph_write_node] entity extraction failed: {type(e).__name__}: {e}")
        return {}


def graph_write_node(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    turn_id = state.get("turn_id")
    contradictions = []
    entities = []

    papers = state.get("ranked_papers", [])
    entities_by_id = _extract_entities_batch(papers)

    for i, paper in enumerate(papers):
        paper_link = paper.get("link", "")
        if not paper_link:
            continue

        graph_store.upsert_paper(paper, session_id, turn_id=turn_id)

        paper_entities = entities_by_id.get(str(i))
        if paper_entities is None:
            continue

        for c in paper_entities.concepts[:_MAX_CONCEPTS_PER_PAPER]:
            c = c.strip()
            if not c:
                continue
            graph_store.link_concept(c, paper_link)
            entities.append({"type": "concept", "name": c.lower(), "paper": paper_link})

        for m in paper_entities.methods[:_MAX_METHODS_PER_PAPER]:
            m = m.strip()
            if not m:
                continue
            graph_store.link_method(m, paper_link)
            entities.append({"type": "method", "name": m.lower(), "paper": paper_link})

    for i, paper_a in enumerate(papers):
        for paper_b in papers[i + 1:]:
            link_a = paper_a.get("link", "")
            link_b = paper_b.get("link", "")
            if link_a and link_b:
                graph_store.link_citation(link_a, link_b)

    return {
        **state,
        "graph_contradictions": contradictions,
        "graph_entities": entities,
    }