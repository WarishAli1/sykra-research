from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import List

from app.agents.state import AgentState
from app.services.graph_store import graph_store
from app.services.llm_client import get_llm


class GraphEntities(BaseModel):
    """Extracted entities for knowledge graph."""
    concepts: List[str] = Field(description="Technical concepts, theories, frameworks, or phenomena discussed in the paper. Exclude common words, discourse markers, and generic terms.")
    methods: List[str] = Field(description="Specific algorithms, techniques, models, architectures, or methodologies used or proposed.")
    authors: List[str] = Field(description="Author names if present in text.")


_GENERIC_CONCEPTS = {
    "abstract", "introduction", "conclusion", "references",
    "figure", "table", "section", "chapter", "page",
    "method", "approach", "technique", "model", "system",
    "framework", "algorithm", "study", "paper", "research",
}


def _is_valid_concept(concept: str) -> bool:
    c = concept.lower().strip()
    if len(c) < 3:
        return False
    if c in _GENERIC_CONCEPTS:
        return False
    if c.split()[0] in {"the", "a", "an", "this", "that", "these", "those"}:
        return False
    return True


def _extract_entities_with_llm(text: str, title: str = "") -> GraphEntities:
    llm = get_llm(temperature=0)

    context = f"Title: {title}\n\n" if title else ""
    context += f"Abstract/Text: {text[:3000]}"

    prompt = f"""You are extracting entities for a research knowledge graph.

{context}

Extract entities following these rules:

CONCEPTS:
- Technical concepts, theories, frameworks, phenomena, or key ideas
- Examples: "attention mechanism", "transformer architecture", "gradient descent", "few-shot learning"
- DO NOT include: discourse markers (however, therefore), generic words (method, approach), author names, or publication metadata

METHODS:
- Specific algorithms, techniques, models, architectures, or methodologies
- Examples: "BERT", "ResNet", "LSTM", "Monte Carlo", "cross-entropy loss"
- Include model names, optimization methods, evaluation techniques

AUTHORS:
- Only extract if clearly identified as author names
- Look for patterns like "by X", "X et al.", or author lists

Return ONLY valid JSON matching the schema."""

    try:
        result = llm.with_structured_output(GraphEntities).invoke([
            SystemMessage(content="Extract entities for a knowledge graph. Return ONLY valid JSON."),
            HumanMessage(content=prompt)
        ], config={"timeout": 20})
        return result
    except Exception as e:
        print(f"[graph_write] LLM extraction failed: {e}")
        return GraphEntities(concepts=[], methods=[], authors=[])


def graph_write_node(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    contradictions = []
    entities = []

    for paper in state.get("ranked_papers", []):
        paper_link = paper.get("link", "")
        if not paper_link:
            continue

        graph_store.upsert_paper(paper, session_id)

        paper_text = paper.get("text") or paper.get("summary") or paper.get("title", "")
        extracted = _extract_entities_with_llm(paper_text, paper.get("title", ""))

        for author_name in extracted.authors:
            if author_name and len(author_name.strip()) > 2:
                clean_name = author_name.strip()
                graph_store.upsert_author(clean_name, paper_link)
                entities.append({"type": "author", "name": clean_name, "paper": paper_link})

        for concept in extracted.concepts:
            if concept and len(concept.strip()) >= 3 and _is_valid_concept(concept):
                clean_concept = concept.strip().lower()
                graph_store.link_concept(clean_concept, paper_link)
                entities.append({"type": "concept", "name": clean_concept, "paper": paper_link})

        for method in extracted.methods:
            if method and len(method.strip()) >= 2:
                clean_method = method.strip().lower()
                graph_store.link_method(clean_method, paper_link)
                entities.append({"type": "method", "name": clean_method, "paper": paper_link})

    return {
        **state,
        "graph_contradictions": contradictions,
        "graph_entities": entities,
    }
